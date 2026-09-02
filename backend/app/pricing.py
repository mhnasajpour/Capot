"""Fair-price engine.

The product's core claim is that we can tell a buyer what a car is *actually*
worth — including the ~36% of listings whose sellers refuse to publish a price
("توافقی"). That is a supervised regression problem with a twist: the rows we
most want to score are exactly the rows with no label.

Approach:
  1. Train a gradient-boosted regressor on log(price) over the priced listings.
     Log-space matters because Iranian car prices span three orders of magnitude
     (~100M to ~45B toman); absolute error on a Pride is meaningless next to a
     Benz, but *relative* error is comparable across the range.
  2. Predict a fair price for every listing, priced or not.
  3. Report confidence from how many true comparables back the estimate, walking
     trim -> model -> global. A number nobody can check is worse than no number,
     so a thin cohort must visibly lower confidence rather than quietly bluff.

    python -m app.pricing --train
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from . import db

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "price_model.pkl"
#: Held-out error, written beside the model whenever it is retrained. Until this
#: existed the metrics were logged and then lost, so nothing downstream could
#: quote what the model actually measures — which is exactly what an estimate
#: needs in order to publish an honest range around itself. See
#: `appraise.price_band`.
METRICS_PATH = MODEL_PATH.with_name("price_model_metrics.json")

# Guard rails against junk rows: a car advertised below 50M toman is a parts
# listing or a typo, and above 100B is a supercar outlier that would distort
# the loss for every ordinary listing.
MIN_VALID_PRICE = 50_000_000
MAX_VALID_PRICE = 100_000_000_000
MAX_VALID_MILEAGE = 1_500_000

NUMERIC_FEATURES = [
    "age", "mileage_km", "body_grade", "engine_volume_l",
    "power_hp", "acceleration_s", "consumption_l100", "dealer_score",
]
CATEGORICAL_FEATURES = [
    "brand", "model", "transmission", "fuel", "body_type", "seller", "city",
    # Which site the ad came from. The platforms differ systematically — Divar
    # skews to private sellers and carries fewer spec fields — so letting the
    # model see the source stops that difference being attributed to the car.
    "source",
]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Cohort depth at which we trust a trim-level comparable set on its own.
MIN_COHORT = 5


def build_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in FEATURES:
        if col not in df.columns:
            df[col] = np.nan
    # HistGradientBoosting handles NaN natively; categoricals just need to be
    # strings for the one-hot encoder.
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype("object").where(df[col].notna(), "unknown").astype(str)
    for col in NUMERIC_FEATURES:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.loc[df["mileage_km"] > MAX_VALID_MILEAGE, "mileage_km"] = np.nan
    return df


# A price this far from its cohort's median is not a price for that car. Chosen
# to clear the deposit listings (~2% of a new car's value) with room to spare,
# while leaving genuine bargains and premium trims inside the training set.
COHORT_PRICE_FLOOR_RATIO = 0.35
COHORT_PRICE_CEILING_RATIO = 3.0
MIN_COHORT_FOR_OUTLIER_CHECK = 3


def implausible_vs_cohort(df: pd.DataFrame) -> pd.Series:
    """Flag prices that cannot be this car's actual price.

    Some dealers advertise the *down-payment* as the price: brand-new Denas
    listed at 50M toman when the model is worth ~2.1B. They are ordinary
    `lumpsum` listings, so no field identifies them — but they are wildly out of
    line with their own cohort, which does.

    A global price floor cannot catch these without also excluding legitimately
    cheap old cars, so we judge each price against the median of its own
    brand+model+year cohort.
    """
    priced = df["price_toman"].notna()
    cohort = df.loc[priced].groupby(["brand", "model", "year"])["price_toman"]
    medians = cohort.transform("median")
    counts = cohort.transform("size")

    flagged = pd.Series(False, index=df.index)
    checkable = counts >= MIN_COHORT_FOR_OUTLIER_CHECK
    ratio = df.loc[priced, "price_toman"] / medians
    flagged.loc[priced] = checkable & (
        (ratio < COHORT_PRICE_FLOOR_RATIO) | (ratio > COHORT_PRICE_CEILING_RATIO)
    )
    return flagged.fillna(False)


# Listings that sell a *claim on* a car rather than a car: delivery vouchers
# (حواله), pre-sales (پیش فروش) and factory registrations (ثبت نام). Their
# advertised figure is a deposit, so it must never be compared against the
# market price of the finished car — otherwise they dominate every ranking as
# fake 90%-below-market bargains.
PRESALE_MARKERS = ("حواله", "پیش فروش", "پیش‌فروش", "ثبت نام", "ثبت‌نام", "قرعه کشی", "قرعه‌کشی")

PRICE_OK = "ok"
PRICE_DEPOSIT = "deposit"


def is_presale_listing(title: str | None, description: str | None = None) -> bool:
    """True when the listing sells an allocation rather than a car."""
    text = f"{title or ''} {description or ''}"
    return any(marker in text for marker in PRESALE_MARKERS)


def price_flag(row: dict, implausible: bool) -> str:
    """Classify whether a listing's published price is really the car's price."""
    if implausible or is_presale_listing(row.get("title"), row.get("description")):
        return PRICE_DEPOSIT
    return PRICE_OK


def trainable_mask(df: pd.DataFrame) -> pd.Series:
    """Rows usable as supervision: a real published price in a sane range."""
    presale = df["title"].fillna("").apply(lambda t: is_presale_listing(t))
    return (
        df["price_toman"].notna()
        & (df["price_toman"] >= MIN_VALID_PRICE)
        & (df["price_toman"] <= MAX_VALID_PRICE)
        & df["age"].notna()
        & ~implausible_vs_cohort(df)
        & ~presale
    )


def make_pipeline() -> Pipeline:
    return Pipeline(
        [
            (
                "encode",
                ColumnTransformer(
                    [(
                        "cat",
                        # Dense output: HistGradientBoosting rejects sparse input.
                        # min_frequency collapses the long tail of rare models and
                        # cities into an "infrequent" bucket, which keeps the matrix
                        # narrow and stops one-off categories from being memorised.
                        OneHotEncoder(
                            handle_unknown="infrequent_if_exist",
                            min_frequency=5,
                            sparse_output=False,
                        ),
                        CATEGORICAL_FEATURES,
                    )],
                    remainder="passthrough",
                ),
            ),
            (
                "model",
                HistGradientBoostingRegressor(
                    loss="absolute_error",  # robust to the outlier asking prices that survive filtering
                    max_iter=400,
                    learning_rate=0.06,
                    max_depth=7,
                    min_samples_leaf=8,
                    l2_regularization=0.5,
                    random_state=42,
                ),
            ),
        ]
    )


def train(rows: list[dict]) -> tuple[Pipeline, dict[str, Any]]:
    """Fit the model and report honest held-out error."""
    df = build_frame(rows)
    train_df = df[trainable_mask(df)]
    if len(train_df) < 50:
        raise RuntimeError(f"not enough priced listings to train: {len(train_df)}")

    X = train_df[FEATURES]
    y = np.log(train_df["price_toman"].astype(float))

    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    pipe = make_pipeline()
    pipe.fit(X_tr, y_tr)

    pred_log = pipe.predict(X_te)
    # Report error in toman-space, which is what a user would actually feel.
    pred = np.exp(pred_log)
    true = np.exp(y_te)
    metrics = {
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "mape": float(mean_absolute_percentage_error(true, pred)),
        "median_ape": float(np.median(np.abs(pred - true) / true)),
        "r2_log": float(r2_score(y_te, pred_log)),
        "by_source": _error_by_source(train_df.loc[X_te.index, "source"], true, pred),
    }

    # Refit on everything for the shipped model — the split above was only to
    # measure, and throwing away 20% of a few thousand rows is expensive.
    pipe.fit(X, y)
    return pipe, metrics


def _error_by_source(sources: pd.Series, true: np.ndarray, pred: np.ndarray) -> dict:
    """Held-out error split by the site each listing came from.

    A single average hides the thing most worth knowing. Sources differ in what
    they publish — Divar supplies none of engine size, power, consumption or
    seller rating — and that shows up as error, not as a warning. Reporting one
    blended number would let a sparse source hide behind a dense one, which is
    the same failure `_confidence` exists to prevent. Computed here rather than
    by hand so the README's table cannot quietly drift from the model.
    """
    ape = np.abs(pred - true) / true
    out: dict[str, dict] = {}
    for source in sorted(set(sources)):
        mask = (sources == source).to_numpy()
        if not mask.any():
            continue
        out[str(source)] = {
            "n": int(mask.sum()),
            "mape": float(ape[mask].mean()),
            "median_ape": float(np.median(ape[mask])),
        }
    return out


def _cohort_counts(df: pd.DataFrame) -> tuple[dict, dict]:
    """Count *priced* comparables per trim-cohort and per model-cohort.

    Only priced listings count as comparables: a cohort of ten negotiable ads
    supports nothing.
    """
    priced = df[df["price_toman"].notna()]
    trim = priced.groupby(["brand", "model", "trim_en", "year"]).size().to_dict()
    model = priced.groupby(["brand", "model", "year"]).size().to_dict()
    return trim, model


# Spec fields that materially sharpen a price estimate. A listing missing all of
# them is priced almost entirely from brand/model/year/mileage.
EVIDENCE_FEATURES = ["engine_volume_l", "power_hp", "consumption_l100", "dealer_score"]


def confidence_for(n_comparables: int, cohort_level: str, evidence: float = 1.0) -> float:
    """Map comparable depth and evidence quality to a 0-1 confidence.

    Saturating rather than linear in depth: the jump from 2 to 8 comparables
    matters far more than 40 to 60. Model-level cohorts are penalised because
    they mix trims.

    Public because `appraise.py` scores a car that is not in the corpus and must
    reach the same number by the same route — two ways of computing confidence
    would be two different promises about the same estimate.

    `evidence` is the share of spec fields the listing actually carries, and it
    matters as much as depth. Measured on a held-out split, error is very
    different by source: Bama listings score 10.0% MAPE, Divar listings 28.0%,
    and the cause is feature sparsity — Divar supplies none of engine size,
    power, consumption or dealer rating. Presenting both estimates with equal
    confidence would be the "number nobody can check" this module exists to
    avoid, so a sparse listing must visibly carry a weaker number.
    """
    base = 1.0 - np.exp(-n_comparables / 6.0)
    penalty = {"trim": 1.0, "model": 0.82, "global": 0.55}[cohort_level]
    # Floor at 0.6 so a sparse listing is discounted, not dismissed: brand,
    # model, year and mileage still carry most of the signal.
    evidence_factor = 0.6 + 0.4 * max(0.0, min(1.0, evidence))
    return round(float(min(base * penalty * evidence_factor, 0.98)), 3)


def estimate(pipe: Pipeline, rows: list[dict]) -> list[dict]:
    """Produce a fair-price row for every listing."""
    df = build_frame(rows)
    if df.empty:
        return []

    scorable = df["age"].notna()
    preds = np.full(len(df), np.nan)
    if scorable.any():
        preds[scorable.to_numpy()] = np.exp(pipe.predict(df.loc[scorable, FEATURES]))

    trim_counts, model_counts = _cohort_counts(df)
    # Share of spec fields present, per row — drives the evidence discount above.
    evidence = df[EVIDENCE_FEATURES].notna().mean(axis=1).to_numpy()
    implausible = implausible_vs_cohort(df).to_numpy()

    out: list[dict] = []
    for idx, row in enumerate(df.itertuples(index=False)):
        fair = preds[idx]
        if not np.isfinite(fair):
            out.append({
                "code": row.code, "fair_price": None, "price_delta_pct": None,
                "confidence": None, "n_comparables": 0, "cohort_level": None,
                "price_flag": PRICE_OK,
            })
            continue

        # Exclude the listing itself from its own comparable count.
        trim_n = max(trim_counts.get((row.brand, row.model, row.trim_en, row.year), 0) - 1, 0)
        model_n = max(model_counts.get((row.brand, row.model, row.year), 0) - 1, 0)
        if trim_n >= MIN_COHORT:
            level, n = "trim", trim_n
        elif model_n >= MIN_COHORT:
            level, n = "model", model_n
        else:
            level, n = "global", max(trim_n, model_n)

        flag = price_flag(
            {"title": getattr(row, "title", None), "description": getattr(row, "description", None)},
            bool(implausible[idx]),
        )

        # A deposit or voucher figure is not this car's price, so it gets no
        # delta — comparing it to the market would invent a 90% discount.
        asking = row.price_toman
        delta = None
        if flag == PRICE_OK and asking and MIN_VALID_PRICE <= asking <= MAX_VALID_PRICE:
            delta = round(float((asking - fair) / fair * 100), 1)

        out.append({
            "code": row.code,
            "fair_price": int(round(fair / 1_000_000) * 1_000_000),  # round to the nearest million
            "price_delta_pct": delta,
            "confidence": confidence_for(n, level, float(evidence[idx])),
            "n_comparables": int(n),
            "cohort_level": level,
            "price_flag": flag,
        })
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Train the fair-price model and score the corpus")
    ap.add_argument("--train", action="store_true", help="retrain before scoring")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    conn = db.connect()
    db.init_db(conn)
    rows = db.fetch_all(conn)
    log.info("loaded %d listings", len(rows))

    if args.train or not MODEL_PATH.exists():
        pipe, metrics = train(rows)
        joblib.dump(pipe, MODEL_PATH)
        METRICS_PATH.write_text(json.dumps(metrics, indent=1), encoding="utf-8")
        log.info(
            "trained on %d rows | holdout MAPE=%.1f%% median APE=%.1f%% R2(log)=%.3f",
            metrics["n_train"], 100 * metrics["mape"],
            100 * metrics["median_ape"], metrics["r2_log"],
        )
        for source, stats in metrics["by_source"].items():
            log.info(
                "  %-9s n=%-5d MAPE=%.1f%% median APE=%.1f%%",
                source, stats["n"], 100 * stats["mape"], 100 * stats["median_ape"],
            )
    else:
        pipe = joblib.load(MODEL_PATH)

    estimates = estimate(pipe, rows)
    written = db.replace_pricing(conn, estimates)
    priced = sum(1 for e in estimates if e["fair_price"])
    log.info("scored %d listings (%d with an estimate)", written, priced)

    hidden = [e for e in estimates if e["fair_price"] and e["price_delta_pct"] is None]
    log.info("gave a price to %d listings that had none", len(hidden))
    conn.close()


if __name__ == "__main__":
    main()

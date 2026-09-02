"""Price a car that is not in the corpus — the one the user already owns.

Every other path through this app starts from a crawled listing. This one starts
from a person: they describe their car in Persian prose, or fill a form, or both,
and the same machinery that prices 22,820 ads prices theirs.

Nothing here is new logic. The brand and model come from the vocabulary
`lexicon.py` derived from the corpus; the year, mileage, gearbox and fuel come
from the rule parser `query.py` already runs on every search; the paint condition
comes from `normalize.infer_body_status`, which was written to read exactly this
kind of prose off a Divar seller; the risk phrases come from `enrich.scan_text`;
the estimate comes from the shipped regressor and the confidence from
`pricing.confidence_for`. The work of this module is assembly and refusal.

Refusal matters as much as assembly. A car we cannot identify, or one with no
model year, gets an honest `status` and **no number** — the same answer search
gives when a query names a car we do not stock. A fabricated valuation is worse
than no valuation: the person on the other side is about to price a real sale on
it.

Two things about a user-described car differ from a crawled listing, and both
show up as lower confidence rather than being papered over:

  * **No trim.** A form does not ask for `trim_en` ('2.0ltype4'), so the
    comparable cohort starts one level coarser than a listing's does.
  * **Thin evidence.** Nobody types their car's power output or fuel
    consumption, and `pricing.confidence_for` discounts an estimate by how much
    spec evidence stands behind it.

So a good appraisal here lands around 0.5-0.6 confidence, not 0.9, and the band
is correspondingly wider. That is the honest number.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, fields as dataclass_fields
from typing import Any

import numpy as np

from . import pricing
from .enrich import scan_text
from .health import health_band, score_listing
from .lexicon import Lexicon, match as match_entities
from .normalize import (
    CURRENT_GREGORIAN_YEAR,
    body_status_grade,
    infer_body_status,
)
from .query import Intent, parse_with_rules
from .rank import order_all

log = logging.getLogger(__name__)

#: How many listings like theirs to hand back.
MATCH_LIMIT = 12

#: Model years either side of theirs that still count as the same car. Two is
#: what the market treats as interchangeable for a domestic model, and it is
#: wide enough to keep a cohort populated for a marque with thin coverage.
YEAR_WINDOW = 2

#: Priced comparables below which the model-level cohort is too thin to stand on
#: and we widen to the brand. Matches `pricing.MIN_COHORT`, which is the same
#: judgement made about a crawled listing.
MIN_COHORT = pricing.MIN_COHORT

#: Fallback held-out error, used when the model has been trained by a version
#: that did not write `price_model_metrics.json` beside it. These are the figures
#: the README publishes for the shipped model, so a checkout with no metrics file
#: quotes a real measurement rather than a guess — it is simply an older one.
FALLBACK_METRICS = {"median_ape": 0.081, "mape": 0.156}


# ------------------------------------------------------------------ the input


@dataclass
class CarInput:
    """One car as its owner describes it.

    Field names match the corpus columns exactly, because `to_row` hands this
    straight to `pricing.build_frame` and `health.score_listing`, which read the
    listing schema. A translation layer here would be a place for the two to
    drift apart.
    """

    brand: str | None = None
    model: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    transmission: str | None = None
    fuel: str | None = None
    body_status: str | None = None
    body_type: str | None = None
    body_color: str | None = None
    city: str | None = None
    seller: str | None = None
    engine_volume_l: float | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def age(self) -> int | None:
        return (CURRENT_GREGORIAN_YEAR - self.year) if self.year else None

    def to_row(self) -> dict[str, Any]:
        """A listing-shaped row, so every downstream reader sees what it knows.

        The risk phrases are scanned out of the description here rather than by
        the caller, because `health.score_listing` reads `red_flags` and
        `positives` off the row and would otherwise silently score the car as
        though its owner had disclosed nothing.
        """
        flags = scan_text(self.description or "")
        return {
            "code": "__appraisal__",
            "brand": self.brand,
            "model": self.model,
            "trim_en": None,
            "year": self.year,
            "age": self.age,
            "mileage_km": self.mileage_km,
            "transmission": self.transmission,
            "fuel": self.fuel,
            "body_status": self.body_status,
            "body_grade": body_status_grade(self.body_status),
            "body_type": self.body_type,
            "body_color": self.body_color,
            "city": self.city,
            # A private sale is what someone appraising their own car is
            # overwhelmingly doing, and the model reads `seller` as a feature.
            "seller": self.seller or "شخصی",
            "engine_volume_l": self.engine_volume_l,
            "description": self.description,
            # Fields the model expects and a person cannot supply. Left as None
            # so `build_frame` reads them as missing — which is true, and is what
            # the evidence discount below is computed from.
            "power_hp": None,
            "acceleration_s": None,
            "consumption_l100": None,
            "dealer_score": None,
            "price_toman": None,
            "title": None,
            # `source` is a model feature: the platforms differ systematically in
            # what they publish, and a self-described car resembles the sparse
            # end of that spectrum far more than it resembles a Bama spec sheet.
            "source": "divar",
            "authenticated": False,
            "image_count": None,
            "insurance_months": None,
            "chassis_status": None,
            "red_flags": flags["red_flags"],
            "positives": flags["positives"],
        }


_FIELD_NAMES = [f.name for f in dataclass_fields(CarInput)]


def merge(parsed: CarInput, explicit: CarInput) -> CarInput:
    """Overlay what the user stated onto what we read from their prose.

    Explicit wins, field by field. This is the appraisal side of
    `features.Filters.apply_to`, and it is the same argument: they can see a
    dropdown, they cannot see a parser. A description saying «مدل ۹۵» and a form
    saying 1396 must resolve to 1396, because only one of those did the user
    check before pressing the button.
    """
    values = {
        name: (
            getattr(explicit, name)
            if getattr(explicit, name) not in (None, "")
            else getattr(parsed, name)
        )
        for name in _FIELD_NAMES
    }
    return CarInput(**values)


def _brand_support(model_support: dict) -> dict[str, int]:
    """Priced listings per brand, folded up from the per-model counts."""
    totals: dict[str, int] = {}
    for (brand, _model), count in model_support.items():
        totals[brand] = totals.get(brand, 0) + count
    return totals


def _pick(candidates: set, support: dict | None) -> Any:
    """Choose one entity when a name resolves to several, by corpus depth.

    «۲۰۶» resolves to *both* `peugeot/206ir` and `peugeot/206`, because
    `lexicon.build` registers the assembly suffix and the bare name as aliases of
    each other. Search never has to choose — it filters on every pair at once —
    but a price model takes one `model` value, so an appraisal must.

    Picking alphabetically put a 206 in the 27-row `206` cohort while its 1,197
    real comparables sat under `206ir`, which is the رانا/`runna` failure the
    brand backfill in `db.py` was written to fix, arriving through a third door:
    the slug a buyer's words resolve to disagreed with the slug the crawl
    learned. So the slug with the most priced listings behind it wins — that is
    the cohort the estimate will actually be measured against. The name itself
    breaks a tie, so a corpus with no support for either is still deterministic.
    """
    return max(candidates, key=lambda item: ((support or {}).get(item, 0), item))


def parse_description(
    text: str, lex: Lexicon, model_support: dict | None = None
) -> CarInput:
    """Read a car out of the owner's own Persian.

    Deliberately assembled from the parsers that already exist rather than a new
    one. `lexicon.match` is the corpus-derived vocabulary search uses — ~80
    brands, ~440 models, tolerant of Persian orthography and typos — and
    `query.parse_with_rules` already knows «مدل ۱۳۹۵», «کارکرد ۱۲۰ هزار»,
    «اتوماتیک» and «دوگانه». Only the fields' *meaning* differs: a search reads
    «کارکرد ۱۲۰ هزار» as a ceiling to filter by, and an appraisal reads it as a
    fact about one car. The numbers extracted are identical, so the parser is
    reused and only the fields read off the `Intent` change. Budget, use case and
    priorities are ignored outright — a description is not a shopping query.
    """
    text = (text or "").strip()
    if not text:
        return CarInput()

    intent: Intent = parse_with_rules(text)
    entities = match_entities(text, lex)

    brand: str | None = None
    model: str | None = None
    if entities.models:
        # `match` narrows models to a named brand when the query gives both, so
        # every pair here is consistent; what differs is how much corpus stands
        # behind each. See `_pick`.
        brand, model = _pick(entities.models, model_support)
    elif entities.brands:
        brand = _pick(
            entities.brands,
            # Brand depth, summed over that brand's models, from the same table.
            _brand_support(model_support) if model_support else None,
        )

    body_status, _grade = infer_body_status(text)

    return CarInput(
        brand=brand,
        model=model,
        # The rule parser stores a year as the floor of a search range; here the
        # same number is the car's own model year.
        year=intent.min_year_gregorian,
        mileage_km=intent.max_mileage_km,
        transmission=intent.transmission,
        fuel=intent.fuel,
        body_status=body_status,
        body_type=intent.body_types[0] if intent.body_types else None,
        description=text,
    )


# ------------------------------------------------------------- corpus lookups


def cohort_counts(corpus: list[dict]) -> tuple[dict, dict, dict]:
    """Priced comparables per (brand, model, year), per (brand, model), per brand.

    `pricing._cohort_counts` computes the first two over a pandas frame, because
    `estimate()` already holds one. The server holds row dicts and should not
    build a 22,820-row frame to count them, so this is the dict form — one pass,
    at start-up, over the corpus that is already in memory.

    The brand tally is the one addition, and it counts rows the other two skip:
    2,169 priced listings carry a brand and no model slug, so a buyer who says
    only «پراید» has thousands of real comparables that a model-keyed count
    cannot see.

    Only priced listings count anywhere. A cohort of ten negotiable ads supports
    nothing, which is the whole reason this product exists.
    """
    by_model_year: dict[tuple, int] = {}
    by_model: dict[tuple, int] = {}
    by_brand: dict[str, int] = {}
    for row in corpus:
        if not row.get("price_toman"):
            continue
        brand, model, year = row.get("brand"), row.get("model"), row.get("year")
        if not brand:
            continue
        by_brand[brand] = by_brand.get(brand, 0) + 1
        if not model:
            continue
        by_model[(brand, model)] = by_model.get((brand, model), 0) + 1
        if year:
            key = (brand, model, year)
            by_model_year[key] = by_model_year.get(key, 0) + 1
    return by_model_year, by_model, by_brand


# Categorical model inputs a person will not always state. Missing is not a
# neutral value for any of them: `pricing.build_frame` turns an absent
# categorical into the literal string "unknown", and the encoder has almost never
# seen that string, because the crawl fills these fields on nearly every row.
#
# Measured on the 20,199 priced training rows, `transmission` is absent on 1.1%
# — and those 217 listings have a median price of 2.0B against 1.44B for the
# rest. So "unknown" does not read to the model as *no information*; it reads as
# *the kind of car whose ad omits its gearbox*, which is a rarer and pricier
# population. Left alone, a 2011 Pride 131 with the gearbox box empty was priced
# at 1.92B against a corpus median of 485M — a four-fold error produced entirely
# by a blank field, and one that no confidence score would have caught, because
# confidence is built from cohort depth and numeric evidence and knew nothing
# about it.
#
# Numeric features are deliberately not in this list: HistGradientBoosting
# handles NaN natively and a missing number really does mean "no information"
# to it, which is the whole reason `confidence_for` discounts on evidence
# instead.
IMPUTED_FEATURES = ("transmission", "fuel", "body_type", "city")


def corpus_modes(corpus: list[dict]) -> dict[str, str]:
    """The commonest value of each imputable field across the whole corpus.

    The last resort, for a car whose brand we hold nothing else of.
    """
    modes: dict[str, str] = {}
    for field in IMPUTED_FEATURES:
        counts: dict[str, int] = {}
        for row in corpus:
            value = row.get(field)
            if value:
                counts[value] = counts.get(value, 0) + 1
        if counts:
            modes[field] = max(counts, key=lambda key: (counts[key], key))
    return modes


def _mode(rows: list[dict], field: str) -> str | None:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(field)
        if value:
            counts[value] = counts.get(value, 0) + 1
    return max(counts, key=lambda key: (counts[key], key)) if counts else None


def impute(
    car: CarInput,
    by_model: dict[tuple, list[dict]],
    modes: dict[str, str],
) -> tuple[CarInput, dict[str, str]]:
    """Fill unstated categoricals from cars of the same kind.

    "If you did not say, assume your car is like the others of its model" is
    what a human appraiser does, and unlike a blank it is a claim the corpus can
    back: the 2011 Pride 131 above imputes «دنده ای» because 578 of its
    cohort-mates are manual.

    Narrowest cohort first — this model, then this brand, then the corpus — and
    every assumption is returned rather than applied silently, because a number
    that moved four-fold on an assumption is exactly the kind of thing this
    product refuses to hide.
    """
    filled = CarInput(**car.to_dict())
    assumed: dict[str, str] = {}

    cohort = by_model.get((car.brand, car.model or ""), [])
    brand_rows = (
        [row for (brand, _m), rows in by_model.items() if brand == car.brand for row in rows]
        if car.brand
        else []
    )

    for field in IMPUTED_FEATURES:
        if getattr(filled, field):
            continue
        value = _mode(cohort, field) or _mode(brand_rows, field) or modes.get(field)
        if value:
            setattr(filled, field, value)
            assumed[field] = value
    return filled, assumed


def index_by_model(corpus: list[dict]) -> dict[tuple, list[dict]]:
    """Corpus bucketed by (brand, model), for finding cars like theirs.

    Built once at start-up so an appraisal narrows to a few hundred candidates
    by dictionary lookup instead of walking the whole corpus — the same reason
    `main.py` keeps `_by_code`.
    """
    buckets: dict[tuple, list[dict]] = {}
    for row in corpus:
        brand, model = row.get("brand"), row.get("model")
        if brand and model:
            buckets.setdefault((brand, model), []).append(row)
    return buckets


def load_metrics() -> dict[str, float]:
    """The model's own held-out error, for quoting a range around an estimate."""
    try:
        data = json.loads(pricing.METRICS_PATH.read_text(encoding="utf-8"))
        return {
            "median_ape": float(data["median_ape"]),
            "mape": float(data["mape"]),
        }
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        log.info("no price model metrics on disk; using the published figures")
        return dict(FALLBACK_METRICS)


# --------------------------------------------------------------- the appraisal


def price_band(fair: int, confidence: float, metrics: dict[str, float]) -> tuple[int, int]:
    """A range around the estimate, anchored on what the model actually measures.

    Half the held-out listings land within `median_ape` of their true price, and
    the mean is dragged out to `mape` by the sources that publish least about
    themselves. So a well-evidenced estimate is quoted at the median error and a
    thin one at the mean, interpolating on confidence — which is itself built
    from comparable depth and spec evidence.

    The alternative was a fixed percentage, which would have told a car with 200
    comparables and one with two the same thing about how much to trust it.
    """
    lo_err, hi_err = metrics["median_ape"], metrics["mape"]
    spread = hi_err - (hi_err - lo_err) * max(0.0, min(1.0, confidence))
    million = 1_000_000
    return (
        int(round(fair * (1 - spread) / million) * million),
        int(round(fair * (1 + spread) / million) * million),
    )


def _evidence(row: dict) -> float:
    """Share of the spec fields that sharpen a price estimate, as this car has.

    The same four fields `pricing.estimate` measures, read the same way, so a
    self-described car is discounted on exactly the scale a sparse Divar listing
    is rather than on one invented here.
    """
    present = sum(1 for key in pricing.EVIDENCE_FEATURES if row.get(key) is not None)
    return present / len(pricing.EVIDENCE_FEATURES)


def _matching_listings(
    car: CarInput,
    by_model: dict[tuple, list[dict]],
) -> tuple[list[dict], str]:
    """Live ads for cars like theirs, and how closely 'like' had to be read.

    Walks the same ladder `pricing.confidence_for` prices: the exact model in a
    year window, then the model at any year, then the brand. Each rung is a
    weaker claim about similarity and is named in the return so the UI can say
    which one it is showing rather than implying they are all the same thing.
    """
    if not car.brand:
        return [], "none"

    same_model = by_model.get((car.brand, car.model or ""), [])
    if same_model and car.year:
        in_window = [
            row for row in same_model
            if row.get("year") and abs(row["year"] - car.year) <= YEAR_WINDOW
        ]
        if len(in_window) >= MIN_COHORT:
            return in_window, "model_year"
    if len(same_model) >= MIN_COHORT:
        return same_model, "model"

    same_brand = [
        row
        for (brand, _model), rows in by_model.items()
        if brand == car.brand
        for row in rows
    ]
    return same_brand, "brand" if same_brand else "none"


def appraise(
    car: CarInput,
    pipe: Any,
    *,
    by_model_year: dict,
    by_model_counts: dict,
    by_model: dict[tuple, list[dict]],
    metrics: dict[str, float],
    by_brand_counts: dict | None = None,
    modes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Value one car, or say honestly why we cannot.

    `status` is the first thing to read. Only `ok` carries a price; every other
    value carries `price: None` and a reason, because the failure modes are
    genuinely different and a buyer or seller deserves to be told which one they
    hit. This mirrors `search.retrieve`'s `mode`, for the same reason.
    """
    row = car.to_row()
    result: dict[str, Any] = {
        "status": "ok",
        "input": car.to_dict(),
        "assumed": {},
        "warnings": [],
        "price": None,
        "health": None,
        "flags": {"red_flags": row["red_flags"], "positives": row["positives"]},
        "matches": [],
        "match_level": "none",
    }

    # An unidentified car is the honest empty result. Ranking a name we do not
    # know against the whole corpus is how the old search returned a BMW for
    # «سراتو», and pricing one would be the same mistake with a number on it.
    #
    # A brand with no model is *not* that case, and refusing it was wrong: 2,169
    # of the priced corpus carry a brand and no model slug — «پراید» and «تیبا»
    # most of all — so the model is trained on exactly this shape and can price
    # it. The missing model simply costs cohort depth, which is what confidence
    # is for.
    if not car.brand:
        result["status"] = "unknown_car"
        return result

    # `pricing.build_frame` cannot score a row with no age, and guessing a year
    # would invent the single strongest input to the estimate.
    if not car.year:
        result["status"] = "need_year"
        return result

    # Fill the categoricals the user left blank before scoring, never after: a
    # blank one is read by the encoder as a rare category rather than as silence.
    # See `IMPUTED_FEATURES`.
    car, assumed = impute(car, by_model, modes or {})
    row = car.to_row()
    result["input"] = car.to_dict()
    result["assumed"] = assumed

    frame = pricing.build_frame([row])
    fair = float(np.exp(pipe.predict(frame[pricing.FEATURES])[0]))
    fair = int(round(fair / 1_000_000) * 1_000_000)

    # Comparable depth, walking model-year -> model -> brand, one rung coarser
    # than a listing's trim -> model -> global because a form collects no trim.
    # Excludes nothing: unlike `pricing.estimate` this car is not itself in the
    # corpus, so there is no self to subtract.
    n_model_year = by_model_year.get((car.brand, car.model, car.year), 0)
    n_model = by_model_counts.get((car.brand, car.model), 0)
    n_brand = by_brand_counts.get(car.brand, 0) if by_brand_counts else 0
    if n_model_year >= MIN_COHORT:
        level, n_comparables = "model", n_model_year
    else:
        # `confidence_for` knows three rungs, and this is its bottom one — the
        # estimate is no longer backed by cars of this exact model and year, so
        # it must be discounted as such however many looser comparables exist.
        level, n_comparables = "global", max(n_model_year, n_model, n_brand)

    confidence = pricing.confidence_for(n_comparables, level, _evidence(row))
    low, high = price_band(fair, confidence, metrics)

    # Zero-kilometre cars are deliberately out of the corpus: Iran's new-car
    # market is dual-priced, so a factory allocation and a free-market car of the
    # same model have two different true prices and "market value" is not one
    # number. The estimate is still returned — refusing outright would be less
    # useful than a caveat — but it must not arrive unqualified.
    if car.mileage_km == 0 or (car.age is not None and car.age <= 0):
        result["warnings"].append("brand_new")
    if car.mileage_km is None:
        result["warnings"].append("no_mileage")
    if n_comparables == 0:
        result["warnings"].append("no_comparables")

    health = score_listing(row)
    band_fa, band_en = health_band(health.score)

    candidates, match_level = _matching_listings(car, by_model)
    if candidates:
        # Ordered by the same value x health x fit the result grid uses, and
        # explained into the same payload `CarCard` already renders. The intent
        # is empty on purpose: these rows were selected by being this car, so
        # filtering them again would only re-ask a question already answered.
        result["matches"] = order_all(candidates, Intent()).page(0, MATCH_LIMIT)
        result["match_level"] = match_level

    result["price"] = {
        "fair_price": fair,
        "low": low,
        "high": high,
        "confidence": confidence,
        "n_comparables": n_comparables,
        "cohort_level": level,
    }
    result["health"] = {
        "score": health.score,
        "band_fa": band_fa,
        "band_en": band_en,
        "factors": [f.to_dict() for f in health.factors],
    }
    return result

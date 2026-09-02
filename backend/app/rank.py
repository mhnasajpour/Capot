"""Ranking: turn an Intent plus the corpus into an explained result list.

Scoring blends three independent signals, which map one-to-one onto the three
questions the product exists to answer:

    value  — is the asking price fair, given what the model says it is worth?
    health — is the car sound?
    fit    — does it match what this buyer actually asked for?

The crucial behaviour is in the budget filter: a listing with no published price
is matched on its *estimated* price. That is what lets a buyer with an 800M
budget see the roughly one-in-five listings that refuse to show a number — the
whole point of the product.

Every result carries the reasons behind its rank. A ranking a user cannot
interrogate is just an opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .features import (
    SORT_KEYS,
    effective_price,
    is_deposit_price,
    passes_features,
)
from .health import health_band, health_score, score_listing
from .query import Intent

# Domestic marques: parts are cheap and available in every Iranian town, which
# is a real ownership-cost signal buyers reason about explicitly.
# Slugs must match what the corpus actually uses — 'quik' and 'paykan' were
# spelled that way here and nowhere in the data, so Saipa Quicks and Peykans
# were never credited with cheap parts.
DOMESTIC_BRANDS = {
    "pride", "peugeot", "samand", "tiba", "quick", "dena", "rana", "saina",
    "shahin", "tara", "arisun", "peykan", "ikco", "saipa",
}
# Marques with a strong reliability reputation in this market.
RELIABLE_BRANDS = {"toyota", "kia", "hyundai", "mazda", "nissan", "honda", "suzuki"}
ROOMY_BODY_TYPES = {"suv", "crossover", "van", "station"}

# How far below market counts as a genuinely good deal (percent).
GREAT_DEAL_PCT = -8.0
OVERPRICED_PCT = 12.0


@dataclass
class Weights:
    value: float = 0.34
    health: float = 0.34
    fit: float = 0.32

    @classmethod
    def for_intent(cls, intent: Intent) -> "Weights":
        """Shift emphasis toward whatever the buyer actually signalled."""
        weights = cls()
        if intent.budget_max or intent.use_case == "economy":
            weights = cls(value=0.44, health=0.30, fit=0.26)
        if intent.require_clean_body or intent.use_case == "first_car":
            weights = cls(value=0.30, health=0.44, fit=0.26)
        if intent.priorities and len(intent.priorities) >= 3:
            weights = cls(value=0.30, health=0.30, fit=0.40)
        return weights


# `effective_price`, `is_deposit_price` and the hard-constraint gate now live in
# `features.py`, which owns the definition of every filterable car feature. They
# are re-exported here because this is where callers have always found them, and
# because ranking and filtering must read a car's price the same way: a listing
# with no published price is judged on its *estimate*, which is what keeps the
# ~1,000 «توافقی» cars inside a buyer's price range instead of below it.
def passes_filters(row: dict, intent: Intent) -> bool:
    """Hard constraints. Anything the buyer stated explicitly is honoured.

    One gate for both doors into search — prose parsed into an `Intent`, and
    features ticked in the UI overlaid onto the same `Intent`.
    """
    return passes_features(row, intent)


def value_score(row: dict) -> tuple[float, list[dict]]:
    """Score how good the asking price is versus the model's fair price."""
    delta = row.get("price_delta_pct")
    confidence = row.get("confidence") or 0.0
    reasons: list[dict] = []

    if delta is None:
        if is_deposit_price(row):
            # Pre-sale / voucher: warn rather than flatter. Its advertised figure
            # is a down-payment, so this is not a comparable purchase.
            reasons.append({
                "fa": "آگهی حواله یا پیش‌فروش؛ مبلغ آگهی قیمت کامل خودرو نیست",
                "en": "Voucher or pre-sale listing; the advertised figure is not the full price",
                "kind": "warning",
            })
            return 35.0, reasons
        # No published price: the estimate is the story, not the discount.
        if row.get("fair_price"):
            reasons.append({
                "fa": "فروشنده قیمت نگذاشته؛ برآورد ما بر پایه آگهی‌های مشابه",
                "en": "Seller hid the price; estimated from comparable listings",
                "kind": "estimate",
            })
            return 50.0, reasons
        return 40.0, reasons

    # -20% under market -> ~95, at market -> 55, +20% over -> ~15.
    score = 55.0 - delta * 2.0
    score = max(0.0, min(100.0, score))
    # A confident estimate should move the ranking more than a shaky one.
    score = 50.0 + (score - 50.0) * (0.45 + 0.55 * confidence)

    if delta <= GREAT_DEAL_PCT:
        reasons.append({
            "fa": f"حدود {abs(delta):.0f}٪ زیر قیمت بازار",
            "en": f"About {abs(delta):.0f}% below market price",
            "kind": "deal",
        })
    elif delta >= OVERPRICED_PCT:
        reasons.append({
            "fa": f"حدود {delta:.0f}٪ بالاتر از قیمت بازار",
            "en": f"About {delta:.0f}% above market price",
            "kind": "warning",
        })
    else:
        reasons.append({
            "fa": "قیمت نزدیک به نرخ بازار",
            "en": "Priced close to market rate",
            "kind": "neutral",
        })
    return score, reasons


def fit_score(row: dict, intent: Intent, ctx: dict) -> tuple[float, list[dict]]:
    """Score how well the car matches the buyer's stated and implied needs."""
    if not intent.priorities and not intent.use_case:
        return 55.0, []

    points: list[float] = []
    reasons: list[dict] = []

    def add(score: float, fa: str | None = None, en: str | None = None) -> None:
        points.append(score)
        if fa and en and score >= 70:
            reasons.append({"fa": fa, "en": en, "kind": "fit"})

    brand = (row.get("brand") or "").lower()

    for priority in intent.priorities:
        if priority == "low_consumption":
            consumption = row.get("consumption_l100")
            if consumption:
                # 5 L/100km -> ~100, 12 -> ~10
                score = max(0.0, min(100.0, (12.0 - consumption) / 7.0 * 100))
                add(score, f"مصرف سوخت پایین ({consumption} لیتر در ۱۰۰ کیلومتر)",
                    f"Low fuel consumption ({consumption} L/100km)")
            else:
                add(50.0)

        elif priority == "space":
            roomy = (row.get("body_type") or "") in ROOMY_BODY_TYPES
            add(88.0 if roomy else 42.0,
                "بدنه جادار مناسب خانواده", "Roomy body, good for a family")

        elif priority == "performance":
            power = row.get("power_hp")
            if power:
                score = max(0.0, min(100.0, (power - 70) / 180 * 100))
                add(score, f"قدرت موتور {power:.0f} اسب بخار", f"{power:.0f} hp engine")
            else:
                add(45.0)

        elif priority == "cheap_parts":
            domestic = brand in DOMESTIC_BRANDS
            add(90.0 if domestic else 40.0,
                "قطعات ارزان و در دسترس (خودروی داخلی)",
                "Cheap, widely available parts (domestic brand)")

        elif priority == "reliability":
            score = 85.0 if brand in RELIABLE_BRANDS else 50.0
            age = row.get("age")
            if age is not None and age <= 6:
                score += 10
            add(min(score, 100.0), "برند با سابقه اطمینان‌پذیری", "Brand with a strong reliability record")

        elif priority == "low_depreciation":
            tags = row.get("life_styles") or []
            has_tag = any("استهلاک" in str(t) for t in tags)
            add(90.0 if has_tag else 50.0, "کم‌استهلاک", "Low depreciation")

        elif priority == "comfort":
            score = 50.0
            if (row.get("transmission") or "") == "اتوماتیک":
                score += 25
            if (row.get("body_type") or "") in ROOMY_BODY_TYPES:
                score += 15
            age = row.get("age")
            if age is not None and age <= 5:
                score += 10
            add(min(score, 100.0), "راحتی بالا (گیربکس اتوماتیک / بدنه بزرگ)",
                "Comfortable (automatic / larger body)")

        elif priority == "safety":
            age = row.get("age")
            score = 50.0 if age is None else max(0.0, min(100.0, (18 - age) / 18 * 100))
            add(score, "خودروی نسبتا جدید با ایمنی بهتر", "Newer vehicle with better safety")

        elif priority == "economy":
            price, _ = effective_price(row)
            if price and ctx.get("median_price"):
                ratio = price / ctx["median_price"]
                add(max(0.0, min(100.0, (1.6 - ratio) / 1.2 * 100)),
                    "قیمت اقتصادی نسبت به بازار", "Economical relative to the market")
            else:
                add(50.0)

    if not points:
        return 55.0, reasons
    return sum(points) / len(points), reasons


# How much retrieval relevance contributes to the final score. In entity mode
# every candidate scores 1.0, so this adds a constant and leaves the
# value/health/fit ordering untouched; for text and semantic queries it
# dominates, which is what stops a weakly-matching bargain from outranking the
# car the user actually asked for.
RELEVANCE_WEIGHT = 45.0


# Explicit orderings, for when the buyer is browsing by feature rather than
# asking a question. Each returns a sort key; `None` means "no value", and those
# rows are pushed to the end rather than sorting as zero — a car with no
# recorded mileage is not the lowest-mileage car in the list.
#
# Price orderings read `effective_price`, so a hidden-price car sorts by our
# estimate. Sorting it as "no price" would undo the whole point of estimating.
def _sort_key(key: str) -> Callable[[dict], tuple]:
    def missing_last(value: float | None, descending: bool) -> tuple:
        if value is None:
            return (1, 0.0)
        return (0, -value if descending else value)

    getters: dict[str, Callable[[dict], tuple]] = {
        "price_asc": lambda r: missing_last(effective_price(r)[0], False),
        "price_desc": lambda r: missing_last(effective_price(r)[0], True),
        "year_desc": lambda r: missing_last(r.get("year"), True),
        "mileage_asc": lambda r: missing_last(r.get("mileage_km"), False),
        "health_desc": lambda r: missing_last(health_score(r), True),
        # Most below market first: delta is negative for a bargain.
        "discount_desc": lambda r: missing_last(r.get("price_delta_pct"), False),
    }
    return getters[key]


@dataclass
class Ranking:
    """One ordered candidate set, kept apart from the payloads it can produce.

    Ordering has to see every candidate — a page is only a window onto one list
    if the whole list was ordered first — but *explaining* every candidate to
    hand back twenty-four of them is pure waste. Building the payloads for
    15,740 cars costs about half a second, and a scrolling result grid asks for
    the same ordering again with every fetch.

    So the two halves are separate: `order_all` puts the candidates in order
    using only the numbers (health comes from the row's cached score, not a
    rescoring), and `page` explains the handful the reader is about to see. The
    caller can hold onto a `Ranking` and serve later pages off it for free.
    """

    rows: list[dict]
    intent: Intent
    ctx: dict
    weights: Weights
    relevance: dict[str, float] | None = None

    def __len__(self) -> int:
        return len(self.rows)

    def page(self, offset: int = 0, limit: int | None = None) -> list[dict]:
        """Explain one window of the ordering. Out of range is simply empty."""
        window = self.rows[offset:] if limit is None else self.rows[offset:offset + limit]
        return [self._explain(row) for row in window]

    def _explain(self, row: dict) -> dict[str, Any]:
        """One result card: the scores that ranked it, and why."""
        health = score_listing(row)
        value, value_reasons = value_score(row)
        fit, fit_reasons = fit_score(row, self.intent, self.ctx)
        total = self._total(row, value, health.score, fit)
        price, estimated = effective_price(row)
        band_fa, band_en = health_band(health.score)
        rel = self._relevance_of(row)

        # Lead with price reasoning, then fit, then the strongest health factors.
        reasons = list(value_reasons) + list(fit_reasons)
        for factor in health.factors[:2]:
            if factor.impact:
                reasons.append({
                    "fa": factor.label_fa,
                    "en": factor.label_en,
                    "kind": "health_positive" if factor.impact > 0 else "health_risk",
                })

        return {
            **{k: row.get(k) for k in (
                "code", "url", "title", "brand", "brand_fa", "model", "trim",
                "year", "year_display", "year_calendar", "age", "mileage_km",
                "body_status", "body_grade", "body_type", "body_type_fa", "transmission", "fuel",
                "body_color", "seller", "dealer_name", "dealer_score", "city",
                "location", "image", "image_count", "authenticated", "life_styles",
                "consumption_l100", "power_hp", "engine_volume_l",
                # Multi-source: which site the ad came from, its cross-listings,
                # and Divar's insurance field.
                "source", "duplicate_of", "insurance_months",
            )},
            "price": {
                "asking": row.get("price_toman"),
                "effective": price,
                "is_estimated": estimated,
                "is_negotiable": bool(row.get("is_negotiable")),
                "fair_price": row.get("fair_price"),
                "delta_pct": row.get("price_delta_pct"),
                "confidence": row.get("confidence"),
                "n_comparables": row.get("n_comparables"),
                "cohort_level": row.get("cohort_level"),
                "price_flag": row.get("price_flag"),
            },
            "health": {
                "score": health.score,
                "band_fa": band_fa,
                "band_en": band_en,
                "factors": [f.to_dict() for f in health.factors],
            },
            "scores": {
                "total": total,
                "value": round(value, 1),
                "health": health.score,
                "fit": round(fit, 1),
                "relevance": round(rel, 3),
            },
            "reasons": reasons[:5],
        }

    def _relevance_of(self, row: dict) -> float:
        if self.relevance is None:
            return 1.0
        return float(self.relevance.get(row["code"], 0.0))

    def _total(self, row: dict, value: float, health: int, fit: float) -> float:
        return _total_score(value, health, fit, self._relevance_of(row), self.weights)


def _total_score(value: float, health: int, fit: float, rel: float, weights: Weights) -> float:
    """The single number the default ordering sorts on.

    Rounded here rather than at display time because the sort reads it: two cars
    a thousandth of a point apart must not swap places between the pass that
    ordered them and the pass that explained them.
    """
    base = weights.value * value + weights.health * health + weights.fit * fit
    return round(0.55 * base + RELEVANCE_WEIGHT * rel, 2)


def order_all(
    rows: list[dict],
    intent: Intent,
    relevance: dict[str, float] | None = None,
    sort: str = "rank",
) -> Ranking:
    """Filter and order *every* candidate, without explaining any of them.

    `rows` is expected to be the retrieved candidate set (see search.py), not the
    whole corpus — relevance is decided before ranking, never by it.

    `sort` defaults to the value x health x fit ordering this module exists for.
    The explicit orderings are for browsing by feature, where "best overall" is
    not what the buyer asked for.

    Nothing is truncated here. Paging is `Ranking.page`'s job, and it has to come
    after the full ordering: a page is a window onto one list, so page 2 is only
    the real second-best twenty-four if page 1 was chosen from the same list.
    """
    candidates = [r for r in rows if passes_filters(r, intent)]
    weights = Weights.for_intent(intent)
    if not candidates:
        return Ranking([], intent, {"median_price": None}, weights, relevance)

    prices = [p for p, _ in (effective_price(r) for r in candidates) if p]
    ctx = {"median_price": sorted(prices)[len(prices) // 2] if prices else None}

    def relevance_of(row: dict) -> float:
        return 1.0 if relevance is None else float(relevance.get(row["code"], 0.0))

    # Always order by the composite first, so an explicit sort is a stable
    # reordering of the recommendation rather than of an arbitrary list.
    scored = [
        (
            _total_score(
                value_score(row)[0],
                # The cached number, not a rescoring: this loop runs once per
                # candidate and `score_listing` walks a dozen factors to produce
                # a score the row already carries.
                health_score(row),
                fit_score(row, intent, ctx)[0],
                relevance_of(row),
                weights,
            ),
            row,
        )
        for row in candidates
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    ordered = [row for _, row in scored]
    if sort != "rank" and sort in SORT_KEYS:
        ordered.sort(key=_sort_key(sort))
    return Ranking(ordered, intent, ctx, weights, relevance)


def rank_all(
    rows: list[dict],
    intent: Intent,
    relevance: dict[str, float] | None = None,
    sort: str = "rank",
) -> list[dict]:
    """Filter, score and explain *every* candidate. Returns ranked result dicts.

    The whole ordering, explained. Callers that only need a page of it should
    hold an `order_all` result and take pages off that instead.
    """
    return order_all(rows, intent, relevance=relevance, sort=sort).page()


def rank(
    rows: list[dict],
    intent: Intent,
    limit: int = 24,
    relevance: dict[str, float] | None = None,
    sort: str = "rank",
    offset: int = 0,
) -> list[dict]:
    """One page of the ranking — `limit` results starting at `offset`.

    Ordering the whole candidate set to hand back twenty-four rows looks
    wasteful, but the corpus is a few thousand listings held in memory and the
    ordering is global: there is no way to know which listings belong on page 3
    without scoring the ones on pages 1 and 2. Only the page itself is explained.

    Callers serving several pages of the *same* search — a scrolling result grid
    asks for one page per fetch — should keep the `order_all` result and page off
    it, rather than reordering the corpus once per page.
    """
    return order_all(rows, intent, relevance=relevance, sort=sort).page(offset, limit)

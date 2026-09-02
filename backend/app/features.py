"""The filterable feature catalogue: what a car *is*, as a set of selectable
features.

Search has only ever had one door: type Persian prose, get a ranked list. That
answers "what should I buy" but not "show me the automatic Hyundais under two
billion" — and a buyer who does not know what to type gets nothing at all.

This module is the second door. It declares every car feature worth filtering
on, derives the available values from the corpus itself (never a hand-written
list, exactly as `lexicon.py` does for brand vocabulary), and owns the predicate
that decides whether one listing matches one selection.

Three things live here together on purpose:

  * `FEATURES` — the declarative spec. One entry per feature, carrying its
    labels, how to read it off a row, and how to test it against an `Intent`.
  * `build_catalogue` — what the UI needs to draw the filter panel.
  * `count_features` — leave-one-out counts, so ticking «هیوندای» does not show
    every other brand as zero and make multi-select impossible.

`effective_price` lives here rather than in `rank.py` because reading a car's
price *is* reading one of its features, and both the filter and the ranker must
read it the same way. That matters more here than anywhere: a listing with no
published price is matched on its **estimate**, which is what keeps all 1,000
«توافقی» cars inside a price filter instead of dumping them at the bottom.

What is deliberately *not* here: `power_hp` (2.8% populated),
`insurance_months` (8.4%) and `dealer_score` (14.5%). A filter over a field that
thin removes 85-97% of the corpus the moment it is touched, and the buyer reads
that as "you have no cars" rather than "we have no data".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable

import numpy as np

from .health import score_listing
from .query import Intent

# --------------------------------------------------------------------- price


def is_deposit_price(row: dict) -> bool:
    """The advertised figure is a deposit/voucher, not the car's price."""
    return row.get("price_flag") == "deposit"


# No used car in this market sells for less than this. `pricing.py` already
# excludes such rows from *training* (`MIN_VALID_PRICE`), and flags down-payment
# listings as `deposit` — but only when their cohort has three or more members
# to compare against. A ₺1,000 Porsche Cayenne sits in a cohort of one, so it
# escapes that check and keeps its published price.
#
# That was invisible while results were only ever ordered by value x health x
# fit, which buries a nonsense price. Sorting by price puts it first: "cheapest
# car" would have been a 1,000-toman Cayenne. The number is deliberately far
# below any real listing (the 1st percentile of published prices is 320M), so it
# catches typos and placeholders without touching a genuinely cheap old Pride.
MIN_CREDIBLE_PRICE = 20_000_000

# A published price this far below the car's own estimate is a down-payment the
# cohort check missed. `pricing.implausible_vs_cohort` needs three comparables
# before it will judge a price, so a thin cohort lets one through: a Tara listed
# at 28.5M against a 3.4B estimate — 0.8% of its own valuation.
#
# Deliberately far more permissive than that check's own 0.35 floor, because an
# estimate is weaker evidence than a real cohort median. A crashed Pride at 50%
# of its estimate is a real, correctly-priced car and must stay.
MIN_PRICE_TO_ESTIMATE_RATIO = 0.15


def is_credible_price(row: dict) -> bool:
    """Is the advertised figure plausibly this car's actual price?"""
    price = row.get("price_toman")
    if not price or price < MIN_CREDIBLE_PRICE or is_deposit_price(row):
        return False
    fair = row.get("fair_price")
    return not (fair and price < fair * MIN_PRICE_TO_ESTIMATE_RATIO)


def effective_price(row: dict) -> tuple[int | None, bool]:
    """Return (price, is_estimated).

    A published price wins — unless it is a deposit, a voucher or an
    implausible figure, in which case it is not this car's price at all and we
    fall back to the estimate, exactly as we do for a listing that published
    nothing.
    """
    if is_credible_price(row):
        return int(row["price_toman"]), False
    if row.get("fair_price"):
        return int(row["fair_price"]), True
    return None, False


def ensure_health_scores(corpus: Iterable[dict]) -> None:
    """Cache each listing's health score on the row.

    The health filter needs the score *before* ranking computes it, and
    `score_listing` walks a dozen factors. Rows are loaded once and never
    mutated afterwards, so computing this at load time costs one pass and makes
    the filter a dictionary lookup.
    """
    for row in corpus:
        if row.get("health_score") is None:
            row["health_score"] = score_listing(row).score


# ------------------------------------------------------------- value labelling

# English labels for the closed Persian value sets. Open sets — colour (51
# values) and city (264) — get no translation: inventing English names for
# «نقرآبی» or «اسلام شهر» would be worse than showing the Persian.
VALUE_LABELS_EN: dict[str, dict[str, str]] = {
    "body_type": {
        "passenger_car": "Sedan", "crossover": "Crossover", "hatchback": "Hatchback",
        "pickup": "Pickup", "suv": "SUV", "coupe": "Coupe",
        "convertible": "Convertible", "van": "Van",
    },
    "transmission": {"اتوماتیک": "Automatic", "دنده ای": "Manual"},
    "fuel": {
        "بنزینی": "Petrol", "دوگانه سوز": "Petrol / LPG", "هیبریدی": "Hybrid",
        "برقی": "Electric", "بردافزا": "Range extender", "دیزلی": "Diesel",
        "هیبرید ملایم": "Mild hybrid", "پلاگین هیبرید": "Plug-in hybrid",
    },
    "seller": {"شخصی": "Private", "نمایشگاه": "Dealership", "نمایندگی": "Official agency"},
    "source": {
        "bama": "Bama", "divar": "Divar",
        "sheypoor": "Sheypoor", "karnameh": "Karnameh",
    },
}

# Persian labels, needed for exactly one feature. Everywhere else the corpus
# already stores the Persian — «اتوماتیک», «شخصی» — and only English needs a
# table. `source` is the exception: its values are latin slugs, so without this
# the filter panel offers 'bama' and 'sheypoor' to a reader of a right-to-left
# Persian interface. The frontend carries the same four names in `sources.ts`
# for the card badge.
VALUE_LABELS_FA: dict[str, dict[str, str]] = {
    "source": {
        "bama": "باما", "divar": "دیوار",
        "sheypoor": "شیپور", "karnameh": "کارنامه",
    },
}


def brand_label_en(slug: str) -> str:
    """English brand name, recovered from the slug the corpus already carries.

    Bama publishes `brand='bmw'` alongside `brand_fa='ب ام و'`, so the English
    name needs no table — only casing. Slugs of three letters or fewer are
    acronyms in this market (BMW, MVM, JAC, KMC, MG); longer ones are ordinary
    names (Hyundai, Renault, Samand).

    The rule also catches Kia, which renders as KIA. That is a common styling of
    the marque and not worth a hand-maintained exception list — the whole point
    of deriving this is that 87 brands stay correct with nobody maintaining them.
    """
    return slug.upper() if len(slug) <= 3 else slug.replace("_", " ").title()

# Paint condition, banded rather than exposed as a raw 0-100 slider. The
# thresholds are the ones `normalize.BODY_STATUS_GRADE` already assigns, and the
# wording is how Iranian buyers actually describe the distinction.
PAINT_BANDS: list[tuple[str, int, str, str]] = [
    ("clean", 100, "بدون رنگ", "No repaint at all"),
    ("near_clean", 80, "بدون رنگ یا خط و خش جزئی", "Unpainted or light scuffs"),
    ("one_spot", 70, "حداکثر یک لکه رنگ", "At most one painted panel"),
    ("few_spots", 45, "حداکثر چند لکه رنگ", "At most a few painted panels"),
]


# ------------------------------------------------------------------- the spec


@dataclass(frozen=True)
class Feature:
    """One filterable car feature.

    `value_of` reads the feature off a listing; `matches` tests that listing
    against whatever the buyer selected. Keeping both on the same object is what
    lets `count_features` do leave-one-out counting generically.
    """

    key: str
    kind: str            # "enum" | "range" | "band" | "bool"
    group: str           # UI section
    label_fa: str
    label_en: str
    matches: Callable[[dict, Intent], bool]
    value_of: Callable[[dict], Any] | None = None
    label_of: Callable[[dict], str | None] = lambda row: None
    parent: str | None = None                      # enum values scoped by another feature
    parent_of: Callable[[dict], str | None] | None = None
    # Derives the English label from the value itself, for sets that carry a
    # latin form in the data but are too large to translate by hand.
    english_of: Callable[[str], str] | None = None
    unit: str | None = None
    step: float | None = None
    decimals: int = 0
    # Range features whose bounds are only meaningful as a ceiling or a floor.
    bound: str = "both"  # "both" | "max" | "min"
    extra: dict[str, Any] = field(default_factory=dict)


def _lower(value: Any) -> str | None:
    return str(value).lower() if value else None


def _model_key(row: dict) -> str | None:
    """Models are namespaced by brand — «۲۰۶» is a Peugeot, «۳۱۵» a MVM."""
    brand, model = _lower(row.get("brand")), _lower(row.get("model"))
    return f"{brand}/{model}" if brand and model else None


# Each `matches` reads only the Intent fields its own feature owns, so
# `count_features` can drop exactly one feature's constraint and keep the rest.

def _m_brand(row: dict, intent: Intent) -> bool:
    return not intent.brands or (_lower(row.get("brand")) or "") in intent.brands


def _m_model(row: dict, intent: Intent) -> bool:
    return not intent.models or (_model_key(row) or "") in intent.models


def _m_body_type(row: dict, intent: Intent) -> bool:
    return not intent.body_types or (row.get("body_type") or "") in intent.body_types


def _m_transmission(row: dict, intent: Intent) -> bool:
    if intent.transmissions and (row.get("transmission") or "") not in intent.transmissions:
        return False
    # The singular field is what the Persian parser fills in; it stays a
    # substring test because prose says «اتومات», not «اتوماتیک».
    if intent.transmission and intent.transmission not in (row.get("transmission") or ""):
        return False
    return True


def _m_fuel(row: dict, intent: Intent) -> bool:
    if intent.fuels and (row.get("fuel") or "") not in intent.fuels:
        return False
    if intent.fuel and intent.fuel not in (row.get("fuel") or ""):
        return False
    return True


def _m_color(row: dict, intent: Intent) -> bool:
    return not intent.colors or (row.get("body_color") or "") in intent.colors


def _m_city(row: dict, intent: Intent) -> bool:
    if intent.cities and (row.get("city") or "") not in intent.cities:
        return False
    if intent.city and intent.city not in (row.get("city") or ""):
        return False
    return True


def _m_seller(row: dict, intent: Intent) -> bool:
    return not intent.sellers or (row.get("seller") or "") in intent.sellers


def _m_source(row: dict, intent: Intent) -> bool:
    return not intent.sources or (row.get("source") or "") in intent.sources


def _m_price(row: dict, intent: Intent) -> bool:
    """The one that carries the product's whole argument.

    Matching on `effective_price` means a car whose seller wrote «توافقی» is
    tested against our estimate, so it stays inside the buyer's price range
    instead of vanishing from every filtered search.
    """
    if not intent.budget_min and not intent.budget_max:
        return True
    price, _ = effective_price(row)
    if intent.budget_max:
        if price is None or price > intent.budget_max * 1.02:  # 2% grace
            return False
    if intent.budget_min and price is not None and price < intent.budget_min * 0.98:
        return False
    return True


def _m_year(row: dict, intent: Intent) -> bool:
    year = row.get("year")
    if intent.min_year_gregorian and (year or 0) < intent.min_year_gregorian:
        return False
    if intent.max_year is not None and (year is None or year > intent.max_year):
        return False
    if intent.max_age_years is not None and (row.get("age") is None or row["age"] > intent.max_age_years):
        return False
    return True


def _m_mileage(row: dict, intent: Intent) -> bool:
    mileage = row.get("mileage_km")
    if intent.max_mileage_km is not None:
        if mileage is None or mileage > intent.max_mileage_km:
            return False
    if intent.min_mileage_km is not None:
        if mileage is None or mileage < intent.min_mileage_km:
            return False
    return True


def _m_engine(row: dict, intent: Intent) -> bool:
    if intent.engine_min_l is None and intent.engine_max_l is None:
        return True
    volume = row.get("engine_volume_l")
    if volume is None:
        return False
    if intent.engine_min_l is not None and volume < intent.engine_min_l:
        return False
    if intent.engine_max_l is not None and volume > intent.engine_max_l:
        return False
    return True


def _m_consumption(row: dict, intent: Intent) -> bool:
    if intent.max_consumption_l100 is None:
        return True
    value = row.get("consumption_l100")
    return value is not None and value <= intent.max_consumption_l100


def _m_paint(row: dict, intent: Intent) -> bool:
    grade = row.get("body_grade") or 0
    if intent.min_body_grade is not None and grade < intent.min_body_grade:
        return False
    # The Persian parser's «بدون رنگ» still works when no band was ticked.
    if intent.require_clean_body and grade < 85:
        return False
    return True


def _m_health(row: dict, intent: Intent) -> bool:
    if intent.min_health is None:
        return True
    score = row.get("health_score")
    if score is None:
        score = score_listing(row).score
    return score >= intent.min_health


def _is_below_market(row: dict) -> bool:
    delta = row.get("price_delta_pct")
    return delta is not None and delta < 0 and not is_deposit_price(row)


def _m_below_market(row: dict, intent: Intent) -> bool:
    return not intent.only_below_market or _is_below_market(row)


def _m_inspected(row: dict, intent: Intent) -> bool:
    return not intent.only_inspected or bool(row.get("authenticated"))


def _m_has_image(row: dict, intent: Intent) -> bool:
    return not intent.only_with_image or bool(row.get("image_count"))


FEATURES: list[Feature] = [
    # ---- what the car is
    Feature(
        key="brand", kind="enum", group="identity", label_fa="برند", label_en="Brand",
        matches=_m_brand, value_of=lambda r: _lower(r.get("brand")),
        label_of=lambda r: r.get("brand_fa"), english_of=brand_label_en,
    ),
    Feature(
        key="model", kind="enum", group="identity", label_fa="مدل", label_en="Model",
        matches=_m_model, value_of=_model_key,
        label_of=lambda r: r.get("model_fa"),
        parent="brand", parent_of=lambda r: _lower(r.get("brand")),
    ),
    Feature(
        key="body_type", kind="enum", group="identity", label_fa="نوع بدنه", label_en="Body type",
        matches=_m_body_type, value_of=lambda r: r.get("body_type") or None,
        label_of=lambda r: r.get("body_type_fa"),
    ),
    # ---- how it drives
    Feature(
        key="transmission", kind="enum", group="mechanical", label_fa="گیربکس", label_en="Gearbox",
        matches=_m_transmission, value_of=lambda r: r.get("transmission") or None,
        label_of=lambda r: r.get("transmission"),
    ),
    Feature(
        key="fuel", kind="enum", group="mechanical", label_fa="سوخت", label_en="Fuel",
        matches=_m_fuel, value_of=lambda r: r.get("fuel") or None,
        label_of=lambda r: r.get("fuel"),
    ),
    Feature(
        key="engine", kind="range", group="mechanical", label_fa="حجم موتور",
        label_en="Engine size", matches=_m_engine,
        value_of=lambda r: r.get("engine_volume_l"), unit="L", step=0.1, decimals=1,
    ),
    Feature(
        key="consumption", kind="range", group="mechanical", label_fa="مصرف سوخت",
        label_en="Fuel consumption", matches=_m_consumption,
        value_of=lambda r: r.get("consumption_l100"),
        unit="L/100km", step=0.5, decimals=1, bound="max",
    ),
    # ---- price
    Feature(
        key="price", kind="range", group="price", label_fa="قیمت", label_en="Price",
        matches=_m_price, value_of=lambda r: effective_price(r)[0],
        unit="toman", step=50_000_000,
    ),
    Feature(
        key="below_market", kind="bool", group="price", label_fa="زیر قیمت بازار",
        label_en="Below market price", matches=_m_below_market, value_of=_is_below_market,
    ),
    # ---- condition
    Feature(
        key="year", kind="range", group="condition", label_fa="سال تولید", label_en="Year",
        matches=_m_year, value_of=lambda r: r.get("year"), step=1,
    ),
    Feature(
        key="mileage", kind="range", group="condition", label_fa="کارکرد", label_en="Mileage",
        matches=_m_mileage, value_of=lambda r: r.get("mileage_km"),
        unit="km", step=10_000, bound="max",
    ),
    Feature(
        key="paint", kind="band", group="condition", label_fa="وضعیت رنگ و بدنه",
        label_en="Paint condition", matches=_m_paint,
        value_of=lambda r: r.get("body_grade"),
    ),
    Feature(
        key="health", kind="range", group="condition", label_fa="حداقل امتیاز سلامت",
        label_en="Minimum health score", matches=_m_health,
        value_of=lambda r: r.get("health_score"), step=5, bound="min",
    ),
    Feature(
        key="inspected", kind="bool", group="condition", label_fa="کارشناسی‌شده",
        label_en="Inspected", matches=_m_inspected,
        value_of=lambda r: bool(r.get("authenticated")),
    ),
    # ---- who and where
    Feature(
        key="color", kind="enum", group="listing", label_fa="رنگ بدنه", label_en="Colour",
        matches=_m_color, value_of=lambda r: r.get("body_color") or None,
        label_of=lambda r: r.get("body_color"),
    ),
    Feature(
        key="city", kind="enum", group="listing", label_fa="شهر", label_en="City",
        matches=_m_city, value_of=lambda r: r.get("city") or None,
        label_of=lambda r: r.get("city"),
    ),
    Feature(
        key="seller", kind="enum", group="listing", label_fa="نوع فروشنده", label_en="Seller",
        matches=_m_seller, value_of=lambda r: r.get("seller") or None,
        label_of=lambda r: r.get("seller"),
    ),
    Feature(
        key="source", kind="enum", group="listing", label_fa="منبع آگهی", label_en="Source",
        matches=_m_source, value_of=lambda r: r.get("source") or None,
        label_of=lambda r: r.get("source"),
    ),
    Feature(
        key="has_image", kind="bool", group="listing", label_fa="فقط آگهی‌های عکس‌دار",
        label_en="With photos only", matches=_m_has_image,
        value_of=lambda r: bool(r.get("image_count")),
    ),
]

FEATURES_BY_KEY: dict[str, Feature] = {f.key: f for f in FEATURES}

GROUPS: list[dict[str, str]] = [
    {"key": "identity", "label_fa": "خودرو", "label_en": "Vehicle"},
    {"key": "price", "label_fa": "قیمت", "label_en": "Price"},
    {"key": "condition", "label_fa": "وضعیت", "label_en": "Condition"},
    {"key": "mechanical", "label_fa": "فنی", "label_en": "Mechanical"},
    {"key": "listing", "label_fa": "آگهی", "label_en": "Listing"},
]


def passes_features(row: dict, intent: Intent) -> bool:
    """Every hard constraint, in one place.

    Both doors into search end here: prose parsed into an `Intent` and features
    ticked in the UI overlaid onto the same `Intent`. One gate means the two can
    never disagree about what a filter means.
    """
    return all(f.matches(row, intent) for f in FEATURES)


# ------------------------------------------------------- explicit selections


SORT_KEYS = (
    "rank", "price_asc", "price_desc", "year_desc", "mileage_asc",
    "health_desc", "discount_desc",
)

_PAINT_GRADE = {key: grade for key, grade, _fa, _en in PAINT_BANDS}


def _csv(raw: str | None) -> list[str]:
    """Comma-separated list param, matching `/api/compare?codes=a,b`."""
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


@dataclass
class Filters:
    """What the buyer ticked, as opposed to what they typed.

    Kept separate from `Intent` only long enough to establish precedence:
    `apply_to` overlays these onto the parsed intent and an explicit selection
    always wins. If the prose said «اتوماتیک» and the buyer then unticks
    automatic, the buyer wins — they can see the checkbox, they cannot see the
    parser.
    """

    brands: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    body_types: list[str] = field(default_factory=list)
    transmissions: list[str] = field(default_factory=list)
    fuels: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    sellers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    mileage_min: int | None = None
    mileage_max: int | None = None
    engine_min: float | None = None
    engine_max: float | None = None
    consumption_max: float | None = None
    min_health: int | None = None
    paint: str | None = None
    below_market: bool = False
    inspected: bool = False
    has_image: bool = False
    sort: str = "rank"

    @classmethod
    def from_params(cls, **params: Any) -> "Filters":
        """Build from raw query-string values, ignoring anything malformed.

        A bad number in a URL should narrow nothing, not 500 the search.
        """
        def as_int(value: Any) -> int | None:
            try:
                return int(float(value)) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None

        def as_float(value: Any) -> float | None:
            try:
                return float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None

        sort = str(params.get("sort") or "rank")
        paint = params.get("paint") or None
        return cls(
            brands=[b.lower() for b in _csv(params.get("brands"))],
            models=[m.lower() for m in _csv(params.get("models"))],
            body_types=_csv(params.get("body_types")),
            transmissions=_csv(params.get("transmissions")),
            fuels=_csv(params.get("fuels")),
            colors=_csv(params.get("colors")),
            cities=_csv(params.get("cities")),
            sellers=_csv(params.get("sellers")),
            sources=[s.lower() for s in _csv(params.get("sources"))],
            price_min=as_int(params.get("price_min")),
            price_max=as_int(params.get("price_max")),
            year_min=as_int(params.get("year_min")),
            year_max=as_int(params.get("year_max")),
            mileage_min=as_int(params.get("mileage_min")),
            mileage_max=as_int(params.get("mileage_max")),
            engine_min=as_float(params.get("engine_min")),
            engine_max=as_float(params.get("engine_max")),
            consumption_max=as_float(params.get("consumption_max")),
            min_health=as_int(params.get("min_health")),
            paint=paint if paint in _PAINT_GRADE else None,
            below_market=bool(params.get("below_market")),
            inspected=bool(params.get("inspected")),
            has_image=bool(params.get("has_image")),
            sort=sort if sort in SORT_KEYS else "rank",
        )

    @property
    def is_empty(self) -> bool:
        """True when nothing was selected. Sort order is not a constraint."""
        return not any([
            self.brands, self.models, self.body_types, self.transmissions,
            self.fuels, self.colors, self.cities, self.sellers, self.sources,
            self.price_min, self.price_max, self.year_min, self.year_max,
            self.mileage_min, self.mileage_max, self.engine_min, self.engine_max,
            self.consumption_max, self.min_health, self.paint,
            self.below_market, self.inspected, self.has_image,
        ])

    def apply_to(self, intent: Intent) -> Intent:
        """Overlay these selections onto a parsed intent. Explicit wins."""
        out = replace(intent)

        if self.brands:
            out.brands = list(self.brands)
        if self.models:
            out.models = list(self.models)
        if self.body_types:
            out.body_types = list(self.body_types)
        # Setting the plural clears the singular: the parser's substring guess
        # must not survive alongside an exact choice the buyer made.
        if self.transmissions:
            out.transmissions, out.transmission = list(self.transmissions), None
        if self.fuels:
            out.fuels, out.fuel = list(self.fuels), None
        if self.cities:
            out.cities, out.city = list(self.cities), None
        if self.colors:
            out.colors = list(self.colors)
        if self.sellers:
            out.sellers = list(self.sellers)
        if self.sources:
            out.sources = list(self.sources)

        if self.price_min is not None:
            out.budget_min = self.price_min
        if self.price_max is not None:
            out.budget_max = self.price_max
        if self.year_min is not None:
            # A chosen year floor replaces both the parsed floor and the parsed
            # age ceiling, which are two spellings of the same constraint.
            out.min_year_gregorian, out.max_age_years = self.year_min, None
        if self.year_max is not None:
            out.max_year = self.year_max
        if self.mileage_min is not None:
            out.min_mileage_km = self.mileage_min
        if self.mileage_max is not None:
            out.max_mileage_km = self.mileage_max
        if self.engine_min is not None:
            out.engine_min_l = self.engine_min
        if self.engine_max is not None:
            out.engine_max_l = self.engine_max
        if self.consumption_max is not None:
            out.max_consumption_l100 = self.consumption_max
        if self.min_health is not None:
            out.min_health = self.min_health
        if self.paint:
            # The band supersedes the parser's «بدون رنگ», which is just a
            # coarser spelling of the same thing.
            out.min_body_grade, out.require_clean_body = _PAINT_GRADE[self.paint], False

        out.only_below_market = out.only_below_market or self.below_market
        out.only_inspected = out.only_inspected or self.inspected
        out.only_with_image = out.only_with_image or self.has_image
        return out

    def to_dict(self) -> dict[str, Any]:
        """Only what was actually set — the UI echoes this back as chips."""
        data = {k: v for k, v in self.__dict__.items() if v not in (None, [], False)}
        data["sort"] = self.sort
        return data


# ---------------------------------------------------------------- the catalogue


def _clamped_bounds(values: list[float], lo: float = 0.01, hi: float = 0.99) -> tuple[float, float]:
    """Percentile bounds, because the raw extremes are junk.

    `price_toman` reaches 535 billion against a p99 of 18.9 billion, and
    `mileage_km` reaches 9,000,000 against a p99 of 497,000. A slider drawn from
    the true maximum spends 97% of its travel on rows that do not exist.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0, 0.0
    return ordered[min(n - 1, int(lo * n))], ordered[min(n - 1, int(hi * n))]


def _snap(value: float, step: float, decimals: int, up: bool) -> float | int:
    """Snap a bound outward onto the slider's own step.

    Rounded to the feature's declared precision because binary floats do not
    divide by 0.1: without this the engine ceiling serialises as
    3.8000000000000003, and the UI would faithfully render every digit.
    """
    if not step:
        return value
    snapped = (np.ceil if up else np.floor)(value / step) * step
    return int(round(snapped)) if decimals == 0 else round(float(snapped), decimals)


def _enum_values(corpus: list[dict], feature: Feature) -> list[dict[str, Any]]:
    """Distinct values with counts, labelled from the data itself.

    Labels come off the rows (`brand_fa`, `model_fa`, `body_type_fa`) rather
    than a table here, so a brand that appears in tomorrow's crawl is labelled
    correctly without anyone editing this file.
    """
    counts: dict[Any, int] = {}
    labels: dict[Any, str] = {}
    parents: dict[Any, str] = {}
    for row in corpus:
        value = feature.value_of(row) if feature.value_of else None
        if value is None or value == "":
            continue
        counts[value] = counts.get(value, 0) + 1
        if value not in labels:
            labels[value] = feature.label_of(row) or str(value)
        if feature.parent_of and value not in parents:
            parent = feature.parent_of(row)
            if parent:
                parents[value] = parent

    english = VALUE_LABELS_EN.get(feature.key, {})
    persian = VALUE_LABELS_FA.get(feature.key, {})
    out = []
    for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        # A hand-written translation wins, then one derived from the value
        # itself; failing both, the Persian stands. Inventing an English name
        # for «نقرآبی» or «اسلام شهر» would be worse than showing the Persian.
        label_en = english.get(value)
        if not label_en and feature.english_of:
            label_en = feature.english_of(str(value))
        entry = {
            "value": value,
            "label_fa": persian.get(value) or labels[value],
            "label_en": label_en or labels[value],
            "count": count,
        }
        if value in parents:
            entry["parent"] = parents[value]
        out.append(entry)
    return out


def _range_bounds(corpus: list[dict], feature: Feature) -> dict[str, Any]:
    values = [v for v in (feature.value_of(row) for row in corpus) if v is not None]
    if not values:
        return {"min": 0, "max": 0, "true_min": 0, "true_max": 0, "count": 0}
    low, high = _clamped_bounds([float(v) for v in values])
    step = feature.step or 1
    return {
        "min": _snap(low, step, feature.decimals, up=False),
        "max": _snap(high, step, feature.decimals, up=True),
        # Kept so the UI can say "and above" rather than pretending the clamped
        # ceiling is the real one.
        "true_min": min(values),
        "true_max": max(values),
        "count": len(values),
    }


def build_catalogue(corpus: list[dict]) -> dict[str, Any]:
    """Everything the filter panel needs, derived from the corpus in one pass."""
    ensure_health_scores(corpus)
    features: list[dict[str, Any]] = []

    for feature in FEATURES:
        entry: dict[str, Any] = {
            "key": feature.key,
            "kind": feature.kind,
            "group": feature.group,
            "label_fa": feature.label_fa,
            "label_en": feature.label_en,
        }
        if feature.unit:
            entry["unit"] = feature.unit
        if feature.step:
            entry["step"] = feature.step
        if feature.decimals:
            entry["decimals"] = feature.decimals
        if feature.parent:
            entry["parent"] = feature.parent
        if feature.bound != "both":
            entry["bound"] = feature.bound

        if feature.kind == "enum":
            entry["values"] = _enum_values(corpus, feature)
        elif feature.kind == "range":
            entry.update(_range_bounds(corpus, feature))
        elif feature.kind == "band":
            entry["values"] = [
                {
                    "value": key, "min_grade": grade, "label_fa": label_fa, "label_en": label_en,
                    "count": sum(1 for r in corpus if (r.get("body_grade") or 0) >= grade),
                }
                for key, grade, label_fa, label_en in PAINT_BANDS
            ]
        elif feature.kind == "bool":
            entry["count"] = sum(1 for r in corpus if feature.value_of and feature.value_of(r))

        features.append(entry)

    return {"total": len(corpus), "groups": GROUPS, "features": features}


# ------------------------------------------------------------ faceted counting


def count_features(rows: list[dict], intent: Intent) -> dict[str, Any]:
    """How many of the current results carry each feature value.

    Counts are **leave-one-out**: a feature's own selection is dropped before
    counting it. Without that, ticking «هیوندای» reports every other brand as
    zero and the buyer can never add «کیا» — multi-select would be unusable.

    One boolean mask per feature, then AND all-but-one. At ~11k rows and 19
    features this is a few million numpy operations, comfortably inside a
    request.
    """
    if not rows:
        return {f.key: ({"values": []} if f.kind in ("enum", "band") else {"count": 0})
                for f in FEATURES}

    masks = np.array(
        [[f.matches(row, intent) for row in rows] for f in FEATURES], dtype=bool
    )
    out: dict[str, Any] = {}

    for i, feature in enumerate(FEATURES):
        others = np.delete(masks, i, axis=0)
        keep = others.all(axis=0) if others.size else np.ones(len(rows), dtype=bool)
        subset = [row for row, ok in zip(rows, keep) if ok]

        if feature.kind == "enum":
            counts: dict[Any, int] = {}
            for row in subset:
                value = feature.value_of(row) if feature.value_of else None
                if value is not None and value != "":
                    counts[value] = counts.get(value, 0) + 1
            out[feature.key] = {
                "values": [
                    {"value": v, "count": c}
                    for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))
                ]
            }
        elif feature.kind == "band":
            out[feature.key] = {
                "values": [
                    {"value": key,
                     "count": sum(1 for r in subset if (r.get("body_grade") or 0) >= grade)}
                    for key, grade, _fa, _en in PAINT_BANDS
                ]
            }
        elif feature.kind == "range":
            values = [v for v in (feature.value_of(row) for row in subset) if v is not None]
            out[feature.key] = {
                "count": len(values),
                "available_min": min(values) if values else None,
                "available_max": max(values) if values else None,
            }
        else:  # bool
            out[feature.key] = {
                "count": sum(1 for r in subset if feature.value_of and feature.value_of(r))
            }

    return out

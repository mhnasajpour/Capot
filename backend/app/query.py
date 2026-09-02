"""Turn a free-text Persian query into a structured search intent.

    "اولین ماشین خانواده، بودجه ۸۰۰ میلیون، کم‌مصرف و بدون رنگ"
      -> budget_max=800_000_000, use_case='family', priorities=['low_consumption'],
         require_clean_body=True

Two paths, same output shape:

  * **LLM path** — handles the long tail: unusual phrasings, implied
    constraints ("برای دربست کار کنم" implies durability and cheap parts).
  * **Rule path** — a deterministic parser covering budget, body style, fuel,
    transmission, brand and the common use-case phrases.

The rule parser always runs and the LLM result is merged *on top* of it, so a
missing key or a dead proxy degrades the query rather than emptying it.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .llm import complete_json
from .normalize import fa_to_en_digits

MILLION = 1_000_000
BILLION = 1_000_000_000

USE_CASES = {"family", "first_car", "economy", "commute", "offroad", "luxury", "work", "performance"}
PRIORITIES = {
    "low_consumption", "low_depreciation", "cheap_parts", "comfort",
    "performance", "safety", "space", "reliability", "economy",
}

BODY_TYPE_WORDS = {
    "سدان": "passenger_car", "صندوق دار": "passenger_car", "صندوق‌دار": "passenger_car",
    "کراس": "crossover", "کراس اور": "crossover", "کراس‌اور": "crossover",
    "شاسی بلند": "suv", "شاسی‌بلند": "suv", "اس یو وی": "suv",
    "هاچبک": "hatchback", "وانت": "pickup", "کوپه": "coupe",
}

FUEL_WORDS = {
    "بنزین": "بنزینی", "دوگانه": "دوگانه سوز", "گاز": "دوگانه سوز",
    "دیزل": "دیزل", "برقی": "برقی", "هیبرید": "هیبرید",
}

USE_CASE_WORDS = {
    "خانواده": "family", "خانوادگی": "family",
    "اولین ماشین": "first_car", "اولین خودرو": "first_car", "تازه کار": "first_car",
    "اقتصادی": "economy", "ارزان": "economy", "کم هزینه": "economy",
    "دانشجو": "first_car", "برای شروع": "first_car", "تازه": "first_car",
    "دربست": "work", "کار": "work", "مسافرکشی": "work", "اسنپ": "work", "تاکسی": "work",
    "آفرود": "offroad", "آف رود": "offroad", "کوهستان": "offroad",
    "لاکچری": "luxury", "لوکس": "luxury",
    "اسپرت": "performance", "سرعت": "performance",
    "شهری": "commute", "ترافیک": "commute", "رفت و آمد": "commute",
}

PRIORITY_WORDS = {
    "کم مصرف": "low_consumption", "کم‌مصرف": "low_consumption", "مصرف پایین": "low_consumption",
    "کم استهلاک": "low_depreciation", "کم‌استهلاک": "low_depreciation",
    "قطعات ارزان": "cheap_parts", "لوازم یدکی": "cheap_parts", "تعمیر ارزان": "cheap_parts",
    "راحت": "comfort", "راحتی": "comfort",
    "ایمن": "safety", "ایمنی": "safety",
    "جادار": "space", "فضای داخلی": "space", "بزرگ": "space",
    "بی دردسر": "reliability", "بی‌دردسر": "reliability", "مطمئن": "reliability",
}

# Brand names as buyers type them, mapped to the slug Bama uses.
BRAND_WORDS = {
    "پژو": "peugeot", "پراید": "pride", "سمند": "samand", "تیبا": "tiba",
    "کوییک": "quick", "دنا": "dena", "رانا": "rana", "شاهین": "shahin",
    "تارا": "tara", "ساینا": "saina", "هیوندای": "hyundai", "هیوندا": "hyundai",
    "کیا": "kia", "تویوتا": "toyota", "رنو": "renault", "مزدا": "mazda",
    "بنز": "benz", "ب ام و": "bmw", "بی ام و": "bmw", "چری": "chery",
    "ام وی ام": "mvm", "جک": "jac", "لیفان": "lifan", "نیسان": "nissan",
    "کوییک ار": "quick",
}

CLEAN_BODY_WORDS = ("بدون رنگ", "بدون‌رنگ", "سالم", "بی رنگ", "بی‌رنگ")

SYSTEM_PROMPT = """You parse Persian car-shopping queries into JSON search filters.
Return ONLY a JSON object with these optional keys:
  budget_min, budget_max: integers in Iranian toman
  max_mileage_km: integer
  min_year_gregorian, max_age_years: integers
  body_types: array of ["passenger_car","crossover","suv","hatchback","pickup","coupe"]
  fuel: string (Persian, e.g. "بنزینی")
  transmission: "اتوماتیک" or "دنده ای"
  brands: array of lowercase latin brand slugs (peugeot, pride, kia, toyota, ...)
  use_case: one of ["family","first_car","economy","commute","offroad","luxury","work","performance"]
  priorities: array of ["low_consumption","low_depreciation","cheap_parts","comfort","performance","safety","space","reliability"]
  require_clean_body: boolean (true if the buyer wants no repainted panels)
  city: Persian city name if the buyer named one
Omit keys the query does not imply. Amounts: "۸۰۰ میلیون" = 800000000, "۲ میلیارد" = 2000000000.
Infer implied needs: a family car implies space and safety; a work/taxi car implies
cheap_parts and reliability; a first car implies economy and low_consumption."""


@dataclass
class Intent:
    """Structured form of what the buyer asked for.

    Two things fill this in and they meet here deliberately: the parsers below,
    reading Persian prose, and `features.Filters`, reading what the buyer ticked
    in the UI. One structure means `rank.passes_filters` has a single definition
    of every constraint, so a filter can never mean one thing when typed and
    another when clicked.

    The fields below the divider exist only for the explicit-filter path — the
    prose parsers never set them, so they default to "unset" and a pure
    natural-language query behaves exactly as it did before they existed.
    """

    raw_query: str = ""
    budget_min: int | None = None
    budget_max: int | None = None
    max_mileage_km: int | None = None
    min_year_gregorian: int | None = None
    max_age_years: int | None = None
    body_types: list[str] = field(default_factory=list)
    fuel: str | None = None
    transmission: str | None = None
    brands: list[str] = field(default_factory=list)
    use_case: str | None = None
    priorities: list[str] = field(default_factory=list)
    require_clean_body: bool = False
    city: str | None = None
    parsed_by: str = "rules"

    # ---- set by explicit feature selection, never by the prose parsers ----
    # `fuel`/`transmission`/`city` above stay singular substring tests because
    # that is how prose arrives («اتومات»); these are exact, multi-select sets.
    models: list[str] = field(default_factory=list)        # "brand/model" keys
    transmissions: list[str] = field(default_factory=list)
    fuels: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    cities: list[str] = field(default_factory=list)
    sellers: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    max_year: int | None = None
    min_mileage_km: int | None = None
    engine_min_l: float | None = None
    engine_max_l: float | None = None
    max_consumption_l100: float | None = None
    min_body_grade: int | None = None
    min_health: int | None = None
    only_below_market: bool = False
    only_inspected: bool = False
    only_with_image: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_empty(self) -> bool:
        """True when the query yielded no usable constraint at all."""
        return not any([
            self.budget_min, self.budget_max, self.max_mileage_km,
            self.min_year_gregorian, self.max_age_years, self.body_types,
            self.fuel, self.transmission, self.brands, self.use_case,
            self.priorities, self.require_clean_body, self.city,
            self.models, self.transmissions, self.fuels, self.colors,
            self.cities, self.sellers, self.sources, self.max_year,
            self.min_mileage_km, self.engine_min_l, self.engine_max_l,
            self.max_consumption_l100, self.min_body_grade, self.min_health,
            self.only_below_market, self.only_inspected, self.only_with_image,
        ])


def _parse_amounts(text: str) -> list[int]:
    """Find toman amounts written as '۸۰۰ میلیون' / '2.5 میلیارد' / '800m'."""
    normalized = fa_to_en_digits(text)
    amounts: list[int] = []
    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(میلیارد|میلیون|تومان|م\b)?", normalized):
        raw, unit = match.group(1), match.group(2)
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if unit == "میلیارد":
            amounts.append(int(value * BILLION))
        elif unit in ("میلیون", "م"):
            amounts.append(int(value * MILLION))
        elif unit == "تومان" and value >= MILLION:
            amounts.append(int(value))
        elif value >= 10 * MILLION:  # a bare large number is already in toman
            amounts.append(int(value))
    return amounts


def _parse_budget(text: str, intent: Intent) -> None:
    amounts = [a for a in _parse_amounts(text) if a >= 10 * MILLION]
    if not amounts:
        return

    has_upper = any(w in text for w in ("تا ", "زیر", "حداکثر", "کمتر از", "بودجه", "سقف"))
    has_lower = any(w in text for w in ("از ", "بالای", "حداقل", "بیشتر از"))

    if len(amounts) >= 2 and ("تا" in text or "بین" in text):
        intent.budget_min, intent.budget_max = min(amounts), max(amounts)
    elif has_lower and not has_upper:
        intent.budget_min = max(amounts)
    else:
        # "بودجه ۸۰۰ میلیون" reads as a ceiling to any Iranian buyer.
        intent.budget_max = max(amounts)


def _parse_mileage(text: str, intent: Intent) -> None:
    normalized = fa_to_en_digits(text)
    match = re.search(r"(?:کارکرد|کیلومتر|کارکرده)\D{0,12}(\d+(?:[.,]\d+)?)\s*(هزار|میلیون)?", normalized)
    if not match:
        return
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return
    unit = match.group(2)
    if unit == "هزار":
        value *= 1_000
    elif unit == "میلیون":
        value *= MILLION
    elif value < 1000:  # "کارکرد ۱۵۰" means 150 thousand km
        value *= 1_000
    intent.max_mileage_km = int(value)


def _parse_year(text: str, intent: Intent) -> None:
    normalized = fa_to_en_digits(text)
    match = re.search(r"(?:مدل|سال)\s*(\d{4})\s*(?:به بالا|به بعد)?", normalized)
    if not match:
        return
    year = int(match.group(1))
    intent.min_year_gregorian = year + 621 if year <= 1500 else year


def parse_with_rules(text: str) -> Intent:
    """Deterministic parser. Always runs; never raises."""
    intent = Intent(raw_query=text, parsed_by="rules")
    if not text:
        return intent

    _parse_budget(text, intent)
    _parse_mileage(text, intent)
    _parse_year(text, intent)

    for word, body_type in BODY_TYPE_WORDS.items():
        if word in text and body_type not in intent.body_types:
            intent.body_types.append(body_type)

    for word, fuel in FUEL_WORDS.items():
        if word in text:
            intent.fuel = fuel
            break

    if "اتومات" in text:
        intent.transmission = "اتوماتیک"
    elif "دنده" in text and "اتومات" not in text:
        intent.transmission = "دنده ای"

    for word, brand in BRAND_WORDS.items():
        if word in text and brand not in intent.brands:
            intent.brands.append(brand)

    for word, use_case in USE_CASE_WORDS.items():
        if word in text:
            intent.use_case = use_case
            break

    for word, priority in PRIORITY_WORDS.items():
        if word in text and priority not in intent.priorities:
            intent.priorities.append(priority)

    if any(word in text for word in CLEAN_BODY_WORDS):
        intent.require_clean_body = True

    _apply_use_case_priors(intent)
    return intent


def _apply_use_case_priors(intent: Intent) -> None:
    """A stated use case implies priorities the buyer did not spell out."""
    implied = {
        "family": ["space", "safety", "comfort"],
        "first_car": ["economy", "low_consumption", "cheap_parts"],
        # 'economy' scores price against the market median, so it has to be in
        # the list for a budget-minded query to actually rank cheaper cars
        # higher. Leaving it out was why «ماشین ارزان برای شروع» ignored price.
        "economy": ["economy", "low_consumption", "cheap_parts"],
        "work": ["economy", "cheap_parts", "reliability", "low_consumption"],
        "commute": ["economy", "low_consumption", "reliability"],
        "luxury": ["comfort", "performance"],
        "offroad": ["space", "reliability"],
        "performance": ["performance"],
    }.get(intent.use_case or "", [])

    for priority in implied:
        if priority in PRIORITIES and priority not in intent.priorities:
            intent.priorities.append(priority)


def _merge_llm(intent: Intent, data: dict) -> Intent:
    """Overlay validated LLM output onto the rule-parsed intent."""
    def as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    intent.budget_min = as_int(data.get("budget_min")) or intent.budget_min
    intent.budget_max = as_int(data.get("budget_max")) or intent.budget_max
    intent.max_mileage_km = as_int(data.get("max_mileage_km")) or intent.max_mileage_km
    intent.min_year_gregorian = as_int(data.get("min_year_gregorian")) or intent.min_year_gregorian
    intent.max_age_years = as_int(data.get("max_age_years")) or intent.max_age_years

    for body_type in data.get("body_types") or []:
        if isinstance(body_type, str) and body_type not in intent.body_types:
            intent.body_types.append(body_type)

    for brand in data.get("brands") or []:
        if isinstance(brand, str) and brand.lower() not in intent.brands:
            intent.brands.append(brand.lower())

    if isinstance(data.get("fuel"), str):
        intent.fuel = intent.fuel or data["fuel"]
    if isinstance(data.get("transmission"), str):
        intent.transmission = intent.transmission or data["transmission"]
    if isinstance(data.get("city"), str):
        intent.city = intent.city or data["city"]

    use_case = data.get("use_case")
    if isinstance(use_case, str) and use_case in USE_CASES:
        intent.use_case = intent.use_case or use_case

    for priority in data.get("priorities") or []:
        if isinstance(priority, str) and priority in PRIORITIES and priority not in intent.priorities:
            intent.priorities.append(priority)

    if data.get("require_clean_body") is True:
        intent.require_clean_body = True

    intent.parsed_by = "llm+rules"
    _apply_use_case_priors(intent)
    return intent


def parse_query(text: str, *, allow_live: bool = True) -> Intent:
    """Parse a shopping query into an Intent, using the LLM when available."""
    text = (text or "").strip()
    intent = parse_with_rules(text)
    if not text:
        return intent

    data = complete_json(
        SYSTEM_PROMPT,
        json.dumps({"query": text}, ensure_ascii=False),
        allow_live=allow_live,
    )
    if isinstance(data, dict):
        try:
            return _merge_llm(intent, data)
        except Exception:  # noqa: BLE001 - malformed LLM output must never break search
            return intent
    return intent

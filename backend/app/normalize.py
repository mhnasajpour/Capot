"""Turn raw Bama ad payloads into clean, typed records.

This module exists because the source data is genuinely messy in ways that
matter for pricing:

  * mileage is either the string 'صفر کیلومتر' or '240,000 km'
  * model years are Jalali for domestic cars (1391) and Gregorian for imports
    (2012) — in the *same* field, with no flag distinguishing them
  * prices are comma-formatted strings, and ~36% are '0' meaning "negotiable"
    (توافقی) rather than free
  * digits may arrive as Persian (۰۱۲) or Arabic-Indic (٠١٢) numerals
  * body condition is a Persian phrase on an implicit severity scale

Everything here is pure and side-effect free so it can be unit-tested and
re-run over the raw JSONL without re-crawling.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

# Jalali years are ~621 years behind Gregorian. Verified against the source data:
# a listing with year '1391' resolves to a Mazda 3 sold as a 2012 model.
JALALI_OFFSET = 621
# Any 4-digit year above this is Gregorian; below it is Jalali. Jalali years in
# the corpus run ~1370-1405, Gregorian ~2000-2026, so the gap is unambiguous.
JALALI_MAX = 1500

CURRENT_GREGORIAN_YEAR = 2026

PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_DIGIT_MAP = {ord(c): str(i) for i, c in enumerate(PERSIAN_DIGITS)}
_DIGIT_MAP.update({ord(c): str(i) for i, c in enumerate(ARABIC_DIGITS)})

# 'صفر' (zero) is the only reliable zero-mileage marker. Do NOT substring-match
# numeric forms like '0 km' here: '240,000 km' contains '0 km'.
ZERO_MILEAGE_TOKEN = "صفر"

# Body condition on a 0-100 "paint integrity" scale. Higher is better.
# Ordering follows how the Iranian market actually discounts a car: untouched
# paint commands a premium, a full respray (دور رنگ) signals major work, and a
# replaced chassis section (تعویض) is the worst outcome short of a write-off.
BODY_STATUS_GRADE: dict[str, int] = {
    "بدون رنگ": 100,
    "صافکاری بدون رنگ": 85,
    "خط و خش جزئی": 80,
    "یک لکه رنگ": 70,
    "دو لکه رنگ": 58,
    "گلگیر رنگ": 52,
    "چند لکه رنگ": 45,
    "دور رنگ": 28,
    "تمام رنگ": 22,
    "کامل رنگ": 22,
    "تعویض شده": 12,
    "اتاق تعویض": 8,
    "دوررنگ": 28,
}
DEFAULT_BODY_GRADE = 60  # unknown phrasing: assume middling rather than punish

SELLER_PRIVATE = "شخصی"
SELLER_SHOWROOM = "نمایشگاه"
SELLER_AGENCY = "نمایندگی"
#: Divar, Sheypoor and Karnameh have no agency tier — a listing is a person's or
#: a shop's — so they all reach for the showroom wording. The alias is here so
#: they can say what they mean without each redeclaring the string, which is how
#: `crawl/divar.py` came to own a second copy of `SELLER_PRIVATE` that
#: `karnameh.py` and `sheypoor.py` then imported *from an adapter*.
SELLER_DEALER = SELLER_SHOWROOM

# Gearbox and fuel as the classifieds write them, mapped onto Bama's wording —
# the vocabulary `normalize_ad`, the UI and `features.VALUE_LABELS_EN` already
# speak. Shared here because three adapters need the same tables: Divar and
# Karnameh had byte-identical copies of TRANSMISSION_MAP, and Sheypoor imported
# both of Divar's.
TRANSMISSION_MAP = {
    "دنده‌ای": "دنده ای", "دنده ای": "دنده ای", "اتوماتیک": "اتوماتیک",
}
FUEL_MAP = {
    "بنزین": "بنزینی", "بنزینی": "بنزینی", "دوگانه سوز": "دوگانه سوز",
    "دوگانه‌سوز": "دوگانه سوز", "گازوئیل": "دیزلی", "دیزل": "دیزلی",
    "هیبرید": "هیبریدی", "برقی": "برقی",
}


def make_code(source: str, native_code: str) -> str:
    """Globally unique listing id across sources.

    Bama and Divar both mint short opaque ids in their own namespaces, so the
    source must be part of the key. Underscore keeps it URL-safe for
    /api/car/{code}.
    """
    return f"{source}_{native_code}"


def fa_to_en_digits(text: str) -> str:
    """Normalize Persian/Arabic-Indic numerals to ASCII."""
    return text.translate(_DIGIT_MAP)


def parse_number(value: Any) -> int | None:
    """Pull the first integer out of a possibly-Persian, comma-formatted string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = fa_to_en_digits(str(value)).replace(",", "").replace("٬", "")
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def parse_float(value: Any) -> float | None:
    """Pull the first decimal number out of a string like '9.2 ثانیه'."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = fa_to_en_digits(str(value)).replace(",", "")
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def parse_price(raw_price: Any, price_type: str | None) -> tuple[int | None, bool]:
    """Return (price_toman, is_negotiable).

    Bama encodes "price on request" as type='negotiable' with price '0'. We keep
    that as None + a flag rather than 0, because a zero would poison any model
    trained on it — and because *predicting* these is the product's core feature.
    """
    price = parse_number(raw_price)
    negotiable = (price_type or "").lower() == "negotiable" or not price
    if negotiable or not price:
        return None, True
    return price, False


def parse_mileage(raw: Any) -> int | None:
    """'صفر کیلومتر' -> 0, '240,000 km' -> 240000, junk -> None."""
    if raw is None:
        return None
    text = fa_to_en_digits(str(raw).strip())
    if ZERO_MILEAGE_TOKEN in text:
        return 0
    # parse_number handles '240,000 km' -> 240000 and a bare '0' -> 0.
    return parse_number(text)


def parse_year(raw: Any) -> tuple[int | None, str | None]:
    """Normalize a mixed Jalali/Gregorian year field.

    Returns (gregorian_year, calendar) where calendar is 'jalali' or 'gregorian'
    so the UI can show the year the seller actually advertised.
    """
    year = parse_number(raw)
    if not year:
        return None, None
    if year <= JALALI_MAX:
        return year + JALALI_OFFSET, "jalali"
    return year, "gregorian"


def body_status_grade(status: str | None) -> int:
    """Map a Persian body-condition phrase to a 0-100 paint-integrity score."""
    if not status:
        return DEFAULT_BODY_GRADE
    text = status.strip()
    if text in BODY_STATUS_GRADE:
        return BODY_STATUS_GRADE[text]
    # Fall back to substring matching so unseen phrasings still land sensibly.
    for phrase, grade in BODY_STATUS_GRADE.items():
        if phrase in text:
            return grade
    return DEFAULT_BODY_GRADE


# Body condition as sellers write it in prose rather than declare it in a field.
# Divar omits وضعیت بدنه on nearly every listing but its sellers state it in the
# title or description ("لیفان 820 بدون رنگ"), and a car owner describing their
# own car does the same. Body condition is the strongest input to the health
# score, so reading it out of text is worth doing; anything inferred this way is
# marked as such so the UI never presents it as a declared field.
BODY_TEXT_PATTERNS: list[tuple[tuple[str, ...], str, int]] = [
    (("تصادفی", "ضربه خورده"), "تصادفی", 15),
    (("اتاق تعویض", "تعویض اتاق"), "اتاق تعویض", 8),
    (("دور رنگ", "دوررنگ", "تمام رنگ"), "دور رنگ", 28),
    (("رنگ شدگی", "رنگ‌شدگی", "لکه رنگ", "آبرنگ"), "رنگ‌شدگی", 55),
    (("صافکاری",), "صافکاری بدون رنگ", 85),
    (("خط و خش", "خط وخش"), "خط و خش جزئی", 80),
    (("بدون رنگ", "بی رنگ", "بی‌رنگ", "بیرنگ", "فول رنگ اصل", "رنگ اصل"), "بدون رنگ", 100),
]


def infer_body_status(*texts: str | None) -> tuple[str | None, int | None]:
    """Read body condition out of free text. Worst match wins.

    Ordered worst-first so «بدون رنگ به جز دور رنگ گلگیر» can't be read as
    a clean car — a seller's optimistic phrasing must not inflate the score.
    """
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None, None
    for phrases, label, grade in BODY_TEXT_PATTERNS:
        if any(p in blob for p in phrases):
            return label, grade
    return None, None


def seller_type(dealer: dict | None) -> str:
    """Private sellers have no dealer object at all."""
    if not dealer:
        return SELLER_PRIVATE
    return dealer.get("type") or SELLER_SHOWROOM


@dataclass
class Listing:
    """One normalized car listing."""

    code: str
    url: str
    title: str
    brand: str | None
    brand_fa: str | None
    model: str | None
    trim: str | None
    trim_en: str | None

    year: int | None            # always Gregorian
    year_display: int | None    # as advertised (may be Jalali)
    year_calendar: str | None
    age: int | None

    mileage_km: int | None
    price_toman: int | None
    is_negotiable: bool
    price_type: str | None

    body_status: str | None
    body_grade: int
    body_type: str | None
    body_type_fa: str | None
    transmission: str | None
    fuel: str | None
    body_color: str | None
    inside_color: str | None

    seller: str
    dealer_name: str | None
    dealer_score: float | None
    dealer_ad_count: int | None
    authenticated: bool

    city: str | None
    location: str | None
    description: str | None
    image: str | None
    image_count: int

    engine_volume_l: float | None
    power_hp: float | None
    acceleration_s: float | None
    consumption_l100: float | None

    modified_date: str | None
    life_styles: list[str] = field(default_factory=list)

    # Multi-source fields. Defaulted so single-source construction is unchanged.
    source: str = "bama"
    #: Persian model name — Divar gives this directly; for Bama it comes from
    #: the title. Used to match models across sources, which name them
    #: differently in Latin ('206ir' vs '206').
    model_fa: str | None = None
    #: Months of remaining third-party insurance. Divar only.
    insurance_months: int | None = None
    #: Chassis condition (وضعیت شاسی). Sheypoor declares it per listing and is
    #: the only source that does, so corpus coverage is far too thin to filter
    #: on — the same reason `power_hp` and `insurance_months` are kept out of
    #: the feature catalogue. It is scored in `health.py` where it is present.
    chassis_status: str | None = None
    #: Codes of listings judged to be the same car on another site.
    duplicate_of: list[str] = field(default_factory=list)

    @property
    def cohort_key(self) -> str:
        """Group key for price comparables: same brand+model+trim+year."""
        return f"{self.brand}|{self.model}|{self.trim_en}|{self.year}"

    @property
    def model_key(self) -> str:
        """Looser group key, used when the exact-trim cohort is too thin."""
        return f"{self.brand}|{self.model}|{self.year}"

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_ad(ad: dict) -> Listing | None:
    """Convert one raw search-feed ad into a Listing. Returns None if unusable."""
    detail = ad.get("detail") or {}
    code = detail.get("code")
    if not code:
        return None

    specs = ad.get("specs") or {}
    dealer = ad.get("dealer") or None
    price_block = ad.get("price") or {}

    year_g, calendar = parse_year(detail.get("year"))
    price, negotiable = parse_price(price_block.get("price"), price_block.get("type"))

    # The search feed carries neither model nor trim_en; recover both from the URL.
    url = detail.get("url") or ""
    slug_model, slug_trim_en = parse_url_slug(url, code, detail.get("brand"))

    brand_fa_title, model_fa_title = (detail.get("title") or "").partition("،")[::2]

    return Listing(
        code=make_code("bama", code),
        url=url,
        title=(detail.get("title") or "").strip(),
        brand=detail.get("brand"),
        brand_fa=detail.get("brand_fa"),
        model=detail.get("model") or slug_model,
        trim=detail.get("trim"),
        trim_en=detail.get("trim_en") or slug_trim_en,
        year=year_g,
        year_display=parse_number(detail.get("year")),
        year_calendar=calendar,
        age=(CURRENT_GREGORIAN_YEAR - year_g) if year_g else None,
        mileage_km=parse_mileage(detail.get("mileage")),
        price_toman=price,
        is_negotiable=negotiable,
        price_type=price_block.get("type"),
        body_status=detail.get("body_status"),
        body_grade=body_status_grade(detail.get("body_status")),
        body_type=detail.get("body_type"),
        body_type_fa=detail.get("body_type_fa"),
        transmission=detail.get("transmission"),
        fuel=detail.get("fuel"),
        body_color=detail.get("body_color"),
        inside_color=detail.get("inside_color"),
        seller=seller_type(dealer),
        dealer_name=(dealer or {}).get("name"),
        dealer_score=(dealer or {}).get("score"),
        dealer_ad_count=(dealer or {}).get("ad_count"),
        authenticated=bool(detail.get("authenticated")),
        city=detail.get("province") or _city_from_location(detail.get("location")),
        location=detail.get("location"),
        description=(detail.get("description") or "").strip() or None,
        image=detail.get("image"),
        image_count=detail.get("image_count") or 0,
        engine_volume_l=parse_float(specs.get("volume")),
        power_hp=parse_float(specs.get("power")),
        acceleration_s=parse_float(specs.get("acceleration")),
        consumption_l100=parse_float(specs.get("fuel")),
        modified_date=detail.get("modified_date"),
        life_styles=[ls.get("display_name") for ls in (detail.get("life_styles") or []) if ls.get("display_name")],
        source="bama",
        model_fa=(model_fa_title or "").strip() or None,
    )


def _city_from_location(location: str | None) -> str | None:
    """Search-feed location is 'تهران / تجریش' — city first, neighbourhood second."""
    if not location:
        return None
    return location.split("/")[0].strip() or None


def parse_url_slug(url: str | None, code: str | None, brand: str | None) -> tuple[str | None, str | None]:
    """Recover (model, trim_en) from the listing URL.

    The search feed omits `model` and `trim_en` entirely — they are only on the
    detail endpoint — but both are embedded in the URL slug:

        /car/detail-tocysn0l-mazda-3sedan-2.0ltype4-1395
                    └code──┘ └brand┘ └model┘ └trim─┘ └year┘

    Without this, every listing would share the same empty cohort key and the
    fair-price comparables would be meaningless. We peel off the parts we
    already know (code, brand, trailing year) and split what remains, which is
    robust to multi-token models and trims.
    """
    if not url:
        return None, None

    slug = url.rsplit("/", 1)[-1]
    slug = slug.removeprefix("detail-")

    # Case-insensitive: the brand field is occasionally capitalised ('Voyah')
    # while the slug is always lowercase.
    lowered = slug.lower()
    if code and lowered.startswith(f"{code.lower()}-"):
        slug = slug[len(code) + 1:]
        lowered = slug.lower()
    if brand and lowered.startswith(f"{brand.lower()}-"):
        slug = slug[len(brand) + 1:]

    parts = [p for p in slug.split("-") if p]
    if parts and re.fullmatch(r"\d{4}", parts[-1]):
        parts = parts[:-1]  # trailing model year
    if not parts:
        return None, None

    model = parts[0]
    trim_en = "-".join(parts[1:]) or None
    return model, trim_en


def merge_detail(listing: Listing, detail_data: dict) -> Listing:
    """Fold a detail-endpoint record into an existing Listing.

    Detail adds specs the search feed omits (power, torque, drive shaft) plus
    Bama's own `life_styles` tags, which are useful need-fit priors.
    """
    detail = detail_data.get("detail") or {}
    specs = detail_data.get("specs") or {}

    listing.power_hp = listing.power_hp or parse_float(specs.get("power"))
    listing.acceleration_s = listing.acceleration_s or parse_float(specs.get("acceleration"))
    listing.consumption_l100 = listing.consumption_l100 or parse_float(specs.get("fuel"))
    listing.engine_volume_l = listing.engine_volume_l or parse_float(specs.get("volume"))
    listing.city = listing.city or detail.get("province")
    listing.model = listing.model or detail.get("model")
    listing.trim_en = listing.trim_en or detail.get("trim_en")

    tags = [ls.get("display_name") for ls in (detail.get("life_styles") or []) if ls.get("display_name")]
    if tags:
        listing.life_styles = sorted(set(listing.life_styles) | set(tags))
    return listing

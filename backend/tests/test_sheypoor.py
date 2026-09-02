"""Tests for the Sheypoor adapter.

Sheypoor puts a listing's whole spec sheet in the search response, so unlike
Divar there is no detail payload to reconstruct — but the row mixes real ads
with paid furniture, and its paint vocabulary is its own. Those two things are
where the risk is. The fixtures mirror payloads captured from the live API.
"""

from app.crawl.sheypoor import (
    SheypoorSource,
    attributes,
    chassis_condition,
    listing_rows,
    parse_city,
    parse_price,
)


def _row(row_id: str, *, title: str, price: list | None, crumbs: list[str],
         attrs: dict[str, str], shop: bool = False, description: str = "",
         location: str = "تهران، تجریش", kind: str = "normal") -> dict:
    return {
        "id": row_id,
        "type": kind,
        "description": description,
        "fullAttributes": [{"key": k, "value": v} for k, v in attrs.items()],
        "attributes": {
            "title": title,
            "location": location,
            "url": f"https://www.sheypoor.com/v/x-{row_id}.html",
            "price": price,
            "imageCount": 8,
            "shopLogo": "https://example/logo.webp" if shop else None,
            "isSecurePurchase": False,
            "images": {"thumbnails": {"landscape": "https://cdn/x.webp"}},
            "categories": [{"name": c} for c in crumbs],
        },
    }


SAMAND = _row(
    "466915662",
    title="سمند Ef7 دوگانه سوز",
    price=[{"label": "", "amount": "1,630,000,000", "currency": "تومان"}],
    crumbs=["وسایل نقلیه", "خودرو", "سمند"],
    attrs={
        "مدل خودرو": "LX EF7 (دوگانه سوز)",
        "سال تولید (چهار رقمی)": "1400",
        "کیلومتر": "120000",
        "وضعیت بدنه": "سالم بدون خط و خش",
        "گیربکس": "دنده‌ای",
        "نوع سوخت": "دوگانه سوز",
        "رنگ": "سفید",
        "نوع شاسی": "سدان (سواری)",
        "وضعیت شاسی جلو": "سالم و پلمپ",
        "وضعیت شاسی عقب": "سالم و پلمپ",
    },
    description="سمند Ef7 دوگانه کارخونه میباشد",
    location="قائم شهر، خیابان تهران",
)


def test_listing_rows_drops_paid_furniture():
    """A page is mostly ads, but not entirely."""
    payload = {"data": [
        SAMAND,
        {"type": "paidEngagement", "id": "1", "attributes": {}},
        {"type": "banner", "id": "2"},
        {"type": "nativeAd", "id": "3"},
        {"type": "catalogLink", "id": "4"},
    ]}
    assert [r["id"] for r in listing_rows(payload)] == ["466915662"]


def test_listing_rows_unwraps_the_vip_carousel():
    """`vip` is a container of listings, not a listing — skipping it loses cars."""
    vip_item = dict(SAMAND, id="999", type="vip")
    payload = {"data": [{"type": "vip", "items": [vip_item]}]}
    assert [r["id"] for r in listing_rows(payload)] == ["999"]


def test_parse_price_reads_a_hidden_price_as_negotiable():
    """'توافقی' must become NULL, never 0 — a zero would poison the model."""
    assert parse_price({"price": [{"amount": "1,630,000,000"}]}) == (1630000000, False)
    assert parse_price({"price": [{"label": "قیمت", "amount": "توافقی"}]}) == (None, True)
    assert parse_price({"price": []}) == (None, True)


def test_parse_city_splits_on_the_persian_comma():
    """Sheypoor separates city from district with '،', where Bama uses '/'."""
    assert parse_city("قائم شهر، خیابان تهران") == ("قائم شهر", "خیابان تهران")
    assert parse_city("پیرانشهر") == ("پیرانشهر", None)
    assert parse_city(None) == (None, None)


def test_chassis_condition_ignores_the_undeclared_answer():
    """'اعلام نشده' means the seller didn't say, which is not a healthy chassis."""
    assert chassis_condition({"وضعیت شاسی جلو": "سالم و پلمپ",
                              "وضعیت شاسی عقب": "سالم و پلمپ"}) == "جلو سالم و پلمپ، عقب سالم و پلمپ"
    assert chassis_condition({"وضعیت شاسی جلو": "اعلام نشده",
                              "وضعیت شاسی عقب": "اعلام نشده"}) is None
    assert chassis_condition({}) is None


def test_attributes_flattens_the_pair_list():
    assert attributes(SAMAND)["کیلومتر"] == "120000"


def test_normalize_reads_the_whole_listing():
    listing = SheypoorSource.__new__(SheypoorSource).normalize(
        {"_id": "466915662", "row": SAMAND}
    )
    assert listing is not None
    assert listing.code == "sheypoor_466915662"
    assert listing.source == "sheypoor"
    assert listing.brand_fa == "سمند"
    # The parenthesised suffix is trim detail; the cohort join wants the model.
    assert listing.model_fa == "LX EF7"
    # 1400 is Jalali and must be converted, with the advertised year preserved.
    assert (listing.year, listing.year_display, listing.year_calendar) == (2021, 1400, "jalali")
    assert listing.mileage_km == 120000
    assert (listing.price_toman, listing.is_negotiable) == (1630000000, False)
    assert listing.transmission == "دنده ای"
    assert listing.fuel == "دوگانه سوز"
    assert listing.city == "قائم شهر"
    assert listing.chassis_status == "جلو سالم و پلمپ، عقب سالم و پلمپ"
    # brand/model stay unresolved: canonical.py fills them from the Persian.
    assert listing.brand is None and listing.model is None


def test_normalize_grades_sheypoors_own_paint_vocabulary():
    """'سالم بدون خط و خش' is Sheypoor's wording; Divar's table doesn't have it."""
    src = SheypoorSource.__new__(SheypoorSource)
    assert src.normalize({"_id": "1", "row": SAMAND}).body_grade == 100

    scratched = _row("2", title="x", price=[{"amount": "1,000"}],
                     crumbs=["وسایل نقلیه", "خودرو", "پراید"],
                     attrs={"وضعیت بدنه": "سالم با خط و خش"})
    assert src.normalize({"_id": "2", "row": scratched}).body_grade == 82

    # These three already live in normalize.BODY_STATUS_GRADE and must agree.
    spotted = _row("3", title="x", price=[{"amount": "1,000"}],
                   crumbs=["وسایل نقلیه", "خودرو", "پراید"],
                   attrs={"وضعیت بدنه": "چند لکه رنگ"})
    assert src.normalize({"_id": "3", "row": spotted}).body_grade == 45


def test_normalize_rejects_a_row_that_is_not_a_car():
    """A mis-set category filter returns apartments without erroring, so the
    breadcrumb is checked rather than the query trusted."""
    flat = _row("9", title="آپارتمان ۹۰ متری", price=[{"amount": "5,000,000,000"}],
                crumbs=["املاک", "فروش مسکونی", "آپارتمان"],
                attrs={"متراژ": "90", "تعداد اتاق": "2"})
    assert SheypoorSource.__new__(SheypoorSource).normalize({"_id": "9", "row": flat}) is None


def test_normalize_rejects_a_row_with_no_brand():
    bare = _row("8", title="خودرو", price=[{"amount": "1,000"}],
                crumbs=["وسایل نقلیه", "خودرو"], attrs={})
    assert SheypoorSource.__new__(SheypoorSource).normalize({"_id": "8", "row": bare}) is None


def test_normalize_marks_a_storefront_ad_as_a_dealer():
    shop = _row("7", title="x", price=[{"amount": "1,000"}],
                crumbs=["وسایل نقلیه", "خودرو", "پژو"], attrs={}, shop=True)
    src = SheypoorSource.__new__(SheypoorSource)
    assert src.normalize({"_id": "7", "row": shop}).seller == "نمایشگاه"
    assert src.normalize({"_id": "1", "row": SAMAND}).seller == "شخصی"

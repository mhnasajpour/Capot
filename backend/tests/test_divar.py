"""Tests for the Divar adapter.

Divar returns presentation data, not records, so almost all of the risk is in
parsing. The fixtures below mirror real payloads captured from the live API.
"""

from app.canonical import BrandResolver
from app.crawl.divar import (
    DivarSource,
    extract_breadcrumb,
    extract_fields,
    infer_body_status,
    parse_divar_year,
)


def _detail(fields: dict[str, str], crumbs: list[str], title: str) -> dict:
    """Rebuild the widget shape Divar actually returns."""
    return {
        "sections": [
            {"widgets": [{"widget_type": "BREADCRUMB",
                          "data": {"parent_items": [{"title": c} for c in crumbs]}}]},
            {"widgets": [
                {"widget_type": "LEGEND_TITLE_ROW", "data": {"title": title}},
                {"widget_type": "GROUP_INFO_ROW", "data": {
                    "items": [{"title": k, "value": v} for k, v in list(fields.items())[:3]]
                }},
                *[
                    {"widget_type": "UNEXPANDABLE_ROW", "data": {"title": k, "value": v}}
                    for k, v in list(fields.items())[3:]
                ],
            ]},
        ]
    }


PEUGEOT = _detail(
    {
        "کارکرد": "۳۰۰۰۰۰",
        "مدل (سال تولید)": "۱۳۹۰ - ۲۰۱۱",
        "رنگ": "سفید",
        "برند و مدل": "پژو 206 تیپ ۵",
        "گیربکس": "دنده‌ای",
        "نوع سوخت": "بنزین",
        "قیمت پایه": "‏۹۵۵,۰۰۰,۰۰۰ تومان",
        "مهلت بیمهٔ شخص ثالث": "۱۰ ماه",
        "مالکیت خودرو": "مالک خودرو هستم",
    },
    ["وسایل نقلیه", "خودرو", "خودرو سواری و وانت", "پژو", "206", "تیپ ۵"],
    "۲۰۶ تیپ ۵ مدل ۹۰",
)


class TestYear:
    def test_dual_calendar(self):
        """Divar shows both: '۱۳۹۰ - ۲۰۱۱'."""
        assert parse_divar_year("۱۳۹۰ - ۲۰۱۱") == (2011, 1390, "jalali")

    def test_jalali_only_is_converted(self):
        gregorian, displayed, calendar = parse_divar_year("۱۳۹۵")
        assert (gregorian, displayed, calendar) == (2016, 1395, "jalali")

    def test_gregorian_only(self):
        assert parse_divar_year("۲۰۱۸") == (2018, 2018, "gregorian")

    def test_missing(self):
        assert parse_divar_year(None) == (None, None, None)
        assert parse_divar_year("نامشخص") == (None, None, None)


class TestExtraction:
    def test_fields_from_both_widget_shapes(self):
        fields = extract_fields(PEUGEOT)
        assert fields["کارکرد"] == "۳۰۰۰۰۰"
        assert fields["گیربکس"] == "دنده‌ای"

    def test_breadcrumb(self):
        assert extract_breadcrumb(PEUGEOT)[3:6] == ["پژو", "206", "تیپ ۵"]


class TestBodyInference:
    """Divar usually omits وضعیت بدنه; sellers state it in prose instead."""

    def test_clean_body_from_title(self):
        assert infer_body_status("لیفان 820 بدون رنگ") == ("بدون رنگ", 100)

    def test_hyphenated_variant(self):
        assert infer_body_status("تیگو ۷ بی‌رنگ") == ("بدون رنگ", 100)

    def test_accident_wins_over_optimistic_wording(self):
        """A seller writing 'بدون رنگ' next to 'دور رنگ' must not score clean."""
        assert infer_body_status("بدون رنگ ولی گلگیر دور رنگ") == ("دور رنگ", 28)

    def test_nothing_to_infer(self):
        assert infer_body_status("ماشین سالم و تمیز") == (None, None)


class TestNormalize:
    def _listing(self):
        raw = {
            "_id": "gaWO-AIn",
            "_source": "divar",
            "list": {
                "title": "۲۰۶ تیپ ۵ مدل ۹۰",
                "image_url": "https://example.invalid/a.webp",
                "image_count": 10,
                "action": {"payload": {"web_info": {
                    "city_persian": "تهران", "district_persian": "قنات‌کوثر"
                }}},
            },
            "detail": PEUGEOT,
        }
        return DivarSource().normalize(raw)

    def test_core_fields(self):
        listing = self._listing()
        assert listing is not None
        assert listing.code == "divar_gaWO-AIn"
        assert listing.source == "divar"
        assert listing.brand_fa == "پژو"
        assert listing.model_fa == "206"
        assert listing.year == 2011
        assert listing.year_display == 1390
        assert listing.mileage_km == 300_000
        assert listing.price_toman == 955_000_000
        assert listing.is_negotiable is False

    def test_persian_vocabulary_is_mapped_to_bama_wording(self):
        """Downstream code and the UI speak Bama's terms."""
        listing = self._listing()
        assert listing.transmission == "دنده ای"
        assert listing.fuel == "بنزینی"

    def test_owner_is_a_private_seller(self):
        assert self._listing().seller == "شخصی"

    def test_insurance_months_captured(self):
        assert self._listing().insurance_months == 10

    def test_location(self):
        listing = self._listing()
        assert listing.city == "تهران"
        assert listing.location == "قنات‌کوثر"

    def test_rejects_record_without_brand(self):
        raw = {"_id": "x", "detail": _detail({}, ["وسایل نقلیه"], "بدون برند"), "list": {}}
        assert DivarSource().normalize(raw) is None


class TestCanonicalisation:
    """Divar has no Latin slugs; Bama teaches them."""

    def test_divar_listing_joins_bama_cohort(self):
        bama_rows = [
            {"brand": "peugeot", "brand_fa": "پژو", "model": "206ir",
             "title": "پژو، 206", "model_fa": "206"},
        ]
        resolver = BrandResolver().learn(bama_rows)

        listing = TestNormalize()._listing()
        assert listing.brand is None  # Divar gave us Persian only
        resolver.resolve(listing)
        assert listing.brand == "peugeot"
        assert listing.model == "206ir"

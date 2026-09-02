"""Tests for the parsing layer.

These cover the cases that actually bit during development — the mixed calendar,
the substring trap in mileage parsing, and negotiable prices — rather than
restating the happy path.
"""

from app.normalize import (
    body_status_grade,
    normalize_ad,
    parse_mileage,
    parse_price,
    parse_year,
    seller_type,
)


class TestMileage:
    def test_persian_zero(self):
        assert parse_mileage("صفر کیلومتر") == 0

    def test_comma_formatted(self):
        assert parse_mileage("240,000 km") == 240_000

    def test_zero_km_is_not_a_substring_match(self):
        # Regression: '240,000 km' contains the literal '0 km'. A naive
        # substring check for a zero-mileage marker returned 0 here.
        assert parse_mileage("1,000 km") == 1_000
        assert parse_mileage("0 km") == 0

    def test_persian_digits(self):
        assert parse_mileage("۱۲۳٬۴۵۶ km") == 123_456

    def test_missing(self):
        assert parse_mileage(None) is None
        assert parse_mileage("") is None


class TestYear:
    def test_jalali_converts_to_gregorian(self):
        # 1391 is advertised as a 2012 model.
        assert parse_year("1391") == (2012, "jalali")

    def test_gregorian_passes_through(self):
        assert parse_year("2012") == (2012, "gregorian")

    def test_recent_jalali(self):
        assert parse_year("1405") == (2026, "jalali")

    def test_missing(self):
        assert parse_year(None) == (None, None)


class TestPrice:
    def test_lumpsum(self):
        assert parse_price("3,890,000,000", "lumpsum") == (3_890_000_000, False)

    def test_negotiable_is_none_not_zero(self):
        # A zero here would poison the regression target.
        assert parse_price("0", "negotiable") == (None, True)

    def test_zero_price_without_type(self):
        assert parse_price("0", "lumpsum") == (None, True)


class TestBodyStatus:
    def test_clean_body_scores_highest(self):
        assert body_status_grade("بدون رنگ") == 100

    def test_full_respray_scores_low(self):
        assert body_status_grade("دور رنگ") < 40

    def test_ordering_is_sensible(self):
        assert (
            body_status_grade("بدون رنگ")
            > body_status_grade("یک لکه رنگ")
            > body_status_grade("چند لکه رنگ")
            > body_status_grade("دور رنگ")
        )

    def test_unknown_phrase_gets_neutral_grade(self):
        assert body_status_grade("یک چیز عجیب") == 60

    def test_missing(self):
        assert body_status_grade(None) == 60


class TestSeller:
    def test_no_dealer_means_private(self):
        assert seller_type(None) == "شخصی"

    def test_dealer_type_preserved(self):
        assert seller_type({"type": "نمایندگی"}) == "نمایندگی"


class TestNormalizeAd:
    def _ad(self, **overrides):
        detail = {
            "code": "abc123",
            "url": "/car/detail-abc123",
            "title": "مزدا، 3 نیو",
            "brand": "mazda",
            "model": "3sedan",
            "trim_en": "2.0ltype4",
            "year": "1391",
            "mileage": "240,000 km",
            "body_status": "یک لکه رنگ",
            "authenticated": False,
        }
        detail.update(overrides.pop("detail", {}))
        ad = {
            "detail": detail,
            "specs": {"volume": "2 لیتر", "power": "147 اسب‌بخار"},
            "price": {"price": "3,890,000,000", "type": "lumpsum"},
            "dealer": {"name": "آرکان خودرو", "score": 4.1, "type": "نمایشگاه"},
        }
        ad.update(overrides)
        return ad

    def test_maps_core_fields(self):
        listing = normalize_ad(self._ad())
        assert listing is not None
        # Codes are namespaced by source now that more than one site is crawled.
        assert listing.code == "bama_abc123"
        assert listing.source == "bama"
        assert listing.year == 2012
        assert listing.year_display == 1391
        assert listing.age == 14
        assert listing.mileage_km == 240_000
        assert listing.price_toman == 3_890_000_000
        assert listing.is_negotiable is False
        assert listing.engine_volume_l == 2.0
        assert listing.power_hp == 147.0
        assert listing.seller == "نمایشگاه"

    def test_negotiable_listing_has_no_price(self):
        listing = normalize_ad(self._ad(price={"price": "0", "type": "negotiable"}))
        assert listing.price_toman is None
        assert listing.is_negotiable is True

    def test_private_seller_when_no_dealer(self):
        ad = self._ad()
        ad["dealer"] = None
        assert normalize_ad(ad).seller == "شخصی"

    def test_rejects_ad_without_code(self):
        assert normalize_ad({"detail": {}}) is None

    def test_cohort_keys(self):
        listing = normalize_ad(self._ad())
        assert listing.cohort_key == "mazda|3sedan|2.0ltype4|2012"
        assert listing.model_key == "mazda|3sedan|2012"

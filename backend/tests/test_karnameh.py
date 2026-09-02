"""Tests for the Karnameh adapter.

Karnameh publishes typed records rather than display strings, so there is very
little parsing to get wrong. The risk lives elsewhere: the build id the JSON
route is addressed by, the page-1 special case, and the fields that are not what
they look like. The fixture mirrors a payload captured from the live route.
"""

import asyncio

import pytest

from app.crawl.karnameh import (
    BUILD_ID_RE,
    KarnamehSource,
    car_posts,
    data_url,
    page_count,
)

PARS = {
    "concierge_sale_token": "4b60f9fb-022b-4a45-877b-37c50c5d1bf3",
    "title": "پژو پارس مدل 1402",
    "year": 1402,
    "usage": 32500,
    "price": 1855000000,
    "prepayment_amount": 1166795000,
    "is_leasing_available": True,
    "has_inspection": False,
    "is_authentic": False,
    "is_professional": False,
    "city": 1,
    "city_name_fa": "تهران",
    "color": "سفید",
    "gearbox": "manual",
    "gearbox_name_fa": "دنده‌ای",
    "brand_name_en": "Peugeot", "brand_name_fa": "پژو",
    "model_name_en": "Pars", "model_name_fa": "پارس",
    "type_name_en": "LX-TU5", "type_name_fa": "LX TU5",
    "image": "https://cdn.karnameh.com/pictures/car-posts/abc",
    "image_count": 4,
}

PAYLOAD = {"pageProps": {"firstPage": {"car_posts": [PARS], "total": 346, "pages": 18}}}


def test_page_one_carries_no_query_string():
    """`?page=1` returns a redirect stub with no posts — the one that bites."""
    assert data_url("BUILD", 1) == "https://karnameh.com/_next/data/BUILD/buy-used-cars.json"
    assert data_url("BUILD", 2).endswith("buy-used-cars.json?page=2")


def test_build_id_is_recoverable_from_the_page():
    html = 'x<script>{"buildId":"eaWs_cPn9BCcAfgHK_AKc","assetPrefix":""}</script>'
    assert BUILD_ID_RE.search(html).group(1) == "eaWs_cPn9BCcAfgHK_AKc"


def test_car_posts_and_page_count_survive_a_redirect_stub():
    """Past the last page the route serves `__N_REDIRECT` instead of a list."""
    stub = {"pageProps": {"__N_REDIRECT": "/buy-used-cars", "__N_REDIRECT_STATUS": 308}}
    assert car_posts(stub) == []
    assert page_count(stub) == 0
    assert page_count(PAYLOAD) == 18


def test_normalize_reads_the_typed_record():
    listing = KarnamehSource.__new__(KarnamehSource).normalize(
        {"_id": PARS["concierge_sale_token"], "post": PARS}
    )
    assert listing is not None
    assert listing.code == "karnameh_4b60f9fb-022b-4a45-877b-37c50c5d1bf3"
    assert listing.url == "https://karnameh.com/used-cars/4b60f9fb-022b-4a45-877b-37c50c5d1bf3"
    assert (listing.year, listing.year_display, listing.year_calendar) == (2023, 1402, "jalali")
    assert listing.mileage_km == 32500
    assert (listing.price_toman, listing.is_negotiable) == (1855000000, False)
    assert listing.transmission == "دنده ای"
    assert listing.city == "تهران"


def test_normalize_fills_both_halves_of_the_brand():
    """Karnameh needs no resolution and teaches the mapping instead — this is
    the whole reason a 346-listing source is worth having."""
    listing = KarnamehSource.__new__(KarnamehSource).normalize({"_id": "t", "post": PARS})
    assert (listing.brand, listing.brand_fa) == ("peugeot", "پژو")
    assert (listing.model, listing.model_fa) == ("pars", "پارس")
    assert (listing.trim_en, listing.trim) == ("lx-tu5", "LX TU5")


def test_normalize_never_records_the_prepayment_as_a_price():
    """`prepayment_amount` is a financing quote Karnameh computes for every car,
    not a down-payment a seller advertised — it must not reach price_toman."""
    listing = KarnamehSource.__new__(KarnamehSource).normalize({"_id": "t", "post": PARS})
    assert listing.price_toman == PARS["price"]
    assert str(PARS["prepayment_amount"]) not in (listing.description or "")


def test_normalize_defaults_the_body_grade_rather_than_scoring_zero():
    """Karnameh states no paint condition. A None grade would read as `or 0` in
    the paint filter and drop every Karnameh car as if it were a wreck."""
    listing = KarnamehSource.__new__(KarnamehSource).normalize({"_id": "t", "post": PARS})
    assert listing.body_status is None
    assert listing.body_grade == 60


def test_normalize_handles_an_import_listed_in_gregorian():
    camry = dict(PARS, year=2007, brand_name_en="Toyota", brand_name_fa="تویوتا")
    listing = KarnamehSource.__new__(KarnamehSource).normalize({"_id": "t", "post": camry})
    assert (listing.year, listing.year_calendar) == (2007, "gregorian")


def test_normalize_rejects_a_post_with_no_token():
    assert KarnamehSource.__new__(KarnamehSource).normalize({"post": {"price": 1}}) is None


def test_build_id_failure_is_loud():
    """A silent zero-record crawl is far more expensive to notice than a crash."""
    class Fake(KarnamehSource):
        def __init__(self, html: str):
            class Client:
                async def get(self, *_args, **_kwargs):
                    return type("Response", (), {"text": html})()
            self._client = Client()

    with pytest.raises(RuntimeError, match="no buildId"):
        asyncio.run(Fake("<html>no build id here</html>").build_id())
    # ...and finds it when the page is intact.
    assert asyncio.run(Fake('{"buildId":"abc123"}').build_id()) == "abc123"

"""Tests for the explicit sort orders.

Ranking by value x health x fit is what the product is for, and stays the
default. These orders exist for browsing by feature, where "best overall" is not
the question being asked.

The behaviour worth pinning is what happens to cars with nothing to sort on: a
listing with no recorded mileage is not the lowest-mileage car in the corpus,
and a car whose seller hid the price is not priceless — it sorts on our
estimate, which is the only reason estimating it was worth doing.
"""

import pytest

from app.query import Intent
from app.rank import rank
from tests.test_features import car


def codes(results) -> list[str]:
    return [r["code"] for r in results]


@pytest.fixture
def rows():
    return [
        car("cheap", price_toman=300_000_000, fair_price=300_000_000,
            year=2010, mileage_km=250_000, price_delta_pct=0.0),
        car("mid", price_toman=1_000_000_000, fair_price=1_200_000_000,
            year=2018, mileage_km=100_000, price_delta_pct=-16.7),
        car("dear", price_toman=5_000_000_000, fair_price=5_000_000_000,
            year=2023, mileage_km=20_000, price_delta_pct=0.0),
    ]


class TestSortOrders:
    def test_default_is_the_capot_ranking(self, rows):
        """No sort argument must not change what search already returned."""
        assert codes(rank(rows, Intent())) == codes(rank(rows, Intent(), sort="rank"))

    def test_price_ascending(self, rows):
        assert codes(rank(rows, Intent(), sort="price_asc")) == ["cheap", "mid", "dear"]

    def test_price_descending(self, rows):
        assert codes(rank(rows, Intent(), sort="price_desc")) == ["dear", "mid", "cheap"]

    def test_newest_first(self, rows):
        assert codes(rank(rows, Intent(), sort="year_desc")) == ["dear", "mid", "cheap"]

    def test_lowest_mileage_first(self, rows):
        assert codes(rank(rows, Intent(), sort="mileage_asc")) == ["dear", "mid", "cheap"]

    def test_biggest_discount_first(self, rows):
        assert codes(rank(rows, Intent(), sort="discount_desc"))[0] == "mid"

    def test_unknown_sort_falls_back_to_the_ranking(self, rows):
        assert codes(rank(rows, Intent(), sort="sideways")) == codes(rank(rows, Intent()))


class TestSortEdgeCases:
    def test_hidden_price_sorts_on_its_estimate(self):
        """Not at the bottom — pricing it was the entire point."""
        rows = [
            car("published", price_toman=2_000_000_000, fair_price=2_000_000_000),
            car("hidden", price_toman=None, is_negotiable=True, fair_price=500_000_000),
        ]
        assert codes(rank(rows, Intent(), sort="price_asc")) == ["hidden", "published"]

    def test_missing_values_sort_last_not_first(self):
        """A car with no odometer reading is not the lowest-mileage car."""
        rows = [
            car("unknown", mileage_km=None),
            car("known", mileage_km=150_000),
        ]
        assert codes(rank(rows, Intent(), sort="mileage_asc")) == ["known", "unknown"]

    def test_every_result_keeps_its_reasons_whatever_the_order(self, rows):
        """Sorting reorders the cards; it must not strip what they explain."""
        for result in rank(rows, Intent(), sort="price_asc"):
            assert "scores" in result and "health" in result
            assert result["scores"]["value"] is not None

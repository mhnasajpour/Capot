"""Tests for paging the ranked result set.

A page is a window onto one globally ordered list, and that is the whole of what
these tests protect. The failure they exist to catch is subtle: if paging were
applied before or during ranking — slicing the candidates and *then* scoring
them — every page would be the best of its own slice, so page 2 would show cars
that outrank half of page 1 and the reader would never see the same list twice.

So the property under test is tiling: concatenating the pages must reproduce
`rank_all` exactly, in order, with nothing repeated and nothing dropped.
"""

import pytest

from app.query import Intent
from app.rank import rank, rank_all
from tests.test_features import car


def codes(results) -> list[str]:
    return [r["code"] for r in results]


@pytest.fixture
def rows():
    """Ten distinguishable cars — more than one page at the sizes used here."""
    return [
        car(
            f"car_{i:02d}",
            price_toman=(i + 1) * 100_000_000,
            fair_price=(i + 1) * 100_000_000,
            year=2010 + i,
            mileage_km=(10 - i) * 20_000,
            price_delta_pct=float(i),
        )
        for i in range(10)
    ]


class TestPaging:
    def test_pages_tile_the_full_ranking(self, rows):
        """Every page in order, concatenated, is the whole ranked list."""
        everything = codes(rank_all(rows, Intent()))
        paged: list[str] = []
        for offset in range(0, len(rows), 3):
            paged += codes(rank(rows, Intent(), limit=3, offset=offset))
        assert paged == everything

    def test_pages_do_not_overlap(self, rows):
        first = codes(rank(rows, Intent(), limit=4, offset=0))
        second = codes(rank(rows, Intent(), limit=4, offset=4))
        assert len(first) == len(second) == 4
        assert not set(first) & set(second)

    def test_offset_does_not_reorder(self, rows):
        """The second page is the ranking's 5th-8th cars, not its own top four.

        This is the regression that matters: rank the slice instead of slicing
        the ranking and this assertion is the one that fails.
        """
        everything = codes(rank_all(rows, Intent()))
        assert codes(rank(rows, Intent(), limit=4, offset=4)) == everything[4:8]

    def test_last_page_is_short_not_padded(self, rows):
        assert len(codes(rank(rows, Intent(), limit=4, offset=8))) == 2

    def test_offset_past_the_end_is_empty(self, rows):
        """Not the last page, and not the first — an out-of-range page has
        nothing on it, and the API says so rather than quietly moving you."""
        assert rank(rows, Intent(), limit=4, offset=40) == []

    def test_default_call_is_unchanged(self, rows):
        """Paging is additive: callers that never pass an offset see page 1."""
        assert codes(rank(rows, Intent(), limit=4)) == codes(
            rank(rows, Intent(), limit=4, offset=0)
        )

    def test_rank_all_returns_everything(self, rows):
        assert len(rank_all(rows, Intent())) == len(rows)

    def test_no_candidates_pages_to_nothing(self):
        assert rank_all([], Intent()) == []
        assert rank([], Intent(), limit=4, offset=4) == []


class TestPagingUnderExplicitSort:
    """An explicit sort reorders the whole set before it is cut into pages, so
    the cheapest car is on page 1 whatever the page size."""

    def test_price_ordering_survives_paging(self, rows):
        everything = codes(rank_all(rows, Intent(), sort="price_asc"))
        paged: list[str] = []
        for offset in range(0, len(rows), 3):
            paged += codes(rank(rows, Intent(), limit=3, offset=offset, sort="price_asc"))
        assert paged == everything

    def test_first_page_holds_the_cheapest(self, rows):
        page = codes(rank(rows, Intent(), limit=3, sort="price_asc"))
        assert page == ["car_00", "car_01", "car_02"]

    def test_last_page_holds_the_dearest(self, rows):
        page = codes(rank(rows, Intent(), limit=3, offset=9, sort="price_asc"))
        assert page == ["car_09"]

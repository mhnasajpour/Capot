"""Tests for appraising a car that is not in the corpus.

Three behaviours carry the weight here, and all three are about refusing to
invent a number rather than about the number itself:

  * **An unidentified car gets no price.** Pricing a name we cannot resolve is
    the same failure as the old search answering «سراتو» with a BMW, except a
    valuation is what someone is about to sell a real car on.
  * **A stated field beats a parsed one.** The user can see a form field and
    cannot see a parser, so «مدل ۹۵» in prose must lose to 1396 in the form.
  * **The band widens as confidence falls.** A thin cohort must visibly carry a
    weaker number, which is the promise `pricing.confidence_for` exists to keep.
"""

import pytest

from app.appraise import (
    FALLBACK_METRICS,
    IMPUTED_FEATURES,
    CarInput,
    appraise,
    cohort_counts,
    corpus_modes,
    impute,
    index_by_model,
    merge,
    parse_description,
    price_band,
)
from app.lexicon import build as build_lexicon


@pytest.fixture(scope="module")
def lex():
    """A lexicon over a handful of rows, built exactly as the server builds it."""
    return build_lexicon([
        {"brand": "peugeot", "brand_fa": "پژو", "model": "206", "title": "پژو، ۲۰۶"},
        {"brand": "peugeot", "brand_fa": "پژو", "model": "pars", "title": "پژو، پارس"},
        {"brand": "kia", "brand_fa": "کیا", "model": "cerato", "title": "کیا، سراتو"},
    ])


def listing(code, **extra) -> dict:
    """One corpus row, priced unless a test says otherwise."""
    row = {
        "code": code, "url": f"https://example.test/{code}", "title": "پژو، ۲۰۶",
        "brand": "peugeot", "brand_fa": "پژو", "model": "206", "model_fa": "۲۰۶",
        "trim": None, "trim_en": None, "year": 2016, "year_display": 1395,
        "year_calendar": "jalali", "age": 10, "mileage_km": 120_000,
        "price_toman": 500_000_000, "is_negotiable": False, "price_flag": "ok",
        "fair_price": 500_000_000, "price_delta_pct": 0.0, "confidence": 0.6,
        "body_status": "بدون رنگ", "body_grade": 100, "body_type": "hatchback",
        "body_type_fa": "هاچبک", "transmission": "دنده ای", "fuel": "بنزینی",
        "body_color": "سفید", "seller": "شخصی", "dealer_name": None,
        "dealer_score": None, "city": "تهران", "source": "divar",
        "authenticated": False, "image_count": 4, "life_styles": [],
        "engine_volume_l": 1.4, "consumption_l100": None, "power_hp": None,
        "description": None, "duplicate_of": [], "insurance_months": None,
    }
    row.update(extra)
    return row


class StubPipe:
    """Stands in for the trained regressor.

    Returns log(price), because that is what the real pipeline is fitted on and
    what `appraise` exponentiates. Fixed, so a test asserts on the assembly
    around the model rather than on the model's own accuracy — which
    `pricing.train` measures and reports for itself.
    """

    def __init__(self, price: float = 500_000_000.0):
        import math

        self.value = math.log(price)

    def predict(self, frame):
        import numpy as np

        return np.full(len(frame), self.value)


@pytest.fixture
def corpus():
    return [listing(f"divar_{i}") for i in range(12)]


@pytest.fixture
def scored(corpus):
    """The corpus-derived arguments `appraise` needs, built as `main` builds them."""
    by_model_year, by_model_counts, by_brand_counts = cohort_counts(corpus)
    return {
        "by_model_year": by_model_year,
        "by_model_counts": by_model_counts,
        "by_brand_counts": by_brand_counts,
        "by_model": index_by_model(corpus),
        "metrics": dict(FALLBACK_METRICS),
        "modes": corpus_modes(corpus),
    }


# ------------------------------------------------------------------- parsing


class TestParseDescription:
    def test_reads_a_whole_car_out_of_persian_prose(self, lex):
        car = parse_description(
            "پژو ۲۰۶ مدل ۱۳۹۵، کارکرد ۱۲۰ هزار کیلومتر، بدون رنگ", lex
        )
        assert car.brand == "peugeot"
        assert car.model == "206"
        assert car.year == 2016
        assert car.mileage_km == 120_000
        assert car.body_status == "بدون رنگ"

    def test_jalali_and_gregorian_years_land_on_the_same_car(self, lex):
        jalali = parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex)
        gregorian = parse_description("پژو ۲۰۶ مدل 2016", lex)
        assert jalali.year == gregorian.year == 2016

    def test_worst_paint_phrase_wins(self, lex):
        """A seller's optimistic wording must not inflate the grade."""
        car = parse_description("پژو ۲۰۶ مدل ۱۳۹۵ بدون رنگ ولی گلگیر دور رنگ", lex)
        assert car.body_status == "دور رنگ"

    def test_gearbox_and_fuel(self, lex):
        car = parse_description("کیا سراتو مدل ۲۰۱۸ اتوماتیک دوگانه", lex)
        assert car.brand == "kia"
        assert car.model == "cerato"
        assert car.transmission == "اتوماتیک"
        assert car.fuel == "دوگانه سوز"

    def test_empty_text_parses_to_an_empty_car(self, lex):
        assert parse_description("", lex) == CarInput()

    def test_ambiguous_slug_resolves_to_the_cohort_we_actually_stock(self):
        """«۲۰۶» is both `206ir` and `206`; the corpus decides which.

        `lexicon.build` registers the assembly suffix as an alias of the bare
        name, so one Persian word resolves to two slugs. Search filters on both
        at once and never has to choose; a price model takes one `model` value,
        and choosing the wrong one prices the car against 27 comparables instead
        of 1,197.
        """
        lex = build_lexicon([
            {"brand": "peugeot", "brand_fa": "پژو", "model": "206ir", "title": "پژو، ۲۰۶"},
            {"brand": "peugeot", "brand_fa": "پژو", "model": "206", "title": "پژو، ۲۰۶"},
        ])
        support = {("peugeot", "206ir"): 1197, ("peugeot", "206"): 27}
        assert parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex, support).model == "206ir"

        # Reverse the corpus and the answer follows it, rather than the spelling.
        flipped = {("peugeot", "206ir"): 5, ("peugeot", "206"): 900}
        assert parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex, flipped).model == "206"

    def test_resolution_is_deterministic_without_corpus_counts(self, lex):
        """No support table (a unit test, a cold corpus) must still not flap."""
        first = parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex)
        assert all(
            parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex) == first for _ in range(5)
        )

    def test_description_is_kept_for_the_risk_scanner(self, lex):
        text = "پژو ۲۰۶ مدل ۱۳۹۵ موتور تعویض شده"
        assert parse_description(text, lex).description == text


class TestMerge:
    def test_stated_field_beats_parsed_one(self, lex):
        parsed = parse_description("پژو ۲۰۶ مدل ۱۳۹۵، کارکرد ۱۲۰ هزار", lex)
        car = merge(parsed, CarInput(year=2017, mileage_km=300_000))
        assert car.year == 2017
        assert car.mileage_km == 300_000
        # Untouched fields still come from the prose.
        assert car.brand == "peugeot"
        assert car.model == "206"

    def test_blank_form_field_does_not_erase_a_parsed_one(self, lex):
        parsed = parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex)
        assert merge(parsed, CarInput()).year == 2016


# ------------------------------------------------------------------ refusals


class TestRefusals:
    def test_unknown_car_gets_no_price(self, lex, scored):
        car = parse_description("یخچال فریزر", lex)
        result = appraise(car, StubPipe(), **scored)
        assert result["status"] == "unknown_car"
        assert result["price"] is None

    def test_a_brand_with_no_model_is_still_priced(self, lex, scored):
        """«پراید» alone is a real car, and 2,169 priced rows carry no model slug.

        Refusing these was wrong: the model is trained on exactly this shape.
        What a missing model costs is cohort depth, which confidence reports.
        """
        car = parse_description("پژو مدل ۱۳۹۵", lex)
        result = appraise(car, StubPipe(), **scored)
        assert result["status"] == "ok"
        assert result["price"] is not None
        # No model means no model-and-year cohort, so it scores at the bottom rung.
        assert result["price"]["cohort_level"] == "global"

    def test_missing_year_gets_no_price(self, lex, scored):
        car = parse_description("پژو ۲۰۶", lex)
        result = appraise(car, StubPipe(), **scored)
        assert result["status"] == "need_year"
        assert result["price"] is None

    def test_zero_kilometre_car_is_priced_but_warned_about(self, scored):
        """New cars are out of the corpus on purpose — say so, don't stay quiet."""
        car = CarInput(brand="peugeot", model="206", year=2026, mileage_km=0)
        result = appraise(car, StubPipe(), **scored)
        assert result["status"] == "ok"
        assert result["price"] is not None
        assert "brand_new" in result["warnings"]

    def test_unstated_mileage_is_warned_about(self, scored):
        car = CarInput(brand="peugeot", model="206", year=2016)
        result = appraise(car, StubPipe(), **scored)
        assert "no_mileage" in result["warnings"]


# ------------------------------------------------------------------ the price


class TestAppraisal:
    def test_prices_a_known_car(self, lex, scored):
        car = parse_description("پژو ۲۰۶ مدل ۱۳۹۵ کارکرد ۱۲۰ هزار بدون رنگ", lex)
        result = appraise(car, StubPipe(500_000_000), **scored)

        assert result["status"] == "ok"
        assert result["price"]["fair_price"] == 500_000_000
        assert result["price"]["low"] < 500_000_000 < result["price"]["high"]
        assert 0 < result["price"]["confidence"] <= 1

    def test_comparable_depth_comes_from_the_corpus(self, lex, scored):
        car = parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex)
        result = appraise(car, StubPipe(), **scored)
        # Twelve priced 2016 Peugeot 206s are in the fixture corpus.
        assert result["price"]["n_comparables"] == 12
        assert result["price"]["cohort_level"] == "model"

    def test_a_car_we_stock_none_of_scores_as_global(self, scored):
        car = CarInput(brand="kia", model="cerato", year=2018)
        result = appraise(car, StubPipe(), **scored)
        assert result["price"]["cohort_level"] == "global"
        assert result["price"]["n_comparables"] == 0
        assert "no_comparables" in result["warnings"]

    def test_returns_live_ads_for_cars_like_it(self, lex, scored):
        car = parse_description("پژو ۲۰۶ مدل ۱۳۹۵", lex)
        result = appraise(car, StubPipe(), **scored)
        assert len(result["matches"]) == 12
        assert result["match_level"] == "model_year"
        # The payload is a result card, unchanged from what the grid renders.
        assert {"code", "price", "health", "scores"} <= set(result["matches"][0])

    def test_only_priced_listings_count_as_comparables(self):
        """A cohort of negotiable ads supports nothing, at any level."""
        rows = [listing(f"divar_{i}", price_toman=None, is_negotiable=True) for i in range(9)]
        assert cohort_counts(rows) == ({}, {}, {})

    def test_model_less_rows_still_count_towards_their_brand(self):
        """The rows a model-keyed tally cannot see are 2,169 of the real corpus."""
        rows = [listing(f"divar_{i}", model=None) for i in range(7)]
        by_model_year, by_model_counts, by_brand_counts = cohort_counts(rows)
        assert by_model_year == {} and by_model_counts == {}
        assert by_brand_counts == {"peugeot": 7}


class TestImputation:
    """A blank categorical is not a neutral value, and must never reach the model.

    `pricing.build_frame` turns an absent categorical into the string "unknown",
    which the encoder has almost never seen — the crawl fills these fields on
    nearly every row. Measured on the real corpus, `transmission` is absent on
    1.1% of priced listings and those have a median price of 2.0B against 1.44B
    for the rest, so "unknown" reads as *an expensive car*, not as *no
    information*. A 2011 Pride 131 with the gearbox left blank was priced at
    1.92B against a corpus median of 485M.
    """

    def test_blank_categoricals_are_filled_from_the_cohort(self, corpus):
        car = CarInput(brand="peugeot", model="206", year=2016)
        filled, assumed = impute(car, index_by_model(corpus), corpus_modes(corpus))

        for field in IMPUTED_FEATURES:
            assert getattr(filled, field), f"{field} left blank"
            assert field in assumed
        # Taken from cars of the same model, not from thin air.
        assert filled.transmission == "دنده ای"
        assert filled.fuel == "بنزینی"
        assert filled.city == "تهران"

    def test_what_the_user_stated_is_never_overwritten(self, corpus):
        car = CarInput(brand="peugeot", model="206", year=2016, transmission="اتوماتیک")
        filled, assumed = impute(car, index_by_model(corpus), corpus_modes(corpus))
        assert filled.transmission == "اتوماتیک"
        assert "transmission" not in assumed

    def test_an_unknown_brand_falls_back_to_the_corpus(self, corpus):
        car = CarInput(brand="lamborghini", model="urus", year=2020)
        filled, _assumed = impute(car, index_by_model(corpus), corpus_modes(corpus))
        assert filled.transmission == "دنده ای"

    def test_assumptions_are_reported_not_applied_silently(self, scored):
        """A number that moves on an assumption must say which one."""
        car = CarInput(brand="peugeot", model="206", year=2016, mileage_km=120_000)
        result = appraise(car, StubPipe(), **scored)
        assert set(result["assumed"]) == set(IMPUTED_FEATURES)
        # And the echoed input shows the filled car, so the form can display it.
        assert result["input"]["transmission"] == "دنده ای"


class TestHealth:
    def test_a_disclosed_risk_lowers_the_score(self, scored):
        clean = CarInput(
            brand="peugeot", model="206", year=2016, mileage_km=120_000,
            body_status="بدون رنگ", description="پژو ۲۰۶ سالم",
        )
        risky = CarInput(
            brand="peugeot", model="206", year=2016, mileage_km=120_000,
            body_status="بدون رنگ", description="پژو ۲۰۶ موتور تعویض شده",
        )
        clean_result = appraise(clean, StubPipe(), **scored)
        risky_result = appraise(risky, StubPipe(), **scored)

        assert risky_result["health"]["score"] < clean_result["health"]["score"]
        assert any(
            factor["key"] == "text_risk:engine_replaced"
            for factor in risky_result["health"]["factors"]
        )

    def test_paint_condition_moves_the_score(self, scored):
        def score_for(status: str) -> int:
            car = CarInput(brand="peugeot", model="206", year=2016,
                           mileage_km=120_000, body_status=status)
            return appraise(car, StubPipe(), **scored)["health"]["score"]

        assert score_for("بدون رنگ") > score_for("دور رنگ")


class TestPriceBand:
    def test_band_brackets_the_estimate(self):
        low, high = price_band(1_000_000_000, 0.6, FALLBACK_METRICS)
        assert low < 1_000_000_000 < high

    def test_lower_confidence_widens_the_band(self):
        confident = price_band(1_000_000_000, 0.95, FALLBACK_METRICS)
        thin = price_band(1_000_000_000, 0.1, FALLBACK_METRICS)
        assert (thin[1] - thin[0]) > (confident[1] - confident[0])

    def test_full_confidence_quotes_the_models_median_error(self):
        low, high = price_band(1_000_000_000, 1.0, FALLBACK_METRICS)
        assert high - 1_000_000_000 == pytest.approx(
            1_000_000_000 * FALLBACK_METRICS["median_ape"], rel=0.01
        )
        assert 1_000_000_000 - low == pytest.approx(
            1_000_000_000 * FALLBACK_METRICS["median_ape"], rel=0.01
        )

    def test_no_confidence_quotes_the_models_mean_error(self):
        _low, high = price_band(1_000_000_000, 0.0, FALLBACK_METRICS)
        assert high - 1_000_000_000 == pytest.approx(
            1_000_000_000 * FALLBACK_METRICS["mape"], rel=0.01
        )

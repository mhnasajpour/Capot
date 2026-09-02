"""Tests for the filterable feature catalogue and the explicit-filter path.

Two behaviours are worth protecting above the rest:

  * **A hidden-price car stays inside a price filter.** The whole product exists
    to make «توافقی» listings comparable; a price slider that drops them would
    undo it silently.
  * **Counts are leave-one-out.** Without that, selecting one brand reports every
    other brand as zero and multi-select becomes impossible to use.
"""

import pytest

from app.features import (
    FEATURES,
    MIN_CREDIBLE_PRICE,
    Filters,
    build_catalogue,
    count_features,
    effective_price,
    passes_features,
)
from app.query import Intent, parse_with_rules


def car(code, **extra) -> dict:
    row = {
        "code": code, "brand": "kia", "brand_fa": "کیا", "model": "cerato",
        "model_fa": "سراتو", "title": "کیا، سراتو", "trim": None,
        "body_type": "passenger_car", "body_type_fa": "سدان",
        "transmission": "اتوماتیک", "fuel": "بنزینی", "body_status": "بدون رنگ",
        "body_grade": 100, "body_color": "سفید", "city": "تهران",
        "seller": "شخصی", "source": "bama", "year": 2018, "age": 7,
        "mileage_km": 100_000, "price_toman": 1_000_000_000, "fair_price": 1_000_000_000,
        "price_delta_pct": 0.0, "price_flag": "ok", "is_negotiable": False,
        "engine_volume_l": 2.0, "consumption_l100": 8.0, "image_count": 5,
        "authenticated": False, "description": None, "confidence": 0.8,
    }
    row.update(extra)
    return row


def intent_from(**params) -> Intent:
    """The real path: parse the (empty) query, then overlay the selections."""
    return Filters.from_params(**params).apply_to(parse_with_rules(""))


class TestEffectivePrice:
    def test_published_price_wins(self):
        assert effective_price(car("a")) == (1_000_000_000, False)

    def test_negotiable_falls_back_to_estimate(self):
        row = car("a", price_toman=None, is_negotiable=True, fair_price=900_000_000)
        assert effective_price(row) == (900_000_000, True)

    def test_deposit_figure_is_not_a_price(self):
        row = car("a", price_toman=50_000_000, price_flag="deposit", fair_price=2_000_000_000)
        assert effective_price(row) == (2_000_000_000, True)

    def test_placeholder_price_is_distrusted(self):
        """A 1,000-toman Porsche is a placeholder, not the cheapest car we have.

        Its cohort is too thin for `pricing.implausible_vs_cohort` to judge it,
        so nothing upstream flags it — and sorting by price puts it first.
        """
        row = car("a", price_toman=1_000, fair_price=3_000_000_000)
        assert effective_price(row) == (3_000_000_000, True)

    def test_price_far_below_its_own_estimate_is_distrusted(self):
        row = car("a", price_toman=28_500_000, fair_price=3_405_000_000)
        assert effective_price(row) == (3_405_000_000, True)

    def test_genuinely_cheap_old_car_is_kept(self):
        """A crashed Pride at half its estimate is real and must survive."""
        row = car("a", price_toman=180_000_000, fair_price=358_000_000)
        assert effective_price(row) == (180_000_000, False)

    def test_no_price_and_no_estimate(self):
        assert effective_price(car("a", price_toman=None, fair_price=None)) == (None, False)


class TestFiltersParsing:
    def test_comma_separated_lists(self):
        f = Filters.from_params(brands="kia,hyundai", fuels="بنزینی,برقی")
        assert f.brands == ["kia", "hyundai"]
        assert f.fuels == ["بنزینی", "برقی"]

    def test_blank_params_select_nothing(self):
        assert Filters.from_params().is_empty

    def test_sort_is_not_a_constraint(self):
        assert Filters.from_params(sort="price_asc").is_empty

    def test_malformed_numbers_narrow_nothing(self):
        """A bad number in a URL must not 500 the search."""
        f = Filters.from_params(price_max="abc", year_min="")
        assert f.price_max is None and f.year_min is None

    def test_unknown_sort_falls_back_to_rank(self):
        assert Filters.from_params(sort="nonsense").sort == "rank"

    def test_unknown_paint_band_is_ignored(self):
        assert Filters.from_params(paint="glittery").paint is None


class TestPrecedence:
    """An explicit selection beats what the parser guessed from the prose."""

    def test_ticked_transmission_overrides_parsed_one(self):
        parsed = parse_with_rules("سراتو اتوماتیک")
        assert parsed.transmission == "اتوماتیک"

        merged = Filters.from_params(transmissions="دنده ای").apply_to(parsed)
        assert merged.transmissions == ["دنده ای"]
        # The parser's guess must not survive alongside the buyer's choice.
        assert merged.transmission is None
        assert passes_features(car("a", transmission="دنده ای"), merged)
        assert not passes_features(car("b", transmission="اتوماتیک"), merged)

    def test_ticked_price_overrides_parsed_budget(self):
        parsed = parse_with_rules("بودجه ۸۰۰ میلیون")
        assert parsed.budget_max == 800_000_000
        merged = Filters.from_params(price_max="2000000000").apply_to(parsed)
        assert merged.budget_max == 2_000_000_000

    def test_paint_band_supersedes_parsed_clean_body(self):
        parsed = parse_with_rules("ماشین بدون رنگ")
        assert parsed.require_clean_body is True
        merged = Filters.from_params(paint="few_spots").apply_to(parsed)
        assert merged.require_clean_body is False
        assert merged.min_body_grade == 45
        assert passes_features(car("a", body_grade=50), merged)

    def test_unset_filters_leave_the_parsed_intent_alone(self):
        parsed = parse_with_rules("کراس اور اتوماتیک تا ۲ میلیارد")
        merged = Filters.from_params().apply_to(parsed)
        assert merged.budget_max == parsed.budget_max
        assert merged.transmission == parsed.transmission
        assert merged.body_types == parsed.body_types


class TestPassesFeatures:
    def test_no_selection_admits_everything(self):
        assert passes_features(car("a"), intent_from())

    @pytest.mark.parametrize("params,field,ok,bad", [
        ({"brands": "kia"}, "brand", "kia", "bmw"),
        ({"body_types": "crossover"}, "body_type", "crossover", "passenger_car"),
        ({"fuels": "برقی"}, "fuel", "برقی", "بنزینی"),
        ({"colors": "مشکی"}, "body_color", "مشکی", "سفید"),
        ({"cities": "اصفهان"}, "city", "اصفهان", "تهران"),
        ({"sellers": "نمایشگاه"}, "seller", "نمایشگاه", "شخصی"),
        ({"sources": "divar"}, "source", "divar", "bama"),
    ])
    def test_enum_selection_is_exact(self, params, field, ok, bad):
        intent = intent_from(**params)
        assert passes_features(car("a", **{field: ok}), intent)
        assert not passes_features(car("b", **{field: bad}), intent)

    def test_multi_select_is_a_union(self):
        intent = intent_from(brands="kia,bmw")
        assert passes_features(car("a", brand="kia"), intent)
        assert passes_features(car("b", brand="bmw"), intent)
        assert not passes_features(car("c", brand="pride"), intent)

    def test_model_is_namespaced_by_brand(self):
        """«۲۰۶» is a Peugeot and «۳۱۵» an MVM; a bare model slug would collide."""
        intent = intent_from(models="peugeot/206ir")
        assert passes_features(car("a", brand="peugeot", model="206ir"), intent)
        assert not passes_features(car("b", brand="mvm", model="206ir"), intent)

    def test_hidden_price_car_stays_inside_a_price_range(self):
        """The product's whole argument, applied to a slider."""
        intent = intent_from(price_min="700000000", price_max="900000000")
        hidden = car("a", price_toman=None, is_negotiable=True, fair_price=800_000_000)
        assert passes_features(hidden, intent)

    def test_car_with_no_price_and_no_estimate_cannot_meet_a_budget(self):
        intent = intent_from(price_max="900000000")
        assert not passes_features(car("a", price_toman=None, fair_price=None), intent)

    def test_year_range(self):
        intent = intent_from(year_min="2015", year_max="2020")
        assert passes_features(car("a", year=2018), intent)
        assert not passes_features(car("b", year=2012), intent)
        assert not passes_features(car("c", year=2024), intent)

    def test_mileage_range(self):
        intent = intent_from(mileage_max="120000")
        assert passes_features(car("a", mileage_km=100_000), intent)
        assert not passes_features(car("b", mileage_km=200_000), intent)

    def test_missing_value_fails_a_range_rather_than_passing_as_zero(self):
        """An unknown engine size is not a 0.0-litre engine."""
        intent = intent_from(engine_min="1.5")
        assert not passes_features(car("a", engine_volume_l=None), intent)

    def test_consumption_ceiling(self):
        intent = intent_from(consumption_max="7")
        assert passes_features(car("a", consumption_l100=6.5), intent)
        assert not passes_features(car("b", consumption_l100=9.0), intent)

    def test_paint_bands_are_ordered(self):
        strict, loose = intent_from(paint="clean"), intent_from(paint="few_spots")
        repainted = car("a", body_grade=45)
        assert not passes_features(repainted, strict)
        assert passes_features(repainted, loose)

    def test_min_health_uses_the_cached_score(self):
        intent = intent_from(min_health="80")
        assert passes_features(car("a", health_score=85), intent)
        assert not passes_features(car("b", health_score=40), intent)

    def test_boolean_toggles(self):
        assert passes_features(car("a", authenticated=True), intent_from(inspected="1"))
        assert not passes_features(car("b", authenticated=False), intent_from(inspected="1"))
        assert not passes_features(car("c", image_count=0), intent_from(has_image="1"))

    def test_below_market_excludes_deposit_listings(self):
        """A voucher's -90% is not a discount, it is a down-payment."""
        intent = intent_from(below_market="1")
        assert passes_features(car("a", price_delta_pct=-12.0), intent)
        assert not passes_features(car("b", price_delta_pct=-90.0, price_flag="deposit"), intent)

    def test_selections_combine_as_and(self):
        intent = intent_from(brands="kia", transmissions="اتوماتیک", price_max="1200000000")
        assert passes_features(car("a"), intent)
        assert not passes_features(car("b", brand="bmw"), intent)
        assert not passes_features(car("c", price_toman=5_000_000_000, fair_price=None), intent)


class TestCatalogue:
    @pytest.fixture
    def corpus(self):
        rows = [car(f"a{i}", brand="kia", body_color="سفید") for i in range(5)]
        rows += [car(f"b{i}", brand="bmw", brand_fa="ب ام و", model="x4",
                     model_fa="X4", body_color="مشکی", price_toman=9_000_000_000,
                     fair_price=9_000_000_000) for i in range(3)]
        return rows

    def test_every_feature_is_described(self, corpus):
        cat = build_catalogue(corpus)
        assert cat["total"] == 8
        assert {f["key"] for f in cat["features"]} == {f.key for f in FEATURES}

    def test_enum_values_are_labelled_from_the_data(self, corpus):
        cat = build_catalogue(corpus)
        brand = next(f for f in cat["features"] if f["key"] == "brand")
        # Sorted by count, so the five Kias lead the three BMWs.
        assert brand["values"][0]["value"] == "kia"
        assert brand["values"][0]["label_fa"] == "کیا"
        assert brand["values"][0]["count"] == 5

    def test_closed_sets_get_english_labels(self, corpus):
        cat = build_catalogue(corpus)
        gearbox = next(f for f in cat["features"] if f["key"] == "transmission")
        assert gearbox["values"][0]["label_en"] == "Automatic"

    def test_brand_english_comes_from_the_slug_the_corpus_carries(self, corpus):
        """87 brands is too many to translate by hand, and Bama already has it.

        Short slugs are acronyms in this market; longer ones are plain names.
        """
        cat = build_catalogue(corpus)
        labels = {
            v["value"]: v["label_en"]
            for v in next(f for f in cat["features"] if f["key"] == "brand")["values"]
        }
        assert labels["bmw"] == "BMW"
        # Three letters, so Kia takes the acronym branch too — an accepted
        # styling of the marque, and cheaper than maintaining an exception list.
        assert labels["kia"] == "KIA"

    def test_open_sets_keep_persian_rather_than_inventing_english(self, corpus):
        """There is no honest English for «نقرآبی» — showing the Persian is better."""
        cat = build_catalogue(corpus)
        colour = next(f for f in cat["features"] if f["key"] == "color")
        assert colour["values"][0]["label_en"] == colour["values"][0]["label_fa"]

    def test_model_values_carry_their_brand(self, corpus):
        cat = build_catalogue(corpus)
        model = next(f for f in cat["features"] if f["key"] == "model")
        assert model["parent"] == "brand"
        assert {v["parent"] for v in model["values"]} == {"kia", "bmw"}

    def test_range_bounds_are_percentile_clamped(self):
        """A slider drawn from the true maximum is unusable.

        Real corpus: prices reach 535 billion against a p99 of 18.9 billion, and
        odometers reach 9,000,000 km against a p99 of 497,000.
        """
        rows = [car(f"a{i}", price_toman=1_000_000_000, fair_price=1_000_000_000)
                for i in range(100)]
        rows.append(car("outlier", price_toman=535_000_000_000, fair_price=None))
        price = next(f for f in build_catalogue(rows)["features"] if f["key"] == "price")
        assert price["true_max"] == 535_000_000_000
        assert price["max"] < 10_000_000_000

    def test_range_bounds_are_snapped_to_clean_numbers(self, corpus):
        """Binary floats do not divide by 0.1; the UI would render every digit."""
        engine = next(f for f in build_catalogue(corpus)["features"] if f["key"] == "engine")
        assert engine["max"] == round(engine["max"], 1)

    def test_health_scores_are_cached_onto_the_rows(self, corpus):
        build_catalogue(corpus)
        assert all(row.get("health_score") is not None for row in corpus)


class TestLeaveOneOutCounts:
    @pytest.fixture
    def corpus(self):
        return (
            [car(f"k{i}", brand="kia", fuel="بنزینی") for i in range(5)]
            + [car(f"h{i}", brand="hyundai", brand_fa="هیوندای", fuel="برقی") for i in range(3)]
            + [car(f"b{i}", brand="bmw", brand_fa="ب ام و", fuel="بنزینی") for i in range(2)]
        )

    def _counts(self, corpus, key, **params):
        counts = count_features(corpus, intent_from(**params))
        return {v["value"]: v["count"] for v in counts[key]["values"]}

    def test_selecting_a_brand_leaves_its_siblings_countable(self, corpus):
        """Otherwise ticking one brand zeroes the rest and you can never add a second."""
        brands = self._counts(corpus, "brand", brands="kia")
        assert brands == {"kia": 5, "hyundai": 3, "bmw": 2}

    def test_other_features_are_narrowed_by_the_selection(self, corpus):
        """Fuel counts must reflect the chosen brand — that is the whole point."""
        assert self._counts(corpus, "fuel", brands="kia") == {"بنزینی": 5}
        assert self._counts(corpus, "fuel", brands="hyundai") == {"برقی": 3}

    def test_unrelated_selections_still_narrow_a_facet(self, corpus):
        assert self._counts(corpus, "brand", fuels="بنزینی") == {"kia": 5, "bmw": 2}

    def test_empty_candidate_set(self):
        counts = count_features([], intent_from())
        assert counts["brand"]["values"] == []

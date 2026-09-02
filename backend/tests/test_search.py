"""Tests for hybrid retrieval.

The behaviour worth protecting is the *separation*: retrieval decides which cars
a query is about, ranking only orders them. Phase 1 conflated the two and every
unrecognised query returned the same "best value" cars.
"""

import pytest

from app.search import SearchIndex


def _corpus() -> list[dict]:
    def car(code, brand, model, brand_fa, title, **extra):
        row = {
            "code": code, "brand": brand, "model": model, "brand_fa": brand_fa,
            "title": title, "trim": None, "body_type_fa": None, "transmission": None,
            "fuel": None, "body_status": "بدون رنگ", "city": "تهران",
            "body_color": "سفید",
            "description": None, "price_toman": 1_000_000_000, "year": 2015,
        }
        row.update(extra)
        return row

    # Colours are spread deliberately: `MIN_IDENTITY_DF` listings must share a
    # word before it counts as a car attribute, so «مشکی» is on three cars and
    # «قرمز» on one. That is the difference the vocabulary gate exists to make.
    return [
        car("bama_1", "kia", "cerato", "کیا", "کیا، سراتو", body_color="مشکی"),
        car("bama_2", "kia", "ceratoir", "کیا", "کیا، سراتو (مونتاژ)"),
        car("bama_3", "peugeot", "206ir", "پژو", "پژو، 206", body_color="مشکی"),
        car("bama_4", "peugeot", "207i", "پژو", "پژو، 207", body_color="مشکی"),
        car("bama_5", "bmw", "x4", "ب ام و", "ب ام و، X4", price_toman=9_000_000_000),
        car("bama_6", "pride", "131", "پراید", "پراید، 131", price_toman=300_000_000,
            body_color="قرمز"),
        car("bama_7", "renault", "tondar90", "رنو", "رنو، تندر 90",
            description="معاوضه با دوچرخه یا موتور"),
    ]


@pytest.fixture(scope="module")
def index() -> SearchIndex:
    return SearchIndex(_corpus())


class TestEntityRetrieval:
    def test_model_name_filters_to_that_model(self, index):
        found = index.retrieve("سراتو")
        assert found.mode == "entity"
        assert set(found.codes) == {"bama_1", "bama_2"}

    def test_unrelated_cars_are_excluded(self, index):
        """The Phase 1 bug: «سراتو» returned a BMW X4."""
        assert "bama_5" not in index.retrieve("سراتو").codes

    def test_brand_and_model_together(self, index):
        found = index.retrieve("پژو ۲۰۶")
        assert found.codes == ["bama_3"]

    def test_brand_alone_returns_the_whole_brand(self, index):
        assert set(index.retrieve("پژو").codes) == {"bama_3", "bama_4"}

    def test_entity_scores_are_uniform(self, index):
        """Ranking, not retrieval, orders cars that all match the query."""
        found = index.retrieve("سراتو")
        assert set(found.scores.values()) == {1.0}

    def test_leftover_words_order_the_entity_set(self, index):
        """«سراتوی مشکی» is still every Cerato — colour is not a hard filter —
        but the black one has to come first. Intent carries no colour field, so
        retrieval is the last stage that still has the word."""
        found = index.retrieve("سراتو مشکی")
        assert set(found.codes) == {"bama_1", "bama_2"}
        assert found.scores["bama_1"] > found.scores["bama_2"]

    def test_brand_with_a_designator_it_has_no_model_for(self, index):
        """«کوییک دنده ای» named Saipa's Quik; «دنده ای» is also the literal
        model name of other marques' trims. Answering with those was the bug."""
        found = index.retrieve("پژو سراتو")
        assert all(index.by_code[c]["brand"] == "peugeot" for c in found.codes)


class TestNonsense:
    def test_gibberish_returns_nothing(self, index):
        found = index.retrieve("زیبیبیبیب")
        assert found.mode == "nonsense"
        assert found.codes == []

    def test_unknown_car_is_not_substituted(self, index):
        """A real car we don't stock must not silently become a different car."""
        found = index.retrieve("لامبورگینی")
        assert found.codes == []

    def test_word_seen_only_in_a_description_is_not_a_car(self, index):
        """«دوچرخه» appears in one seller's part-exchange note. That is a
        mention, not a thing we sell, and a search for it used to answer with
        whatever the ranker liked best."""
        found = index.retrieve("دوچرخه")
        assert found.mode == "nonsense"
        assert found.codes == []

    def test_named_car_we_do_not_stock_says_so(self, index):
        """Distinct from gibberish: we understood the query, we have none."""
        found = index.retrieve("فولکس واگن")
        assert found.mode == "unknown_car"
        assert found.codes == []

    def test_unreadable_words_fall_back_to_the_constraints(self, index):
        """A budget we understood beside words we did not. Answer the budget and
        let the UI admit the rest was ignored — inventing a relevance order over
        meaningless words is what produced unrelated results."""
        found = index.retrieve("دوچرخه زیر ۵۰۰ میلیون", has_constraints=True)
        assert found.mode == "constraints"
        assert len(found.codes) == len(_corpus())


class TestRelevanceFloor:
    def test_only_cars_sharing_the_attribute_are_kept(self, index):
        """The core regression: retrieval used to hand ranking the top 400 rows
        whatever they scored, so «ماشین مشکی» returned white cars too."""
        found = index.retrieve("ماشین مشکی")
        brands = {index.by_code[c]["body_color"] for c in found.codes}
        assert found.codes
        assert brands == {"مشکی"}

    def test_the_pool_is_smaller_than_the_corpus(self, index):
        found = index.retrieve("ماشین مشکی")
        assert len(found.codes) < len(_corpus())


class TestConstraintOnly:
    def test_pure_budget_query_keeps_everything(self, index):
        """No relevance signal to apply — the structured filters do the work."""
        found = index.retrieve("زیر ۵۰۰ میلیون", has_constraints=True)
        assert found.mode == "none"
        assert len(found.codes) == len(_corpus())

    def test_budget_query_does_not_match_a_numeric_model(self, index):
        assert index.retrieve("زیر ۵۰۰ میلیون", has_constraints=True).mode != "entity"


class TestSemantic:
    def test_lifestyle_query_is_not_nonsense(self, index):
        """«دختر دانشجو» appears in no listing but is real intent.

        On a corpus this small nothing discriminates, so retrieval hands
        everything to ranking rather than returning an empty page.
        """
        found = index.retrieve("ماشین برای دختر دانشجو")
        assert found.mode in ("semantic", "text", "none")
        assert found.codes

    def test_scores_are_ranked(self, index):
        found = index.retrieve("سراتو ۲۰۱۵ بدون رنگ")
        values = [found.scores[c] for c in found.codes if c in found.scores]
        assert values == sorted(values, reverse=True)


class TestGracefulDegradation:
    def test_semantic_falls_back_without_embeddings(self, index):
        """No sentence model loaded — LSA must still produce scores."""
        assert index.embeddings is None
        scores = index._semantic_scores("ماشین خانواده")
        assert scores is not None and len(scores) == len(_corpus())

    def test_empty_query_returns_everything(self, index):
        assert len(index.retrieve("").codes) == len(_corpus())

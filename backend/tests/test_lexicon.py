"""Tests for the corpus-derived vocabulary and entity matching.

These pin the specific failures found in Phase 1 — «سراتو» returning a BMW,
«۲۰۶» matching nothing — plus the false positives introduced while fixing them.
"""

import pytest

from app import lexicon
from app.lexicon import Lexicon, fold, match, split_title


def _rows() -> list[dict]:
    """A miniature corpus with the ambiguities that matter."""
    return [
        {"brand": "kia", "model": "cerato", "brand_fa": "کیا", "title": "کیا، سراتو"},
        {"brand": "kia", "model": "ceratoir", "brand_fa": "کیا", "title": "کیا، سراتو (مونتاژ)"},
        {"brand": "kia", "model": "rioir", "brand_fa": "کیا", "title": "کیا، ریو (مونتاژ)"},
        {"brand": "peugeot", "model": "206ir", "brand_fa": "پژو", "title": "پژو، 206"},
        {"brand": "peugeot", "model": "206sd", "brand_fa": "پژو", "title": "پژو، 206 SD"},
        {"brand": "samand", "model": "lx", "brand_fa": "سمند", "title": "سمند، LX"},
        {"brand": "lexus", "model": "lx", "brand_fa": "لکسوس", "title": "لکسوس، LX"},
        {"brand": "mazda", "model": "3sedan", "brand_fa": "مزدا", "title": "مزدا، 3 نیو صندوق دار"},
        {"brand": "bmw", "model": "5seriessedan", "brand_fa": "ب ام و", "title": "ب ام و، سری 5 سدان"},
        {"brand": "dena", "model": "plus", "brand_fa": "دنا", "title": "دنا، پلاس EF7"},
        {"brand": "saina", "model": "at", "brand_fa": "ساینا", "title": "ساینا، اتوماتیک"},
        {"brand": "pride", "model": "hatchback", "brand_fa": "پراید", "title": "پراید، هاچ بک"},
        {"brand": "fiat", "model": "500", "brand_fa": "فیات", "title": "فیات، 500"},
    ]


@pytest.fixture(scope="module")
def lex() -> Lexicon:
    return lexicon.build(_rows())


class TestFold:
    def test_persian_digits_become_ascii(self):
        assert fold("۲۰۶") == "206"

    def test_arabic_yeh_and_kaf_normalized(self):
        assert fold("كيا") == fold("کیا")

    def test_zwnj_becomes_space(self):
        assert fold("کم‌مصرف") == "کم مصرف"

    def test_punctuation_stripped(self):
        assert fold("سراتو (مونتاژ)") == "سراتو مونتاژ"


class TestSplitTitle:
    def test_splits_on_persian_comma(self):
        assert split_title("کیا، سراتو (مونتاژ)") == ("کیا", "سراتو (مونتاژ)")

    def test_missing_separator(self):
        assert split_title("چیزی") == (None, None)


class TestEntityMatching:
    def test_model_name_alone_resolves_brand(self, lex):
        """The Phase 1 headline bug: «سراتو» returned a BMW."""
        m = match("سراتو", lex)
        assert m.models == {("kia", "cerato"), ("kia", "ceratoir")}
        assert m.brands == set()

    def test_persian_digits_match_latin_model(self, lex):
        m = match("پژو ۲۰۶", lex)
        assert ("peugeot", "206ir") in m.models

    def test_brand_disambiguates_shared_model_name(self, lex):
        """Both Samand and Lexus have an 'LX'; the named brand decides."""
        m = match("سمند ال ایکس", lex)
        assert m.models == {("samand", "lx")}

    def test_brand_plus_bare_number(self, lex):
        m = match("مزدا ۳", lex)
        assert ("mazda", "3sedan") in m.models

    def test_multiword_brand_and_alias(self, lex):
        m = match("ب ام و سری ۵", lex)
        assert ("bmw", "5seriessedan") in m.models

    def test_plus_is_part_of_the_model_not_noise(self, lex):
        m = match("دنا پلاس", lex)
        assert ("dena", "plus") in m.models

    def test_brand_alone(self, lex):
        m = match("کیا", lex)
        assert m.brands == {"kia"}
        assert not m.models

    def test_typo_still_matches(self, lex):
        m = match("سراتوو", lex)
        assert ("kia", "cerato") in m.models
        assert m.fuzzy is True

    def test_leftover_is_returned_for_text_stage(self, lex):
        m = match("سراتو اتوماتیک", lex)
        assert "اتوماتیک" in m.leftover


class TestFalsePositives:
    def test_amount_is_not_a_model(self, lex):
        """«زیر ۵۰۰ میلیون» must not match the Fiat 500."""
        m = match("زیر ۵۰۰ میلیون", lex)
        assert ("fiat", "500") not in m.models
        assert not m.has_entity

    def test_gearbox_word_is_not_a_model(self, lex):
        """Saina's trim is literally called «اتوماتیک»; in a query it's a spec."""
        m = match("206 اتوماتیک", lex)
        assert ("saina", "at") not in m.models
        assert ("peugeot", "206ir") in m.models

    def test_body_style_is_not_a_model(self, lex):
        """Pride has a model called «هاچ بک»; in a query it's a body style."""
        m = match("هاچبک اتوماتیک", lex)
        assert not m.has_entity

    def test_gibberish_matches_nothing(self, lex):
        assert not match("زیبیبیبیب", lex).has_entity

    def test_number_never_fuzzy_matches(self, lex):
        """Numbers match exactly or not at all."""
        assert not match("۵۰۱ میلیون", lex).has_entity


class TestBuild:
    def test_vocabulary_comes_from_the_data(self, lex):
        assert fold("کیا") in lex.brands
        assert fold("سراتو") in lex.models

    def test_assembly_suffix_is_stripped(self, lex):
        """'rioir' should be reachable as 'rio'."""
        assert ("kia", "rioir") in {tuple(p) for p in lex.models[fold("rio")]}

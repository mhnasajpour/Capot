"""Tests for the rule-based query parser.

The rule path is what runs when the LLM is unavailable, so it has to stand on
its own — these tests pin the behaviour the demo depends on.
"""

from app.query import parse_with_rules


class TestBudget:
    def test_million_with_persian_digits(self):
        intent = parse_with_rules("بودجه ۸۰۰ میلیون")
        assert intent.budget_max == 800_000_000

    def test_billion(self):
        intent = parse_with_rules("تا ۲ میلیارد")
        assert intent.budget_max == 2_000_000_000

    def test_decimal_billion(self):
        intent = parse_with_rules("تا 1.5 میلیارد")
        assert intent.budget_max == 1_500_000_000

    def test_range(self):
        intent = parse_with_rules("بین ۵۰۰ میلیون تا ۸۰۰ میلیون")
        assert intent.budget_min == 500_000_000
        assert intent.budget_max == 800_000_000

    def test_lower_bound_only(self):
        intent = parse_with_rules("بالای ۱ میلیارد")
        assert intent.budget_min == 1_000_000_000
        assert intent.budget_max is None

    def test_no_budget_mentioned(self):
        assert parse_with_rules("پراید سالم").budget_max is None


class TestAttributes:
    def test_transmission_automatic(self):
        assert parse_with_rules("کراس اور اتوماتیک").transmission == "اتوماتیک"

    def test_body_type(self):
        assert "crossover" in parse_with_rules("کراس اور می‌خوام").body_types

    def test_clean_body_requirement(self):
        assert parse_with_rules("بدون رنگ باشه").require_clean_body is True

    def test_brand_detection(self):
        assert "pride" in parse_with_rules("پراید زیر ۳۰۰ میلیون").brands

    def test_fuel(self):
        assert parse_with_rules("دوگانه سوز باشه").fuel == "دوگانه سوز"


class TestUseCaseAndPriorities:
    def test_family_implies_space_and_safety(self):
        intent = parse_with_rules("ماشین خانواده")
        assert intent.use_case == "family"
        assert "space" in intent.priorities
        assert "safety" in intent.priorities

    def test_first_car_implies_economy(self):
        intent = parse_with_rules("اولین ماشین")
        assert intent.use_case == "first_car"
        assert "low_consumption" in intent.priorities

    def test_work_car_implies_cheap_parts(self):
        intent = parse_with_rules("ماشین مسافرکشی")
        assert intent.use_case == "work"
        assert "cheap_parts" in intent.priorities

    def test_explicit_priority_detected(self):
        assert "low_consumption" in parse_with_rules("کم‌مصرف باشه").priorities


class TestCompositeQuery:
    def test_realistic_query(self):
        intent = parse_with_rules("اولین ماشین خانواده، بودجه ۸۰۰ میلیون، کم‌مصرف و بدون رنگ")
        assert intent.budget_max == 800_000_000
        assert intent.require_clean_body is True
        assert "low_consumption" in intent.priorities
        assert intent.use_case in {"family", "first_car"}
        assert not intent.is_empty

    def test_empty_query_is_empty_intent(self):
        assert parse_with_rules("").is_empty

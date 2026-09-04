"""Health / risk scoring for a listing.

Answers the second of the buyer's three questions: *is this car healthy?*

The score is deliberately rule-based and fully deterministic. Two reasons:
the signals that matter (paint condition, mileage-for-age, seller trust) are
already structured, and a buyer deserves to know exactly why a car scored what
it did. The LLM contributes only *extra* evidence pulled out of the free-text
description — it never replaces the arithmetic.

Every component returns a labelled factor with its point impact, so the UI can
show "why 72" rather than an unexplained number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Typical annual distance for an Iranian car. Used to judge whether a given
# odometer reading is high, normal, or implausibly low for the car's age.
EXPECTED_KM_PER_YEAR = 20_000

BASE_SCORE = 62  # a plain, unremarkable used car starts here

SEVERITY_PENALTY = {"high": 18, "medium": 10, "low": 5}


@dataclass
class Factor:
    """One scoring component, with the points it moved and a bilingual label."""

    key: str
    label_fa: str
    label_en: str
    impact: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label_fa": self.label_fa,
            "label_en": self.label_en,
            "impact": self.impact,
        }


@dataclass
class HealthResult:
    score: int
    factors: list[Factor] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "factors": [f.to_dict() for f in self.factors]}

    @property
    def positives(self) -> list[Factor]:
        return [f for f in self.factors if f.impact > 0]

    @property
    def negatives(self) -> list[Factor]:
        return [f for f in self.factors if f.impact < 0]


def _body_factor(body_grade: int | None, body_status: str | None) -> Factor:
    """Paint integrity is the single strongest condition signal in this market."""
    grade = 60 if body_grade is None else body_grade
    # Map the 0-100 paint grade onto a -22..+18 swing around the base score.
    impact = round((grade - 60) * 0.40)
    impact = max(-22, min(18, impact))
    status = body_status or "نامشخص"
    return Factor("body", f"وضعیت بدنه: {status}", f"Body: {status}", impact)


def _mileage_factor(mileage_km: int | None, age: int | None) -> Factor | None:
    """Judge the odometer against what the car's age would predict.

    Unusually *low* mileage on an old car is treated as a mild risk, not a bonus:
    in this market it more often signals a rolled-back odometer than a garaged
    creampuff.
    """
    if mileage_km is None or age is None:
        return None

    if age <= 0:
        if mileage_km <= 1000:
            return Factor("mileage", "خودرو صفر کیلومتر", "Brand new", 14)
        return None

    expected = EXPECTED_KM_PER_YEAR * age
    if expected <= 0:
        return None
    ratio = mileage_km / expected

    if ratio >= 1.8:
        return Factor("mileage", "کارکرد بسیار بالا برای این سن", "Very high mileage for age", -16)
    if ratio >= 1.35:
        return Factor("mileage", "کارکرد بالاتر از حد معمول", "Above-average mileage", -9)
    if ratio <= 0.25 and age >= 5:
        return Factor("mileage", "کارکرد مشکوک (بسیار کم برای این سن)", "Suspiciously low mileage for age", -7)
    if ratio <= 0.65:
        return Factor("mileage", "کارکرد کمتر از حد معمول", "Below-average mileage", 10)
    return Factor("mileage", "کارکرد متناسب با سن خودرو", "Mileage normal for age", 3)


def _age_factor(age: int | None) -> Factor | None:
    if age is None:
        return None
    if age <= 1:
        return Factor("age", "خودرو نو", "Nearly new", 8)
    if age <= 5:
        return Factor("age", "سن پایین", "Low age", 4)
    if age >= 18:
        return Factor("age", "خودرو قدیمی", "Old vehicle", -12)
    if age >= 12:
        return Factor("age", "سن نسبتا بالا", "Ageing vehicle", -6)
    return None


def _seller_factor(seller: str | None, dealer_score: float | None) -> Factor | None:
    """Seller trust, from the marque's own accountability and its rating.

    `dealer_ad_count` is deliberately not read. It was passed in and ignored,
    which made the signature promise a volume judgement the arithmetic never
    made — and a high ad count is not evidence either way here: the busiest
    dealers on these sites are also the established ones.
    """
    if seller == "نمایندگی":
        return Factor("seller", "فروشنده: نمایندگی رسمی", "Seller: official agency", 8)
    if dealer_score is not None:
        if dealer_score >= 4.3:
            return Factor("seller", f"نمایشگاه با امتیاز بالا ({dealer_score})", f"Highly rated dealer ({dealer_score})", 7)
        if dealer_score >= 3.5:
            return Factor("seller", f"نمایشگاه معتبر ({dealer_score})", f"Reputable dealer ({dealer_score})", 3)
        return Factor("seller", f"امتیاز پایین نمایشگاه ({dealer_score})", f"Low dealer rating ({dealer_score})", -6)
    if seller == "شخصی":
        # Neither good nor bad, but worth surfacing: no dealer accountability.
        return Factor("seller", "فروشنده شخصی (بدون سابقه قابل بررسی)", "Private seller (no track record)", -2)
    return None


def _inspection_factor(authenticated: bool) -> Factor | None:
    if authenticated:
        return Factor("inspection", "کارشناسی‌شده توسط باما", "Bama-inspected", 12)
    return None


#: Chassis phrases Sheypoor uses, worst first. A bent or repaired chassis is
#: structural damage rather than cosmetic, so it outweighs any paint grade.
CHASSIS_PATTERNS: list[tuple[tuple[str, ...], str, str, int]] = [
    (("تعویض",), "شاسی تعویض شده", "Chassis replaced", -26),
    (("ضربه", "تصادف"), "شاسی ضربه‌خورده", "Chassis impact damage", -20),
    (("رنگ",), "شاسی رنگ‌شده", "Chassis resprayed", -12),
    (("سالم و پلمپ", "پلمپ"), "شاسی سالم و پلمپ", "Chassis intact and sealed", 8),
    (("سالم",), "شاسی سالم", "Chassis intact", 5),
]


def _chassis_factor(status: str | None) -> Factor | None:
    """Chassis condition (وضعیت شاسی).

    Sheypoor is the only source here that reports it, so this only ever fires
    for Sheypoor rows — a genuine extra signal, not a penalty for the sources
    that stay quiet. Matched worst-first for the same reason
    `divar.infer_body_status` is: a listing reading 'جلو سالم، عقب ضربه‌خورده'
    must score as damaged, not as intact.
    """
    if not status:
        return None
    for phrases, label_fa, label_en, impact in CHASSIS_PATTERNS:
        if any(phrase in status for phrase in phrases):
            return Factor("chassis", label_fa, label_en, impact)
    return None


def _insurance_factor(months: int | None) -> Factor | None:
    """Remaining third-party insurance (بیمهٔ شخص ثالث).

    Divar publishes this; Bama does not, so it only ever fires for Divar rows —
    a genuine signal rather than a penalty for the other source. In Iran it cuts
    both ways: a long remaining term is real money the buyer doesn't have to
    spend, and an expired policy is both an immediate cost and a hint the car
    has been sitting.
    """
    if months is None:
        return None
    if months >= 9:
        return Factor("insurance", "بیمهٔ شخص ثالث بلندمدت", "Long insurance remaining", 6)
    if months >= 4:
        return Factor("insurance", "بیمهٔ شخص ثالث معتبر", "Valid insurance", 3)
    if months >= 1:
        return Factor("insurance", "بیمه رو به اتمام", "Insurance expiring soon", -2)
    return Factor("insurance", "بیمهٔ شخص ثالث منقضی", "Insurance expired", -5)


def _media_factor(image_count: int | None) -> Factor | None:
    """Sellers hiding a car behind one photo are hiding something more often
    than not; a full gallery is a small honesty signal."""
    if image_count is None:
        return None
    if image_count == 0:
        return Factor("media", "بدون تصویر", "No photos", -6)
    if image_count >= 8:
        return Factor("media", "گالری تصاویر کامل", "Full photo gallery", 3)
    return None


def _llm_flag_factors(red_flags: list[dict] | None, positives: list[str] | None) -> list[Factor]:
    """Fold in evidence the LLM extracted from the free-text description."""
    factors: list[Factor] = []
    for flag in red_flags or []:
        if not isinstance(flag, dict):
            continue
        label_fa = flag.get("label_fa") or flag.get("label") or "ریسک ذکرشده در توضیحات"
        label_en = flag.get("label_en") or "Risk mentioned in description"
        severity = str(flag.get("severity", "medium")).lower()
        penalty = SEVERITY_PENALTY.get(severity, SEVERITY_PENALTY["medium"])
        factors.append(Factor(f"text_risk:{flag.get('code', severity)}", label_fa, label_en, -penalty))

    for positive in (positives or [])[:2]:
        if isinstance(positive, str) and positive.strip():
            factors.append(Factor("text_positive", positive.strip(), positive.strip(), 4))
    return factors


def score_listing(row: dict) -> HealthResult:
    """Compute the composite health score for one listing row."""
    factors: list[Factor] = [_body_factor(row.get("body_grade"), row.get("body_status"))]

    candidates = [
        _mileage_factor(row.get("mileage_km"), row.get("age")),
        _age_factor(row.get("age")),
        _seller_factor(row.get("seller"), row.get("dealer_score")),
        _inspection_factor(bool(row.get("authenticated"))),
        _insurance_factor(row.get("insurance_months")),
        _chassis_factor(row.get("chassis_status")),
        _media_factor(row.get("image_count")),
    ]
    factors.extend(f for f in candidates if f is not None)
    factors.extend(_llm_flag_factors(row.get("red_flags"), row.get("positives")))

    raw = BASE_SCORE + sum(f.impact for f in factors)
    score = max(1, min(100, int(round(raw))))

    # Show the factors that moved the number most, largest effect first.
    factors.sort(key=lambda f: abs(f.impact), reverse=True)
    return HealthResult(score=score, factors=factors)


def health_score(row: dict) -> int:
    """The number alone, from the row's cache when it has one.

    Ordering a result set needs the score but none of the factors behind it,
    and `score_listing` walks a dozen of them. `features.ensure_health_scores`
    already writes the number onto every corpus row at load time, so ranking
    thousands of candidates is thousands of dict lookups rather than thousands
    of rescorings. A row that was never through that pass — a fabricated one in
    a test — is scored on the spot.
    """
    cached = row.get("health_score")
    return int(cached) if cached is not None else score_listing(row).score


def health_band(score: int) -> tuple[str, str]:
    """Bucket a score into a bilingual label for the UI."""
    if score >= 80:
        return "عالی", "Excellent"
    if score >= 65:
        return "خوب", "Good"
    if score >= 50:
        return "متوسط", "Fair"
    if score >= 35:
        return "قابل بررسی", "Needs inspection"
    return "پرریسک", "High risk"

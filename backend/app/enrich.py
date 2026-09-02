"""Extract structured risk signals from free-text ad descriptions.

    python -m app.enrich --limit 500

Sellers bury the things that matter in prose: «درب شاگرد آبرنگ», «موتور تعویض
شده», «سند در رهن بانک». Those change what a car is worth and whether it is safe
to buy, and none of them appear in any structured field.

This is a **batch** job, run once after ingest. Results land in the enrichment
table and the LLM cache, so the request path never waits on a model and the demo
runs offline. A keyword scanner runs first and always — the LLM adds nuance on
top, it is not a dependency.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from . import db
from .llm import complete_json

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You read Persian used-car advertisement text and extract risk signals.
Return ONLY a JSON object:
{
  "red_flags": [ {"code": "...", "label_fa": "...", "label_en": "...", "severity": "high|medium|low"} ],
  "positives": ["short Persian phrase", ...],
  "extracted": {"installment": bool, "exchange": bool, "urgent_sale": bool, "warranty": bool}
}
red_flags codes to use when present: accident (تصادف), repainted (رنگ شدگی),
engine_replaced (موتور تعویض), chassis (شاسی/جوش), lien (سند در رهن/سند مشکل دار),
high_wear (استهلاک بالا), flood (آبگرفتگی), unclear_papers (مدارک ناقص).
severity: high for structural/legal problems, medium for cosmetic bodywork or
major component replacement, low for minor wear.
positives: genuine selling points only (بیمه کامل, کارشناسی شده, تک برگ سند,
سرویس دوره ای). Ignore dealer marketing boilerplate, phone numbers and slogans.
If the text says nothing meaningful, return empty arrays."""

# Deterministic scan. Deliberately conservative: these phrases are unambiguous in
# Persian car ads, so a false positive here would be a real product defect.
RISK_PATTERNS: list[tuple[str, tuple[str, ...], str, str, str]] = [
    ("accident", ("تصادفی", "تصادف کرده", "ضربه خورده"), "سابقه تصادف", "Accident history", "high"),
    ("chassis", ("شاسی خوردگی", "شاسی ضربه", "جوشکاری شاسی", "شاسی تعویض"), "مشکل شاسی", "Chassis damage", "high"),
    ("lien", ("در رهن", "سند در رهن", "سند مشکل", "وکالتی"), "وضعیت سند", "Ownership/title issue", "high"),
    ("engine_replaced", ("موتور تعویض", "تعویض موتور", "موتور نو شده"), "موتور تعویض شده", "Engine replaced", "medium"),
    ("gearbox", ("گیربکس تعویض", "گیربکس مشکل"), "مشکل گیربکس", "Gearbox issue", "medium"),
    ("repainted", ("آبرنگ", "رنگ شدگی", "دور رنگ", "تمام رنگ"), "رنگ‌شدگی بدنه", "Repainted panels", "medium"),
    ("flood", ("آبگرفتگی", "آب گرفتگی"), "آبگرفتگی", "Flood damage", "high"),
    ("high_wear", ("استهلاک بالا", "نیاز به تعمیر", "موتور کار دارد"), "استهلاک بالا", "High wear", "medium"),
]

POSITIVE_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("بیمه کامل", "بیمه تا"), "بیمه معتبر"),
    (("کارشناسی شده", "کارشناسی مثبت"), "کارشناسی‌شده"),
    (("تک برگ", "سند تک برگ"), "سند تک‌برگ"),
    (("سرویس دوره", "سرویس کامل"), "سرویس دوره‌ای انجام‌شده"),
    (("بدون خط و خش", "بدون خش"), "بدنه بدون خط و خش"),
    (("گارانتی",), "دارای گارانتی"),
]

CONTEXT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("installment", ("اقساط", "قسطی", "نقد و اقساط")),
    ("exchange", ("معاوضه",)),
    ("urgent_sale", ("فوری", "فوری فروشی")),
    ("warranty", ("گارانتی", "وارانتی")),
]


def scan_text(description: str) -> dict[str, Any]:
    """Keyword pass over one description. Always runs, never fails."""
    text = description or ""
    red_flags = [
        {"code": code, "label_fa": fa, "label_en": en, "severity": severity}
        for code, phrases, fa, en, severity in RISK_PATTERNS
        if any(phrase in text for phrase in phrases)
    ]
    positives = [
        label for phrases, label in POSITIVE_PATTERNS
        if any(phrase in text for phrase in phrases)
    ]
    extracted = {
        key: any(phrase in text for phrase in phrases)
        for key, phrases in CONTEXT_PATTERNS
    }
    return {"red_flags": red_flags, "positives": positives, "extracted": extracted}


def _merge(rule_result: dict, llm_result: dict | None) -> dict:
    """Union the two passes, keeping the harsher severity on conflicts."""
    if not llm_result:
        return rule_result

    severity_rank = {"low": 0, "medium": 1, "high": 2}
    by_code: dict[str, dict] = {f["code"]: f for f in rule_result["red_flags"]}

    for flag in llm_result.get("red_flags") or []:
        if not isinstance(flag, dict) or not flag.get("code"):
            continue
        code = str(flag["code"])
        candidate = {
            "code": code,
            "label_fa": flag.get("label_fa") or flag.get("label") or code,
            "label_en": flag.get("label_en") or code,
            "severity": str(flag.get("severity", "medium")).lower(),
        }
        if candidate["severity"] not in severity_rank:
            candidate["severity"] = "medium"
        existing = by_code.get(code)
        if not existing or severity_rank[candidate["severity"]] > severity_rank[existing["severity"]]:
            by_code[code] = candidate

    positives = list(rule_result["positives"])
    for positive in llm_result.get("positives") or []:
        if isinstance(positive, str) and positive.strip() and positive.strip() not in positives:
            positives.append(positive.strip())

    extracted = dict(rule_result["extracted"])
    for key, value in (llm_result.get("extracted") or {}).items():
        if isinstance(value, bool):
            extracted[key] = extracted.get(key, False) or value

    return {
        "red_flags": list(by_code.values()),
        "positives": positives[:5],
        "extracted": extracted,
    }


def enrich_rows(rows: list[dict], *, use_llm: bool = True) -> list[dict]:
    """Enrich listings that have a description worth reading."""
    out: list[dict] = []
    llm_hits = 0

    for row in rows:
        description = (row.get("description") or "").strip()
        if not description:
            continue

        result = scan_text(description)
        from_llm = False

        if use_llm and len(description) >= 40:
            llm_result = complete_json(
                SYSTEM_PROMPT,
                json.dumps({"description": description[:1200]}, ensure_ascii=False),
            )
            if llm_result:
                llm_hits += 1
                from_llm = True
                result = _merge(result, llm_result)

        out.append({
            "code": row["code"],
            "red_flags": result["red_flags"],
            "positives": result["positives"],
            "extracted": result["extracted"],
            # Records what actually read this listing, not what was asked for.
            # Labelling by the flag marks a row 'llm+rules' whenever the model
            # was *available*, including runs where every call returned nothing
            # — an unreachable endpoint, an empty cache, a description under the
            # length floor. The corpus then claims a model read it when none
            # did, and `--only-new` skips it forever on that claim.
            "model": "llm+rules" if from_llm else "rules",
        })

    log.info("enriched %d listings (%d via LLM)", len(out), llm_hits)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract risk signals from ad descriptions")
    ap.add_argument("--limit", type=int, default=0, help="cap listings processed (0 = all)")
    ap.add_argument("--no-llm", action="store_true", help="keyword scan only")
    ap.add_argument(
        "--only-new", action="store_true",
        help="skip listings that already have an enrichment row",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    conn = db.connect()
    db.init_db(conn)
    rows = [r for r in db.fetch_all(conn) if r.get("description")]
    total = len(rows)

    if args.only_new:
        # Adding a source doubles the corpus but not the work: the listings
        # already enriched have not changed. The disk cache normally makes a
        # re-run free, but it only covers what has actually been written — a
        # fresh checkout, or a corpus enriched on another machine, has an
        # enrichment table and no cache behind it. Then a blanket re-run pays
        # full price for answers already in the database.
        #
        # "Already done" depends on what this run would produce. A row scanned
        # by rules alone is not finished work for an LLM run, so skipping it
        # would strand it: the cheap pass would permanently mask the listing
        # from the expensive one, and the corpus would look enriched while a
        # slice of it had never been read by a model.
        if args.no_llm:
            done = {r["code"] for r in conn.execute("SELECT code FROM enrichment")}
        else:
            done = {
                r["code"] for r in
                conn.execute("SELECT code FROM enrichment WHERE model = 'llm+rules'")
            }
        rows = [r for r in rows if r["code"] not in done]
        log.info("%d of %d listings still need enrichment", len(rows), total)

    if args.limit:
        rows = rows[: args.limit]
    log.info("%d listings with descriptions", len(rows))

    enriched = enrich_rows(rows, use_llm=not args.no_llm)
    written = db.upsert_enrichment(conn, enriched)
    log.info("wrote %d enrichment rows", written)

    flagged = sum(1 for e in enriched if e["red_flags"])
    log.info("%d listings carry at least one red flag", flagged)
    conn.close()


if __name__ == "__main__":
    main()

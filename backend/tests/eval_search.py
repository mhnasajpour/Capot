"""Search quality evaluation.

    python -m tests.eval_search              # run the suite, print precision@5
    python -m tests.eval_search --verbose    # also show the failing results

"Search is not accurate" is not a number, so this makes it one. Each case pairs a
realistic Persian query with the constraints a correct result must satisfy, and
we report precision@5 — of the top 5 results, how many actually satisfy them.

The cases are grounded in entities verified to exist in the corpus (Kia Cerato:
273 listings, Peugeot 206: 55, Renault Tondar 90: 671), so a failure means the
search missed them, not that the data is absent.

Run this BEFORE and AFTER a search change. It calls the search path in-process,
so no server needs to be running.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

from app import db


@dataclass
class Case:
    """One labelled query plus the constraints a correct hit must satisfy."""

    query: str
    note: str = ""
    brand: str | None = None
    model_contains: str | None = None
    max_price: int | None = None
    min_price: int | None = None
    body_type: str | None = None
    transmission: str | None = None
    fuel: str | None = None
    body_color: str | None = None
    text_contains: str | None = None
    min_body_grade: int | None = None
    max_mileage: int | None = None
    expect_empty: bool = False
    # Soft cases (vague, semantic) are reported separately — they measure
    # judgement, not correctness, and shouldn't inflate or deflate the headline.
    soft: bool = False

    def checks(self) -> list[tuple[str, Callable[[dict], bool]]]:
        out: list[tuple[str, Callable[[dict], bool]]] = []
        if self.brand:
            out.append((f"brand={self.brand}", lambda r: (r.get("brand") or "").lower() == self.brand))
        if self.model_contains:
            out.append((
                f"model~{self.model_contains}",
                lambda r: self.model_contains in (r.get("model") or "").lower(),
            ))
        if self.max_price:
            out.append((
                f"price<={self.max_price:,}",
                lambda r: (_price(r) or 0) <= self.max_price * 1.02,
            ))
        if self.min_price:
            out.append((
                f"price>={self.min_price:,}",
                lambda r: (_price(r) or 0) >= self.min_price * 0.98,
            ))
        if self.body_type:
            out.append((f"body={self.body_type}", lambda r: r.get("body_type") == self.body_type))
        if self.transmission:
            out.append((
                f"gearbox={self.transmission}",
                lambda r: self.transmission in (r.get("transmission") or ""),
            ))
        if self.fuel:
            out.append((f"fuel={self.fuel}", lambda r: self.fuel in (r.get("fuel") or "")))
        if self.body_color:
            out.append((
                f"colour={self.body_color}",
                lambda r: self.body_color in (r.get("body_color") or ""),
            ))
        if self.text_contains:
            # The same fields `search.doc_text` indexes — «پانوراما» lives in
            # Bama's `trim` far more often than in the title.
            out.append((
                f"text~{self.text_contains}",
                lambda r: self.text_contains in " ".join(
                    str(r.get(k) or "") for k in ("title", "trim", "body_type_fa")
                ) + (r.get("description") or "")[:300],
            ))
        if self.min_body_grade:
            out.append((
                f"body_grade>={self.min_body_grade}",
                lambda r: (r.get("body_grade") or 0) >= self.min_body_grade,
            ))
        if self.max_mileage:
            out.append((
                f"mileage<={self.max_mileage:,}",
                lambda r: (r.get("mileage_km") or 10**9) <= self.max_mileage,
            ))
        return out


def _price(result: dict) -> int | None:
    """Results carry price under 'price' (search) or flat (raw row)."""
    block = result.get("price")
    if isinstance(block, dict):
        return block.get("effective")
    return result.get("price_toman")


MILLION = 1_000_000
BILLION = 1_000_000_000

# Entity lookups — the category that is completely broken today.
CASES: list[Case] = [
    Case("سراتو", "model name alone, no brand", brand="kia", model_contains="cerato"),
    Case("پژو ۲۰۶", "Persian digits + brand", brand="peugeot", model_contains="206"),
    Case("206 اتوماتیک", "latin digits + gearbox", model_contains="206", transmission="اتوماتیک"),
    Case("تندر ۹۰", "model alone", brand="renault", model_contains="tondar"),
    Case("سمند ال ایکس", "spelled-out trim", brand="samand", model_contains="lx"),
    Case("پراید ۱۳۱", "brand + numeric model", brand="pride", model_contains="131"),
    Case("دنا پلاس", "brand + Persian trim", brand="dena", model_contains="plus"),
    Case("شاهین", "brand alone", brand="shahin"),
    Case("جک S5", "mixed script", brand="jac", model_contains="s5"),
    Case("هیوندای توسان", "brand + model", brand="hyundai", model_contains="tucson"),
    Case("ب ام و سری ۵", "multi-word brand", brand="bmw", model_contains="5series"),
    Case("مزدا ۳", "short numeric model", brand="mazda", model_contains="3"),
    Case("ریو", "short model name", brand="kia", model_contains="rio"),
    Case("سوناتا", "model alone", brand="hyundai", model_contains="sonata"),
    Case("ماکسیما", "model alone", brand="nissan", model_contains="maxima"),
    Case("کیا سراتو اتوماتیک", "brand+model+gearbox", brand="kia",
         model_contains="cerato", transmission="اتوماتیک"),
    Case("تیبا", "brand alone", brand="tiba"),
    # 700M, not 300M: the cheapest clean-bodied Pride in the corpus is 325M, so
    # the original threshold was below market and the correct answer was an
    # empty result. The case is meant to test brand+budget filtering, not to
    # assert a price level that no longer exists.
    Case("پراید سالم زیر ۷۰۰ میلیون", "brand + budget", brand="pride",
         max_price=700 * MILLION),

    # Constraint queries — these mostly worked before; they guard against regression.
    Case("زیر ۵۰۰ میلیون", "budget ceiling", max_price=500 * MILLION),
    Case("بین ۱ تا ۲ میلیارد", "budget range", min_price=1 * BILLION, max_price=2 * BILLION),
    Case("شاسی بلند زیر ۲ میلیارد", "body + budget", body_type="suv", max_price=2 * BILLION),
    Case("هاچبک اتوماتیک", "body + gearbox", body_type="hatchback", transmission="اتوماتیک"),
    Case("دوگانه سوز", "fuel type", fuel="دوگانه"),
    Case("بدون رنگ زیر ۱ میلیارد", "condition + budget",
         min_body_grade=85, max_price=1 * BILLION),
    Case("کارکرد زیر ۱۰۰ هزار کیلومتر", "mileage ceiling", max_mileage=100_000),

    # Attribute queries — words that are in the listings but in no entity name.
    # These were the worst failure after entity lookups: with only character
    # n-grams to go on, «ماشین قرمز» scored on «ماشین» as much as on «قرمز» and
    # returned cars of every colour.
    Case("ماشین قرمز", "colour named in the query", body_color="قرمز"),
    Case("سراتو سفید", "entity + colour", brand="kia", body_color="سفید"),
    Case("پژو ۲۰۶ مشکی", "brand + model + colour", model_contains="206", body_color="مشکی"),
    Case("ماشین پانوراما", "feature in free text", text_contains="پانوراما"),
    Case("ماشین اقساطی", "instalment sale, morphological variant",
         text_contains="اقساط"),
    # Brand slugs that existed in the alias tables but in none of the data, so
    # these common cars were unreachable by name.
    Case("کوییک", "slug was 'quik' in code, 'quick' in the data", brand="quick"),
    Case("رانا", "Divar rows carry only the Persian marque", brand="rana"),

    # Nonsense must not return confident garbage. Everything below is something
    # this site does not sell; every one of them used to return five cars.
    Case("زیبیبیبیب", "gibberish", expect_empty=True),
    Case("فراری", "a marque we have no listing of", expect_empty=True),
    Case("دوچرخه", "not a car; appears only in a part-exchange note", expect_empty=True),
    Case("یخچال فریزر", "not a car", expect_empty=True),
    Case("خانه ویلایی", "not a car", expect_empty=True),
    Case("گوشی موبایل", "not a car", expect_empty=True),

    # Soft / semantic — judgement calls where no listing contains the query's
    # words. Reported separately because the "right" answer is a matter of
    # degree, and a small set of these is noisy by nature.
    Case("ماشین برای دختر دانشجو", "small cheap first car",
         max_price=700 * MILLION, soft=True),
    Case("ماشین خانواده جادار", "roomy family car", soft=True,
         body_type="crossover"),
    Case("ماشین ارزان برای شروع", "cheap starter car",
         max_price=600 * MILLION, soft=True),
    Case("خودرو اقتصادی و کم مصرف", "economical", max_price=900 * MILLION, soft=True),
    Case("ماشین برای مسافرکشی و اسنپ", "ride-hailing: cheap domestic",
         max_price=900 * MILLION, soft=True),
    Case("ماشین لوکس و گران", "luxury", min_price=4 * BILLION, soft=True),
    Case("ماشین شهری کوچک", "small city car", max_price=900 * MILLION, soft=True),
    Case("خودرو مطمئن و بی دردسر برای جاده", "reliable for long trips",
         max_mileage=200_000, soft=True),
]


def evaluate(search_fn: Callable[[str, int], list[dict]], k: int = 5, verbose: bool = False) -> dict[str, Any]:
    """Run every case through `search_fn(query, limit) -> results`."""
    rows: list[dict] = []

    for case in CASES:
        results = search_fn(case.query, k)
        checks = case.checks()

        if case.expect_empty:
            passed = len(results) == 0
            precision = 1.0 if passed else 0.0
        elif not results:
            precision = 0.0
        else:
            hits = 0
            for r in results[:k]:
                if all(fn(r) for _, fn in checks):
                    hits += 1
            precision = hits / min(len(results), k)

        rows.append({
            "case": case,
            "precision": precision,
            "n": len(results),
            "results": results[:k],
        })

    def mean(subset: list[dict]) -> float:
        return sum(r["precision"] for r in subset) / len(subset) if subset else 0.0

    hard_rows = [r for r in rows if not r["case"].soft]
    soft_rows = [r for r in rows if r["case"].soft]

    print(f"\n{'query':<34} {'p@5':>6}  {'n':>5}  note")
    print("-" * 78)
    for r in rows:
        case = r["case"]
        mark = "✓" if r["precision"] >= 0.8 else ("~" if r["precision"] > 0 else "✗")
        tag = " [soft]" if case.soft else ""
        print(f"{case.query[:33]:<34} {r['precision']:>5.0%} {mark} {r['n']:>4}  {case.note}{tag}")
        if verbose and r["precision"] < 0.8 and not case.expect_empty:
            for res in r["results"][:3]:
                price = _price(res)
                print(f"      → {str(res.get('title'))[:30]:32s} "
                      f"{res.get('brand')}/{res.get('model')} "
                      f"{(price or 0)/1e6:.0f}M")

    summary = {
        "precision_at_k_hard": mean(hard_rows),
        "precision_at_k_soft": mean(soft_rows),
        "n_hard": len(hard_rows),
        "n_soft": len(soft_rows),
        "fully_correct": sum(1 for r in hard_rows if r["precision"] >= 0.8),
    }
    print("-" * 78)
    print(f"HARD  precision@{k}: {summary['precision_at_k_hard']:.1%}   "
          f"({summary['fully_correct']}/{summary['n_hard']} cases ≥80%)")
    print(f"SOFT  precision@{k}: {summary['precision_at_k_soft']:.1%}   ({summary['n_soft']} cases)")
    return summary


def _legacy_search(corpus: list[dict]) -> Callable[[str, int], list[dict]]:
    """Phase 1 behaviour: rank the whole corpus, no retrieval stage.

    Kept so `--baseline` can reproduce the original numbers on demand.
    """
    from app.query import parse_query
    from app.rank import rank

    def run(query: str, limit: int) -> list[dict]:
        intent = parse_query(query, allow_live=False)
        return rank(corpus, intent, limit=limit)

    return run


def _current_search(corpus: list[dict], embeddings: bool = False) -> Callable[[str, int], list[dict]]:
    """Retrieval + ranking, as the API now serves it."""
    from app.query import parse_query
    from app.rank import rank
    from app.search import SearchIndex

    index = SearchIndex(corpus)
    if embeddings:
        index.load_embeddings()
    else:
        # Retrieval never fits the LSA fallback itself — the server builds it at
        # start-up — so an offline eval has to ask for it, or it would measure
        # lexical relevance alone and call it the current search.
        index.prepare_semantic()

    def run(query: str, limit: int) -> list[dict]:
        intent = parse_query(query, allow_live=False)
        found = index.retrieve(query, has_constraints=not intent.is_empty)
        if not found.codes:
            return []
        rows = [index.by_code[c] for c in found.codes]
        return rank(rows, intent, limit=limit, relevance=found.scores)

    return run


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate search quality")
    ap.add_argument("--verbose", action="store_true", help="show results for failing cases")
    ap.add_argument("--baseline", action="store_true", help="run Phase 1 (no retrieval stage)")
    ap.add_argument("--embeddings", action="store_true", help="enable semantic embeddings")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()

    conn = db.connect()
    db.init_db(conn)
    corpus = db.fetch_all(conn)
    conn.close()
    if not corpus:
        print("corpus is empty — run `python -m app.ingest` first", file=sys.stderr)
        raise SystemExit(1)
    label = "BASELINE (Phase 1, no retrieval)" if args.baseline else (
        "HYBRID + embeddings" if args.embeddings else "HYBRID (lexicon + TF-IDF + LSA)"
    )
    print(f"corpus: {len(corpus):,} listings   |   mode: {label}")

    search_fn = (
        _legacy_search(corpus) if args.baseline
        else _current_search(corpus, embeddings=args.embeddings)
    )
    evaluate(search_fn, k=args.k, verbose=args.verbose)


if __name__ == "__main__":
    main()

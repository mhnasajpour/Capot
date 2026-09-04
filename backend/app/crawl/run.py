"""Crawl every configured source into raw JSONL.

    python -m app.crawl.run --sources bama,divar --pages 60
    python -m app.crawl.run --sources divar --pages 25 --cities 1,2
    python -m app.crawl.run --sources sheypoor,karnameh --pages 400

Writes one raw record per line to `data/{source}_raw.jsonl`, exactly as the site
returned it. All parsing lives in the adapters and `normalize.py`, so a
normalization fix never costs another crawl.

Sources are crawled one after another and politely. They are not equally cheap:
Divar needs one detail request per listing (it fetches those with a small worker
pool, see `--concurrency`), while Sheypoor returns a listing's full attributes
inside the search response and so costs one request per 24 cars.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from ..config import BAMA_DETAIL_PATH, DATA_DIR, raw_path
from . import bama as _bama  # noqa: F401 - registers BamaSource
from . import divar as _divar  # noqa: F401 - registers DivarSource
from . import karnameh as _karnameh  # noqa: F401 - registers KarnamehSource
from . import sheypoor as _sheypoor  # noqa: F401 - registers SheypoorSource
from .base import available, get_source

log = logging.getLogger(__name__)

# Stratifying across brands gives deeper per-model cohorts than the
# undifferentiated feed, which skews to whatever was posted most recently.
BAMA_BRANDS = [
    "peugeot", "pride", "samand", "tiba", "quik", "dena", "rana", "shahin",
    "tara", "arisun", "saina", "hyundai", "kia", "toyota", "renault", "mazda",
    "benz", "bmw", "chery", "mvm", "jac", "lifan", "kmc", "bahman", "nissan",
]


def existing_ids(path: Path) -> set[str]:
    """Ids already in a raw file, so a resumed crawl doesn't re-fetch them."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = record.get("_id") or ((record.get("detail") or {}).get("code"))
            if code:
                ids.add(str(code))
    return ids


async def crawl_source(name: str, pages: int, append: bool = False, **options) -> int:
    """Crawl one source to its raw file. Returns the number of new records.

    `append` makes a crawl resumable. Divar needs one request per listing, so a
    full pass takes the best part of an hour — long enough that an interruption
    is likely, and starting from scratch each time is wasteful.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = raw_path(name)

    known = existing_ids(path) if append else set()
    if known:
        log.info("[%s] resuming; %d records already on disk", name, len(known))

    written = 0
    async with get_source(name)() as source:
        with path.open("a" if append else "w", encoding="utf-8") as fh:
            # Passed down so a source can skip a known id *before* paying for its
            # detail request — the whole point of resuming a Divar crawl.
            async for record in source.iter_raw(max_pages=pages, skip_ids=known, **options):
                if str(record.get("_id")) in known:
                    continue
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                if written % 200 == 0:
                    fh.flush()
                    log.info("[%s] %d new records", name, written)

    log.info("[%s] wrote %d new records -> %s", name, written, path)
    return written


async def crawl_bama_details(limit: int) -> int:
    """Fetch Bama detail records for a subset (specs, life_styles, tenure)."""
    if limit <= 0:
        return 0
    from .bama import BamaClient

    bama_raw = raw_path("bama")
    if not bama_raw.exists():
        return 0

    codes: list[str] = []
    with bama_raw.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = record.get("_id") or ((record.get("detail") or {}).get("code"))
            if code:
                codes.append(code)
            if len(codes) >= limit:
                break

    log.info("[bama] fetching %d detail records", len(codes))
    async with BamaClient() as client:
        found = await client.details(codes)

    with BAMA_DETAIL_PATH.open("w", encoding="utf-8") as fh:
        for code, data in found.items():
            fh.write(json.dumps({"code": code, "data": data}, ensure_ascii=False) + "\n")
    log.info("[bama] wrote %d detail records", len(found))
    return len(found)


async def run(sources: list[str], pages: int, details: int,
              cities: list[str] | None, append: bool = False,
              concurrency: int | None = None) -> None:
    for name in sources:
        options: dict = {}
        if name == "bama":
            options["brands"] = BAMA_BRANDS
        elif name == "divar":
            if cities:
                options["cities"] = cities
            if concurrency:
                options["concurrency"] = concurrency

        try:
            await crawl_source(name, pages, append=append, **options)
        except Exception as exc:  # noqa: BLE001 - one dead source must not stop the rest
            log.error("[%s] crawl failed: %s", name, exc)

        if name == "bama":
            await crawl_bama_details(details)


def main() -> None:
    ap = argparse.ArgumentParser(description="Crawl car listings into raw JSONL")
    ap.add_argument("--sources", default="bama", help=f"comma-separated; known: {','.join(available())}")
    ap.add_argument("--pages", type=int, default=60, help="pages per feed")
    ap.add_argument("--details", type=int, default=500, help="Bama detail records to fetch")
    ap.add_argument("--cities", default="", help="Divar city ids, comma-separated")
    ap.add_argument("--concurrency", type=int, default=2,
                    help="Divar detail requests in flight at once (default 2; "
                         "higher trips Divar's burst limit and loses listings)")
    ap.add_argument("--append", action="store_true",
                    help="resume: keep existing records and skip ids already fetched")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    cities = [c.strip() for c in args.cities.split(",") if c.strip()] or None
    asyncio.run(run(sources, args.pages, args.details, cities, args.append,
                    args.concurrency))


if __name__ == "__main__":
    main()

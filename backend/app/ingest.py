"""Load raw crawl output from every source into SQLite.

    python -m app.ingest
    python -m app.ingest --include-new

Reads `data/{source}_raw.jsonl` for each registered source, normalizes through
that source's adapter, resolves brands and models to a shared vocabulary, links
cross-site duplicates, and writes the result.

Idempotent, and re-parsing never needs a re-crawl — the raw files are kept
exactly as the sites returned them.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import db
from .canonical import BrandResolver, apply_duplicates
from .crawl import bama as _bama  # noqa: F401 - registers BamaSource
from .crawl import divar as _divar  # noqa: F401 - registers DivarSource
from .crawl import karnameh as _karnameh  # noqa: F401 - registers KarnamehSource
from .crawl import sheypoor as _sheypoor  # noqa: F401 - registers SheypoorSource
from .crawl.base import available, get_source
from .normalize import Listing, merge_detail

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DETAIL_PATH = DATA_DIR / "bama_details.jsonl"


def raw_path(source: str) -> Path:
    return DATA_DIR / f"{source}_raw.jsonl"


def is_brand_new(listing: Listing) -> bool:
    """Zero-kilometre cars (صفر کیلومتر) — not part of this product's market."""
    return listing.mileage_km == 0


def load_source(source: str) -> tuple[list[Listing], int]:
    """Parse one source's raw file. Returns (listings, failure_count)."""
    path = raw_path(source)
    if not path.exists():
        return [], 0

    adapter = get_source(source)()
    listings: dict[str, Listing] = {}
    failures = 0

    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                listing = adapter.normalize(raw)
                if listing is None:
                    failures += 1
                    continue
                listings[listing.code] = listing
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                failures += 1
                log.debug("[%s] line %d failed: %s", source, line_no, exc)

    log.info("[%s] parsed %d listings, %d failures", source, len(listings), failures)
    return list(listings.values()), failures


def apply_details(listings: list[Listing], path: Path = DETAIL_PATH) -> int:
    """Fold Bama detail records into the matching listings."""
    if not path.exists():
        return 0
    by_code = {listing.code: listing for listing in listings}
    merged = 0
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Detail records predate source-prefixed codes.
            listing = by_code.get(f"bama_{record.get('code')}") or by_code.get(record.get("code"))
            if listing and record.get("data"):
                merge_detail(listing, record["data"])
                merged += 1
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest raw crawl output into SQLite")
    ap.add_argument("--sources", default=",".join(available()),
                    help=f"comma-separated; known: {','.join(available())}")
    ap.add_argument(
        "--include-new", action="store_true",
        help="also ingest zero-kilometre cars (excluded by default; see below)",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    listings: list[Listing] = []
    failures = 0
    for source in sources:
        found, failed = load_source(source)
        listings.extend(found)
        failures += failed

    if not listings:
        log.error("nothing to ingest — run `python -m app.crawl.run` first")
        raise SystemExit(1)

    total = len(listings) + failures
    log.info("parsed %d listings across %d sources, %d failures (%.2f%%)",
             len(listings), len(sources), failures, 100 * failures / total if total else 0)

    merged = apply_details(listings)
    log.info("merged %d Bama detail records", merged)

    # Bama and Karnameh publish the brand slug and the Persian name together,
    # so they teach the mapping that lets the Persian-only sources — Divar and
    # Sheypoor — join the same cohorts.
    resolver = BrandResolver().learn(l.to_dict() for l in listings)
    unresolved = 0
    for listing in listings:
        resolver.resolve(listing)
        if not listing.brand:
            unresolved += 1
    if unresolved:
        log.warning("%d listings have no resolvable brand and will not be priced", unresolved)

    # Brand-new cars are deliberately out of scope. Iran's new-car market is
    # dual-priced — a factory/allocation price and a much higher free-market
    # price coexist for the same model — so "market value" is not one number and
    # every comparison against it produces phantom 60%-below-market bargains.
    # The health engine is also meaningless at 0 km: body status is always
    # 'بدون رنگ' and there is no wear to assess. This product is about used cars.
    if not args.include_new:
        before = len(listings)
        listings = [listing for listing in listings if not is_brand_new(listing)]
        log.info("excluded %d brand-new (0 km) listings", before - len(listings))

    apply_duplicates(listings)

    conn = db.connect()
    db.init_db(conn)
    written = db.upsert_listings(conn, listings)
    stale = db.prune_missing(conn, [listing.code for listing in listings])
    log.info("wrote %d rows to %s (pruned %d stale)", written, db.DB_PATH, stale)
    log.info("corpus: %s", db.stats(conn))
    conn.close()


if __name__ == "__main__":
    main()

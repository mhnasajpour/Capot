"""SQLite storage for normalized listings, price estimates and LLM enrichment.

SQLite (not Postgres) is deliberate: the whole corpus is a few thousand rows, and
shipping a single self-contained file means a reviewer can clone the repo and run
the app with no database to provision.

Three tables:
  listings   — normalized facts from the crawl (one row per ad)
  pricing    — fair-price model output, refreshed whenever the model retrains
  enrichment — LLM-extracted structured flags from free-text descriptions
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH
from .lexicon import BRAND_ALIASES, fold
from .normalize import Listing

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    code            TEXT PRIMARY KEY,
    url             TEXT,
    title           TEXT,
    brand           TEXT,
    brand_fa        TEXT,
    model           TEXT,
    trim            TEXT,
    trim_en         TEXT,
    year            INTEGER,
    year_display    INTEGER,
    year_calendar   TEXT,
    age             INTEGER,
    mileage_km      INTEGER,
    price_toman     INTEGER,
    is_negotiable   INTEGER,
    price_type      TEXT,
    body_status     TEXT,
    body_grade      INTEGER,
    body_type       TEXT,
    body_type_fa    TEXT,
    transmission    TEXT,
    fuel            TEXT,
    body_color      TEXT,
    inside_color    TEXT,
    seller          TEXT,
    dealer_name     TEXT,
    dealer_score    REAL,
    dealer_ad_count INTEGER,
    authenticated   INTEGER,
    city            TEXT,
    location        TEXT,
    description     TEXT,
    image           TEXT,
    image_count     INTEGER,
    engine_volume_l REAL,
    power_hp        REAL,
    acceleration_s  REAL,
    consumption_l100 REAL,
    modified_date   TEXT,
    life_styles     TEXT,
    source          TEXT DEFAULT 'bama',
    model_fa        TEXT,
    insurance_months INTEGER,
    chassis_status  TEXT,
    duplicate_of    TEXT
);

CREATE INDEX IF NOT EXISTS idx_listings_cohort ON listings (brand, model, trim_en, year);
CREATE INDEX IF NOT EXISTS idx_listings_model  ON listings (brand, model, year);
CREATE INDEX IF NOT EXISTS idx_listings_price  ON listings (price_toman);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings (source);

CREATE TABLE IF NOT EXISTS pricing (
    code             TEXT PRIMARY KEY,
    fair_price       INTEGER,   -- model's market estimate, toman
    price_delta_pct  REAL,      -- (asking - fair) / fair * 100; NULL when negotiable
    confidence       REAL,      -- 0-1, driven by comparable depth and cohort spread
    n_comparables    INTEGER,
    cohort_level     TEXT,      -- 'trim' | 'model' | 'global'
    price_flag       TEXT,      -- 'ok' | 'deposit' (voucher/pre-sale figure)
    FOREIGN KEY (code) REFERENCES listings (code)
);

CREATE TABLE IF NOT EXISTS enrichment (
    code            TEXT PRIMARY KEY,
    red_flags       TEXT,   -- JSON array of {code, label_fa, severity}
    positives       TEXT,   -- JSON array of strings
    extracted       TEXT,   -- JSON object of structured fields found in the text
    model           TEXT,   -- which LLM produced this
    FOREIGN KEY (code) REFERENCES listings (code)
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that postdate an existing database file.

    `CREATE TABLE IF NOT EXISTS` is a no-op once the table exists, so a column
    added to SCHEMA never reaches a db built before it. Ingest rebuilds every
    row but not the table, so without this an older cars.db fails on the first
    upsert with 'table listings has no column named ...'.
    """
    have = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
    for column, ddl in (("chassis_status", "TEXT"),):
        if column not in have:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {column} {ddl}")
            log.info("db: added listings.%s", column)


_LISTING_COLUMNS = [
    "code", "url", "title", "brand", "brand_fa", "model", "trim", "trim_en",
    "year", "year_display", "year_calendar", "age", "mileage_km", "price_toman",
    "is_negotiable", "price_type", "body_status", "body_grade", "body_type",
    "body_type_fa", "transmission", "fuel", "body_color", "inside_color",
    "seller", "dealer_name", "dealer_score", "dealer_ad_count", "authenticated",
    "city", "location", "description", "image", "image_count",
    "engine_volume_l", "power_hp", "acceleration_s", "consumption_l100",
    "modified_date", "life_styles", "source", "model_fa", "insurance_months",
    "chassis_status", "duplicate_of",
]


def upsert_listings(conn: sqlite3.Connection, listings: Iterable[Listing]) -> int:
    """Insert or replace listings. Returns the number written."""
    placeholders = ",".join("?" for _ in _LISTING_COLUMNS)
    sql = f"INSERT OR REPLACE INTO listings ({','.join(_LISTING_COLUMNS)}) VALUES ({placeholders})"

    rows = []
    for listing in listings:
        data = listing.to_dict()
        data["life_styles"] = json.dumps(data.get("life_styles") or [], ensure_ascii=False)
        data["duplicate_of"] = json.dumps(data.get("duplicate_of") or [], ensure_ascii=False)
        data["is_negotiable"] = int(bool(data["is_negotiable"]))
        data["authenticated"] = int(bool(data["authenticated"]))
        rows.append(tuple(data[col] for col in _LISTING_COLUMNS))

    conn.executemany(sql, rows)
    conn.commit()
    return len(rows)


def prune_missing(conn: sqlite3.Connection, keep_codes: Iterable[str]) -> int:
    """Drop listings that are no longer in the crawl, plus their derived rows.

    Ingest is a full rebuild from the raw files, so anything already in the table
    that this pass did not produce is stale — a listing that has since been
    delisted, or a leftover from an earlier crawl. Without this, `INSERT OR
    REPLACE` silently accumulates them and every corpus statistic drifts.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _keep (code TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _keep")
    conn.executemany("INSERT OR IGNORE INTO _keep (code) VALUES (?)",
                     [(c,) for c in keep_codes])

    # Children first: pricing and enrichment carry FK references to listings and
    # have no ON DELETE CASCADE, so removing the parent first fails outright.
    for table in ("pricing", "enrichment"):
        conn.execute(
            f"DELETE FROM {table} WHERE code NOT IN (SELECT code FROM _keep)"
        )
    removed = conn.execute(
        "DELETE FROM listings WHERE code NOT IN (SELECT code FROM _keep)"
    ).rowcount
    conn.commit()
    return removed


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for key in ("life_styles", "duplicate_of"):
        if isinstance(data.get(key), str):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                data[key] = []
    for key in ("is_negotiable", "authenticated"):
        if key in data and data[key] is not None:
            data[key] = bool(data[key])
    for key in ("red_flags", "positives", "extracted"):
        if data.get(key) and isinstance(data[key], str):
            try:
                data[key] = json.loads(data[key])
            except json.JSONDecodeError:
                data[key] = None

    # Divar listings sometimes carry only the Persian marque («رانا») and no
    # latin slug. Brand retrieval and every brand filter key off the slug, so
    # without this those cars are in the corpus but unreachable: searching
    # «رانا» answered "no such car" over eleven Ranas. Backfilled here because
    # this is the one function every read path goes through.
    if not data.get("brand") and data.get("brand_fa"):
        slug = BRAND_ALIASES.get(fold(data["brand_fa"]))
        if slug:
            data["brand"] = slug
    return data


# Listings joined with everything we've derived about them. This is the single
# read path used by search, detail and compare so they can never disagree.
_FULL_SELECT = """
SELECT l.*,
       p.fair_price, p.price_delta_pct, p.confidence, p.n_comparables, p.cohort_level, p.price_flag,
       e.red_flags, e.positives, e.extracted
FROM listings l
LEFT JOIN pricing p    ON p.code = l.code
LEFT JOIN enrichment e ON e.code = l.code
"""


def fetch_all(conn: sqlite3.Connection) -> list[dict]:
    return [_row_to_dict(r) for r in conn.execute(_FULL_SELECT)]


def fetch_one(conn: sqlite3.Connection, code: str) -> dict | None:
    row = conn.execute(f"{_FULL_SELECT} WHERE l.code = ?", (code,)).fetchone()
    return _row_to_dict(row) if row else None


def fetch_many(conn: sqlite3.Connection, codes: list[str]) -> list[dict]:
    if not codes:
        return []
    marks = ",".join("?" for _ in codes)
    rows = conn.execute(f"{_FULL_SELECT} WHERE l.code IN ({marks})", codes)
    return [_row_to_dict(r) for r in rows]


def replace_pricing(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    """Overwrite the pricing table with a fresh set of estimates."""
    conn.execute("DELETE FROM pricing")
    payload = [
        (
            r["code"], r.get("fair_price"), r.get("price_delta_pct"),
            r.get("confidence"), r.get("n_comparables"), r.get("cohort_level"),
            r.get("price_flag"),
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT INTO pricing (code, fair_price, price_delta_pct, confidence,"
        " n_comparables, cohort_level, price_flag) VALUES (?,?,?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return len(payload)


def upsert_enrichment(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    payload = [
        (
            r["code"],
            json.dumps(r.get("red_flags") or [], ensure_ascii=False),
            json.dumps(r.get("positives") or [], ensure_ascii=False),
            json.dumps(r.get("extracted") or {}, ensure_ascii=False),
            r.get("model"),
        )
        for r in rows
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO enrichment (code, red_flags, positives, extracted, model)"
        " VALUES (?,?,?,?,?)",
        payload,
    )
    conn.commit()
    return len(payload)


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """Corpus summary — used by the API's /api/stats and by the demo narrative."""
    def scalar(sql: str) -> Any:
        return conn.execute(sql).fetchone()[0]

    total = scalar("SELECT COUNT(*) FROM listings")
    negotiable = scalar("SELECT COUNT(*) FROM listings WHERE is_negotiable = 1")
    return {
        "total": total,
        "negotiable": negotiable,
        "negotiable_pct": round(100 * negotiable / total, 1) if total else 0,
        "priced": total - negotiable,
        "with_estimate": scalar("SELECT COUNT(*) FROM pricing WHERE fair_price IS NOT NULL"),
        "enriched": scalar("SELECT COUNT(*) FROM enrichment"),
        "brands": scalar("SELECT COUNT(DISTINCT brand) FROM listings"),
        "cities": scalar("SELECT COUNT(DISTINCT city) FROM listings"),
        "by_source": {
            r["source"]: r["n"]
            for r in conn.execute(
                "SELECT COALESCE(source,'bama') source, COUNT(*) n FROM listings GROUP BY source"
            )
        },
        "cross_listed": scalar(
            "SELECT COUNT(*) FROM listings WHERE duplicate_of IS NOT NULL AND duplicate_of != '[]'"
        ),
    }

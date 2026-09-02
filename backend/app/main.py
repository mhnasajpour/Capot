"""FastAPI application.

    uvicorn app.main:app --reload

Endpoints:
    GET /api/search?q=…            natural-language search, ranked, explained, paged
    GET /api/car/{code}            one listing with comparables
    GET /api/compare?codes=a,b     side-by-side comparison
    GET /api/appraise?q=…          price a car the user owns, from prose and/or a form
    GET /api/features              the filterable feature catalogue
    GET /api/stats                 corpus summary (drives the landing page)
    GET /api/health                liveness + LLM/cache status

The whole corpus is a few thousand rows, so search loads it into memory once and
ranks in process. That keeps the ranking logic in plain Python — readable and
explainable — instead of pushing it into SQL where the reasoning would vanish.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import joblib
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import appraise as appraisal
from . import db, lexicon, normalize, pricing
from .config import settings
from .features import Filters, build_catalogue, count_features, effective_price
from .health import health_band, score_listing
from .llm import cache_stats
from .query import parse_query
from .rank import Ranking, order_all
from .search import SearchIndex

log = logging.getLogger(__name__)

_corpus: list[dict] = []
_by_code: dict[str, dict] = {}
_index: SearchIndex | None = None
_catalogue: dict[str, Any] = {}

# Everything /api/appraise needs to value a car that is not in the corpus: the
# trained pipeline, the comparable-depth counts, the corpus bucketed by model,
# and the model's own held-out error. All derived once at start-up, because none
# of them change while the process is alive — the same reasoning behind
# `_catalogue`.
_model: Any = None
_metrics: dict[str, float] = {}
_cohort_by_model_year: dict = {}
_cohort_by_model: dict = {}
_cohort_by_brand: dict = {}
_by_model: dict[tuple, list[dict]] = {}
# Commonest gearbox, fuel, body type and city, for filling what a person leaves
# blank. A blank categorical is not neutral to the model — see
# `appraise.IMPUTED_FEATURES`.
_modes: dict[str, str] = {}


@dataclass
class _CachedSearch:
    """Everything about one search that does not depend on which page you want.

    Retrieval and ranking answer a *query*; `limit`/`offset` only choose a window
    onto the answer. The result grid scrolls, so the same query arrives once per
    screenful — and re-retrieving and re-ordering the corpus for each of them was
    half a second of work per scroll to produce twenty-four cards.

    `Ranking` holds references to corpus rows, so an entry is a list of pointers
    and a counts dict, not a copy of the results.
    """

    ranking: Ranking
    retrieval: dict[str, Any]
    features: dict[str, Any]
    intent: dict[str, Any]


# Small on purpose: it exists to make scrolling one result set cheap, not to
# remember every search the server has ever seen. A handful of readers scrolling
# at once fit comfortably.
_CACHE_SIZE = 24
_cache: "OrderedDict[tuple, _CachedSearch]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key: tuple) -> _CachedSearch | None:
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            _cache.move_to_end(key)
        return cached


def _cache_put(key: tuple, value: _CachedSearch) -> None:
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)


def load_corpus(use_embeddings: bool = True) -> None:
    """Load listings into memory and build the search index."""
    global _corpus, _by_code, _index, _catalogue
    global _model, _metrics, _cohort_by_model_year, _cohort_by_model, _by_model
    global _cohort_by_brand, _modes
    conn = db.connect()
    db.init_db(conn)
    _corpus = db.fetch_all(conn)
    _by_code = {r["code"]: r for r in _corpus}
    conn.close()
    log.info("loaded %d listings into memory", len(_corpus))

    # The filter catalogue is derived from the corpus, not hand-written, so it
    # can never list a brand we do not stock or miss one we just ingested. Built
    # once here because the corpus never changes while the process is alive.
    _cache.clear()
    _catalogue = build_catalogue(_corpus) if _corpus else {}
    if _corpus:
        log.info("feature catalogue: %d features", len(_catalogue["features"]))

    _load_price_model()
    _cohort_by_model_year, _cohort_by_model, _cohort_by_brand = appraisal.cohort_counts(_corpus)
    _by_model = appraisal.index_by_model(_corpus)
    _modes = appraisal.corpus_modes(_corpus)

    if not _corpus:
        _index = None
        return

    # The lexicon is rebuilt from the corpus so new brands and models become
    # searchable the moment they are ingested — nothing to hand-maintain.
    lex = lexicon.build(_corpus)
    lexicon.save(lex)
    _index = SearchIndex(_corpus, lex)
    if use_embeddings:
        # In a thread, because fitting the LSA fallback takes seconds on a cold
        # cache and the API should answer immediately. Until it finishes,
        # retrieval quietly runs on lexical relevance alone — which it already
        # knows how to do — rather than making the first vague search wait for
        # a matrix decomposition, as it used to.
        threading.Thread(
            target=_prepare_semantic, args=(_index,), name="semantic-index", daemon=True
        ).start()


def _load_price_model() -> None:
    """Load the trained regressor for live appraisal.

    Every other price in this app was computed offline and written to the
    `pricing` table, so until now the server never needed the model itself. An
    appraisal is the one thing that cannot be precomputed — the car does not
    exist until someone describes it.

    A missing or unreadable model file takes down `/api/appraise` alone and
    leaves search, detail and compare exactly as they were, which is the same
    bargain `llm.py` strikes with a dead proxy: a feature that cannot work
    should fail on its own, not take the page with it.
    """
    global _model, _metrics
    _metrics = appraisal.load_metrics()
    try:
        _model = joblib.load(pricing.MODEL_PATH)
        log.info("price model loaded for appraisal (%s)", pricing.MODEL_PATH.name)
    except Exception as exc:  # noqa: BLE001 - any failure here is the same failure
        _model = None
        log.warning("price model unavailable, /api/appraise disabled: %s", exc)


def _prepare_semantic(index: SearchIndex) -> None:
    signal = index.prepare_semantic()
    log.info("semantic relevance ready: %s", signal)
    # Searches answered during the build were retrieved on lexical relevance
    # alone. They are honest results, but they are not the ones this index now
    # gives, and a cached one would outlive the difference.
    with _cache_lock:
        _cache.clear()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_corpus()
    yield


app = FastAPI(
    title="Capot API",
    description="Fair price, health and need-fit for the Iranian used-car market",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return {
        "status": "ok",
        "listings_loaded": len(_corpus),
        "search": {
            "index_ready": _index is not None,
            # Built in the background at start-up, so "pending" is a real state
            # for the first few seconds of a cold run.
            "semantic": _semantic_state(),
            "brands": len(_index.lexicon.brands) if _index else 0,
            "models": len(_index.lexicon.models) if _index else 0,
        },
        "llm": cache_stats(),
    }


def _semantic_state() -> str:
    if _index is None:
        return "none"
    if _index.embeddings is not None:
        return "embeddings"
    return "lsa" if _index.semantic_ready else "pending"


@app.get("/api/stats")
def api_stats() -> dict[str, Any]:
    """Corpus summary. The negotiable share is the product's headline number."""
    conn = db.connect()
    stats = db.stats(conn)
    conn.close()

    priced_estimates = [
        r for r in _corpus if r.get("is_negotiable") and r.get("fair_price")
    ]
    stats["hidden_prices_recovered"] = len(priced_estimates)
    return stats


@app.get("/api/features")
def api_features() -> dict[str, Any]:
    """The filterable feature catalogue that drives the filter panel.

    Every value here was derived from the corpus at start-up, so the panel can
    never offer a brand we do not stock or a colour no car has.
    """
    return _catalogue or {"total": 0, "groups": [], "features": []}


@app.get("/api/search")
def api_search(
    q: str = Query("", description="natural-language query, Persian or English"),
    limit: int = Query(24, ge=1, le=100, description="page size"),
    offset: int = Query(0, ge=0, description="how many ranked results to skip"),
    live_llm: bool = Query(False, description="allow a live LLM call to parse the query"),
    # Explicit feature selections. Lists are comma-separated, matching
    # /api/compare?codes=a,b — and a GET keeps a filtered search shareable as a
    # URL, which a POST body could not.
    brands: str = Query("", description="comma-separated brand slugs"),
    models: str = Query("", description="comma-separated 'brand/model' keys"),
    body_types: str = Query(""),
    transmissions: str = Query(""),
    fuels: str = Query(""),
    colors: str = Query(""),
    cities: str = Query(""),
    sellers: str = Query(""),
    sources: str = Query(""),
    price_min: str = Query(""),
    price_max: str = Query(""),
    year_min: str = Query(""),
    year_max: str = Query(""),
    mileage_min: str = Query(""),
    mileage_max: str = Query(""),
    engine_min: str = Query(""),
    engine_max: str = Query(""),
    consumption_max: str = Query(""),
    min_health: str = Query(""),
    paint: str = Query("", description="paint band: clean|near_clean|one_spot|few_spots"),
    below_market: bool = Query(False),
    inspected: bool = Query(False),
    has_image: bool = Query(False),
    sort: str = Query("rank", description="rank|price_asc|price_desc|year_desc|mileage_asc|health_desc|discount_desc"),
) -> dict[str, Any]:
    """Retrieve the cars the query is about, then rank within them.

    Retrieval decides relevance (entity match, then text, then semantic) and
    ranking decides order. Keeping those separate is what stops an unrecognised
    query from silently returning whatever happens to be the best bargain.

    Ticked features are overlaid onto the parsed intent before either stage, so
    they narrow the same way a typed constraint does — and take precedence over
    it, because the buyer can see a checkbox but not a parser.

    Paging comes last, after retrieval and ranking, so a page is always a window
    onto one globally ordered list. `total` counts everything that survived both
    stages — note that for text and semantic queries retrieval hands over at most
    `search.CANDIDATE_POOL` listings, so it is a count of what is reachable, not
    of every listing in the corpus that could conceivably match.

    Only the page itself is explained, and the ordering behind it is cached: the
    grid scrolls, so page 2 of a search is a slice of work already done rather
    than the whole search over again.
    """
    filters = Filters.from_params(
        brands=brands, models=models, body_types=body_types,
        transmissions=transmissions, fuels=fuels, colors=colors, cities=cities,
        sellers=sellers, sources=sources, price_min=price_min, price_max=price_max,
        year_min=year_min, year_max=year_max, mileage_min=mileage_min,
        mileage_max=mileage_max, engine_min=engine_min, engine_max=engine_max,
        consumption_max=consumption_max, min_health=min_health, paint=paint,
        below_market=below_market, inspected=inspected, has_image=has_image,
        sort=sort,
    )

    if _index is None:
        intent = filters.apply_to(parse_query(q, allow_live=live_llm))
        return {"query": q, "intent": intent.to_dict(), "count": 0, "total": 0,
                "limit": limit, "offset": offset, "has_more": False,
                "retrieval": {"mode": "empty"}, "applied": filters.to_dict(),
                "features": {}, "results": []}

    cached = _search_once(q, filters, live_llm)
    results = cached.ranking.page(offset, limit)
    total = len(cached.ranking)

    return {
        "query": q,
        "intent": cached.intent,
        "retrieval": cached.retrieval,
        "applied": filters.to_dict(),
        # Leave-one-out counts over the retrieved set, so the panel can show how
        # many cars each remaining choice would add without zeroing the siblings
        # of whatever is already ticked.
        #
        # Only on the first page. Every value of every feature is tens of
        # kilobytes of JSON that describe the *search*, not the page, and a
        # scrolling grid asks for page after page of the same search — the panel
        # already has these and would only redraw them identically.
        "features": cached.features if offset == 0 else None,
        # `count` is this page, `total` is the whole result set. The grid draws
        # the first; `has_more` is what tells it whether to fetch again.
        "count": len(results),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(results) < total,
        "results": results,
    }


def _search_once(q: str, filters: Filters, live_llm: bool) -> _CachedSearch:
    """Retrieve, filter and order — once per distinct search, not per page.

    Keyed on everything that decides *which* cars come back and in what order.
    `limit` and `offset` are deliberately not part of that: they choose a window
    onto this result, which is the whole reason it is worth keeping.
    """
    key = (q.strip(), live_llm, repr(filters))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    intent = filters.apply_to(parse_query(q, allow_live=live_llm))
    # Ticked features count as constraints. Without this a mistyped query plus a
    # ticked brand falls into retrieval's `nonsense` branch and answers nothing,
    # even though the buyer gave us a perfectly good filter to honour.
    found = _index.retrieve(q, has_constraints=not intent.is_empty)
    rows = [_by_code[c] for c in found.codes if c in _by_code]

    cached = _CachedSearch(
        ranking=order_all(rows, intent, relevance=found.scores, sort=filters.sort),
        retrieval=found.to_dict(),
        features=count_features(rows, intent),
        intent=intent.to_dict(),
    )
    _cache_put(key, cached)
    return cached


def _comparables(row: dict, limit: int = 6) -> list[dict]:
    """Priced listings of the same model and year — the evidence behind the
    fair-price estimate, so the user can audit the number themselves."""
    peers = [
        r for r in _corpus
        if r["code"] != row["code"]
        and r.get("brand") == row.get("brand")
        and r.get("model") == row.get("model")
        and r.get("price_toman")
    ]
    # Closest by year first, then by mileage.
    peers.sort(key=lambda r: (
        abs((r.get("year") or 0) - (row.get("year") or 0)),
        abs((r.get("mileage_km") or 0) - (row.get("mileage_km") or 0)),
    ))
    return [
        {
            "code": p["code"], "title": p["title"], "year_display": p.get("year_display"),
            "mileage_km": p.get("mileage_km"), "price_toman": p.get("price_toman"),
            "body_status": p.get("body_status"), "url": p.get("url"),
            "source": p.get("source"),
        }
        for p in peers[:limit]
    ]


def _detail_payload(row: dict) -> dict[str, Any]:
    health = score_listing(row)
    band_fa, band_en = health_band(health.score)
    price, estimated = effective_price(row)
    return {
        **row,
        "price_block": {
            "asking": row.get("price_toman"),
            "effective": price,
            "is_estimated": estimated,
            "is_negotiable": bool(row.get("is_negotiable")),
            "fair_price": row.get("fair_price"),
            "delta_pct": row.get("price_delta_pct"),
            "confidence": row.get("confidence"),
            "n_comparables": row.get("n_comparables"),
            "cohort_level": row.get("cohort_level"),
            "price_flag": row.get("price_flag"),
        },
        "health": {
            "score": health.score,
            "band_fa": band_fa,
            "band_en": band_en,
            "factors": [f.to_dict() for f in health.factors],
        },
        "comparables": _comparables(row),
    }


@app.get("/api/car/{code}")
def api_car(code: str) -> dict[str, Any]:
    row = _by_code.get(code)
    if not row:
        raise HTTPException(status_code=404, detail="listing not found")
    return _detail_payload(row)


@app.get("/api/appraise")
def api_appraise(
    q: str = Query("", description="the car described in the owner's own words"),
    # The same fields, stated rather than parsed. Every one of these overrides
    # whatever `q` said, because the user can see a form field and cannot see a
    # parser — the rule `features.Filters.apply_to` already establishes.
    brand: str = Query(""),
    model: str = Query("", description="model slug, not 'brand/model'"),
    year: str = Query("", description="Gregorian or Jalali; Jalali is converted"),
    mileage: str = Query(""),
    transmission: str = Query(""),
    fuel: str = Query(""),
    body_status: str = Query(""),
    body_type: str = Query(""),
    color: str = Query(""),
    city: str = Query(""),
    seller: str = Query(""),
    engine: str = Query("", description="engine volume in litres"),
) -> dict[str, Any]:
    """Value a car the user owns, and show the live ads for cars like it.

    A GET, and everything in the query string, for the two reasons the rest of
    this API is: an appraisal is a thing people send each other, and the answer
    has to survive a reload. The description travels in `q` like a search does.

    The response's `status` is what to read first. Only `ok` carries a price;
    `unknown_car` and `need_year` carry a reason and no number, because there is
    no honest way to value a car we cannot name or date.
    """
    if _model is None or not _corpus:
        raise HTTPException(
            status_code=503,
            detail="the price model is not loaded; run `python -m app.pricing --train`",
        )

    def as_int(value: str) -> int | None:
        try:
            return int(float(value)) if value else None
        except (TypeError, ValueError):
            return None

    def as_float(value: str) -> float | None:
        try:
            return float(value) if value else None
        except (TypeError, ValueError):
            return None

    # A Jalali year typed into the form is converted the same way the crawl
    # converts one read off a listing, so «۱۳۹۵» and «2016» mean one car.
    stated_year, _calendar = normalize.parse_year(year) if year else (None, None)

    explicit = appraisal.CarInput(
        brand=brand.strip().lower() or None,
        model=model.strip().lower() or None,
        year=stated_year,
        mileage_km=as_int(mileage),
        transmission=transmission.strip() or None,
        fuel=fuel.strip() or None,
        body_status=body_status.strip() or None,
        body_type=body_type.strip() or None,
        body_color=color.strip() or None,
        city=city.strip() or None,
        seller=seller.strip() or None,
        engine_volume_l=as_float(engine),
    )
    # The cohort counts double as the tie-break when one name resolves to
    # several slugs: «۲۰۶» is both `206ir` and `206`, and the estimate must be
    # backed by whichever of them the corpus actually stocks.
    parsed = (
        appraisal.parse_description(q, _index.lexicon, _cohort_by_model)
        if _index
        else appraisal.CarInput()
    )
    car = appraisal.merge(parsed, explicit)
    # The description survives the merge whatever else the form said: it is the
    # evidence the risk scanner and the health score read, not just a source of
    # field values.
    car.description = q.strip() or None

    result = appraisal.appraise(
        car,
        _model,
        by_model_year=_cohort_by_model_year,
        by_model_counts=_cohort_by_model,
        by_brand_counts=_cohort_by_brand,
        by_model=_by_model,
        metrics=_metrics,
        modes=_modes,
    )
    # What the parser understood on its own, so the form can show it filled in
    # and the user can correct it rather than guess why a number looks wrong.
    result["parsed"] = parsed.to_dict()
    return result


@app.get("/api/compare")
def api_compare(codes: str = Query(..., description="comma-separated listing codes")) -> dict[str, Any]:
    wanted = [c.strip() for c in codes.split(",") if c.strip()][:4]
    rows = [_by_code[c] for c in wanted if c in _by_code]
    if not rows:
        raise HTTPException(status_code=404, detail="no matching listings")
    return {"count": len(rows), "cars": [_detail_payload(r) for r in rows]}

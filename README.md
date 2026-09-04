# Capot · کاپوت

### *Capot* is the bonnet of a car, and the name is the promise: every listing is a closed hood, and the product's whole job is to open it.



## The problem

Buying a used car in Iran means answering three questions no listing site answers:
**is this price fair?**, **is this car healthy?**, **does it fit what I need?**
Asking prices are published; market value isn't. «دور رنگ», «موتور تعویض شده»,
«سند در رهن» are buried in prose. And you can filter by brand and year, but not ask
for "a first family car under 800M that's cheap to run."

A fourth problem makes the first one worse:

> **2,621 of the 22,820 used cars in this corpus publish no price at all** — they say
> «توافقی». On every existing site those are a dead end: unsearchable, unfilterable,
> uncomparable. That's 11.5% of supply, invisible to anyone shopping by budget.

## What Capot does

- **Prices the cars that have no price.** A gradient-boosted model trained on the
  19,281 usable priced listings values every hidden-price car and ranks it alongside
  everything else with a confidence band — recovering **2,598 listings that
  published none**.
- **Scores health 0–100** from paint condition, mileage-for-age, seller trust,
  inspection, chassis, insurance and risk phrases mined from the ad text. Every
  point is itemised.
- **Understands need.** Ask in plain Persian; the query becomes structured intent
  and results rank on value × health × fit, with reasons printed on each card.
- **Or filter instead.** 19 features, each measured for corpus coverage before being
  exposed, with live leave-one-out counts. Both doors share one filter gate.

## Results

**Fair price**, on a 20% held-out split of 19,281 trainable rows —
median APE **7.6%**, MAPE **14.4%**, R² on log(price) **0.929**.

**Search**, on 38 labelled Persian queries — precision@5 of **93.2%** (35/38 cases
≥80%), against **42.1%** (14/38) for ranking the whole corpus with no retrieval stage.

One average would hide the thing most worth knowing:

| Source | Held out | MAPE | Median APE | Avg confidence |
|---|---|---|---|---|
| Bama | 1,768 | **10.2%** | 6.0% | 0.595 |
| Sheypoor | 1,653 | **17.4%** | 9.1% | 0.399 |
| Divar | 373 | **18.5%** | 10.5% | 0.366 |
| Karnameh | 63 | **26.1%** | 15.2% | 0.218 |

Bama is twice as easy to price, and the cause is measurable: it is the only source
publishing engine size, power, consumption and seller rating, on ~90% of rows.
So confidence is discounted by the evidence a listing actually carries, not just by
how many comparables it has. **Adding sources raised average error** — three
quarters of the corpus now publishes less about itself than Bama does. Publishing
one blended number at uniform confidence would hide exactly that.

Two honest caveats on the search number. Two of the three remaining failures are the
test being wrong («یخچال فریزر» correctly retrieves a refrigerated Pride pickup —
that's a car); the third is real, since the char n-grams that handle Persian
morphology without a stemmer also match خانه inside کارخانه. And on 8 deliberately
vague queries the numbers **invert** — 72.5% without retrieval, 52.5% with it. The
gates that stop «فراری» also constrain lifestyle wording; the fix is a stronger
semantic signal, not weaker gates.

## Architecture

```
   Bama        Sheypoor      Divar      Karnameh      (source adapters,
  JSON API     JSON:API     JSON API   _next/data      crawl once → JSONL)
  9,798 rows  10,839 rows  1,857 rows   326 rows
      └────────────┴──────┬─────┴────────────┘
                          ▼
   normalize.py ── mixed Jalali/Gregorian years, 'صفر کیلومتر' vs '240,000 km',
        │          Persian digits, negotiable → NULL (never 0),
        │          model/trim recovered from the URL slug
        ▼
   canonical.py ── Persian ↔ latin brand/model mapping, learned from the sources
        │          that publish both halves; duplicates linked across sites
        ▼
     SQLite ──── listings · pricing · enrichment      22,820 used cars
        │
        ├── pricing.py  HistGradientBoosting on log(price), cohort confidence
        ├── health.py   deterministic, itemised risk scoring
        ├── enrich.py   risk extraction from ad text (batch, cached to disk)
        ├── lexicon.py  brand/model vocabulary derived from the corpus
        ├── search.py   entity match → TF-IDF → semantic (retrieval)
        ├── features.py the filterable feature catalogue + the one filter gate
        └── rank.py     value × health × fit, within the retrieved set
        ▼
   FastAPI  →  React + Tailwind (RTL Persian, English toggle)
```

Each site is a `Source` adapter owning exactly two things — fetch raw records, turn
one into a `Listing`. Everything downstream sees only `Listing`, so adding a site
never touches product logic.

## Data sources

| Source | Rows | Requests/car | What it uniquely gives |
|---|---|---|---|
| **Bama** | 9,798 | ~0.03 | Engine size, power, consumption, dealer rating; latin brand slug beside the Persian |
| **Sheypoor** | 10,839 | 0.04 | Full spec sheet inline — no detail request; *declares* وضعیت بدنه; only source with chassis condition |
| **Divar** | 1,857 | ~1.0 | Insurance validity and technical-inspection status |
| **Karnameh** | 326 | 0.05 | Typed integers instead of display strings; `brand_name_en`; inspection flag |

Coverage differs sharply, and that difference is what the per-source error table
measures:

| Field | Bama | Sheypoor | Divar | Karnameh | Corpus |
|---|---|---|---|---|---|
| Engine size / consumption | 92% / 89% | 0% | 0% | 0% | 39% / 38% |
| Body type | 100% | 0% | 0% | 0% | 43% |
| Body status | 100% | 99% | 53% | 0% | 94% |
| Chassis status | 0% | 79% | 0% | 0% | 37% |
| Insurance months | 0% | 0% | 85% | 0% | 7% |
| Description | 88% | 100% | 100% | 100% | 95% |

**Five sites were attempted; two worked.** Hamrah Mechanic's `/car-buy/` is a
concierge page whose `__NEXT_DATA__` carries only meta tags, Khodro45 ships React
flight data with no listing keys, and Iranecar is a Nuxt SPA whose listing routes
404 on direct fetch. Each would need browser-based reverse engineering and a
brittle bespoke parser.

## How it works

### Crawling

Public JSON APIs, not HTML scraping — no headless browser, no brittle selectors.
Raw records are stored exactly as returned, so re-parsing never means re-crawling.

**The crawler finds each site's pace instead of being told one.** A five-worker pool
on Divar measured 1.2× quicker and lost 8 listings of 48: Divar limits *bursts*, not
throughput — ~70ms per response, roughly thirty requests, then 429 until it refills.
A 429 now throttles the whole source and a success decays it gently. Listing loss:
**4.2% → 1.0%**.

Two adapter gotchas worth recording. Sheypoor's category filter `c=43627` is read
from `/api/v10.0.0/search/filters/car` rather than guessed, and getting it wrong is
*silent* — without it the endpoint returns the whole site (739,791 rows) and the
rows are apartments, so the adapter asserts the category from each row's own
breadcrumb. Karnameh's `buildId` changes every deploy, so it is scraped per crawl
and a miss **raises** — a crawl that succeeds with zero records is far more
expensive to notice than one that crashes.

### Normalization

- Model years are Jalali for domestic cars (1391) and Gregorian for imports (2012),
  in the *same field* with no flag. Split at 1500 — the corpus ranges don't overlap.
- Mileage is «صفر کیلومتر» or `240,000 km`. Only the token «صفر» marks zero; never
  substring-match `0 km`, because `240,000 km` contains it.
- Digits arrive Persian, Arabic-Indic or ASCII, sometimes in one string.
- **Negotiable prices are `NULL`, never `0`.** A zero would poison the regression
  target, and those rows are the ones the product exists to serve.
- Body condition is a Persian phrase on an implicit severity scale, worded
  differently per site; each source maps onto one shared 0–100 paint scale. Where a
  source omits it (Divar, 47% of rows) it's inferred from prose **worst-match-first**,
  so «بدون رنگ» next to «دور رنگ» can't score as clean.
- The search feed omits `model` and `trim_en` entirely (0% populated); both are
  recovered from the URL slug. Without that every car shares one empty cohort key.
  With it, 1,066 trim cohorts have five or more priced comparables.

### Cross-source identity

Bama publishes `brand='peugeot'` alongside `brand_fa='پژو'`; Divar and Sheypoor give
Persian only. The mapping is **learned** from the sources carrying both halves rather
than hand-written, with Persian names as the join key. Duplicate detection is
deliberately conservative — same brand/model/year, mileage within 2%, price within
3%, different sources — because a false merge hides a real listing, which is worse
than showing a car twice. It links **1,058** cross-posted listings.

### Fair price

`HistGradientBoostingRegressor` on `log(price)` with absolute-error loss. Prices span
~100M to ~45B toman; without the log transform, error on a Benz drowns out every
Pride. 8 numeric + 8 categorical features, including `source` — platforms differ
systematically, and letting the model see which site an ad came from stops that
being attributed to the car.

**Two data-quality findings changed the model materially.** Some dealers advertise
the *down-payment* as the price (a new car at 50M against ~2.1B). They're ordinary
`lumpsum` listings, detectable only as wild outliers against their own cohort;
excluding them cut MAPE **28% → 11.8%**. Voucher and pre-sale listings needed the
same treatment at *serving* time too, or they dominate every ranking as phantom
"90% below market" bargains — **824 listings** carry that flag.

**Confidence is driven by real comparable depth** (trim → model → global) multiplied
by how much spec evidence the listing carries. A thin cohort visibly lowers
confidence instead of quietly bluffing a number.

Sorting by price once put a **1,000-toman Porsche Cayenne** first: the cohort outlier
check needs three members and a Cayenne sits in a cohort of one. `effective_price`
now distrusts any published figure below 20M toman or below 15% of the car's own
estimate — reclassifying 20 listings, every one a placeholder.

### Health score

Rule-based and fully deterministic, because the signals that matter are already
structured and a buyer deserves to know exactly why a car scored what it did. A plain
used car starts at 62; ten factors move it, the widest being body condition
(−22…+18). Unusually *low* mileage on an old car is a mild risk, not a bonus — in
this market it more often signals a rolled-back odometer. Fields only one source
reports (chassis from Sheypoor, insurance from Divar) are a genuine extra signal
where present, never a penalty for sources that stay quiet.

### Search: retrieval, then ranking

Phase 1 had **no retrieval stage** — `rank()` scored the whole corpus, so any query it
didn't understand returned whatever was cheapest relative to market. «سراتو» returned
a BMW X4 while 273 Kia Ceratos sat unreachable.

1. **Entity match** — 193 brand names and 751 model names derived from the corpus
   itself, so nothing needs hand-maintaining. Folds Persian/Arabic yeh and kaf, ZWNJ
   and digits, tolerates typos. A named car is a hard filter, not a hint.
2. **TF-IDF** — char n-grams for Persian morphology, word tokens to keep the query's
   words apart, blended 0.65 toward words.
3. **Semantic** — for vague intent, with an LSA fallback needing no model download.

Two gates stand between a query and a result set, because similarity alone will
always rank *something* first. **Is this about a car?** — only words the corpus
actually uses count, and description words only when *common* («سقف» 4.9% of
listings, «دوچرخه» 0.01%). **Is this close enough to the best hit?** — candidates
must clear a fraction of the top score, or normalisation rescales the best of a bad
batch to a confident 1.0. Nonsense now returns an honest empty result, and retrieval
reports *which kind* of nothing (`nonsense`, `unknown_car`, `constraints`).

The LSA fallback is fitted once at start-up in a background thread and cached under a
fingerprint of the TF-IDF matrix it was fitted on. Retrieval never fits anything
itself: until the thread finishes, queries are answered on lexical relevance alone.

### Filters

Nineteen features, chosen by measurement rather than taste. `power_hp` (1.3%),
`insurance_months` (6.9%), `dealer_score` (6.9%) and `chassis_status` (37.3%) are
left out on purpose: a filter over a field that thin deletes most of the corpus the
moment it's touched, and a buyer reads that as "you have no cars", not "we have no
data". Chassis therefore scores in the health breakdown, where a missing value is one
fewer factor, and stays out of the panel, where it would be a trapdoor.

- **The catalogue is derived, never hand-written.** `/api/features` walks the corpus
  at start-up: 96 brands, 477 brand+model pairs, 70 colours, 563 cities. Tomorrow's
  new brand is filterable without editing a file.
- **Prose and ticks meet in one place.** Both produce an `Intent` and pass through
  `passes_features`. Where they overlap the tick wins — the buyer can see a checkbox
  and cannot see a parser.
- **Counts are leave-one-out**, or picking «هیوندای» reports every other brand as
  zero and multi-select becomes unusable.
- **The price filter runs on `effective_price`**, so «توافقی» cars are matched and
  sorted on our estimate. Any other choice makes them unfilterable again — precisely
  what this product exists to fix.

### AI, and what happens when it isn't there

Three uses, one contract: **cache first, always; never fail the request.** Risk
extraction from ad prose is a batch job run after ingest, with a keyword scanner
always running first and the LLM adding nuance on top. Query parsing runs the
deterministic Persian parser always and merges LLM output *over* it, so a missing key
degrades a query rather than emptying it. Semantic retrieval ships with the
no-download LSA fallback, with sentence embeddings behind `--embeddings`.

Every prompt is hashed and its response stored on disk, so the app runs correctly with
the network unplugged. `LLM_BASE_URL` takes any OpenAI-compatible endpoint — an
Iranian proxy (AvalAI, Metis, Liara), a local Ollama, or OpenAI directly.

> **The state of this checkout, stated plainly:** the enrichment table is **entirely
> rules-derived**. `data/llm_cache/` does not exist, and all 21,637 enrichment rows
> reproduce exactly from the keyword scanner — nothing in the shipped corpus has been
> read by a model. Red flags (1,880 listings carry at least one), positives and the
> health breakdown are all populated, which is the fallback doing its job. Getting the
> LLM layer in costs one pass of ~11.9k sequential calls, after which the cache makes
> it free.

## Decisions worth knowing

- **Raw records stored untouched.** Re-parsing after a normalization fix never means
  re-crawling — for Divar, the difference between a minute and an afternoon.
- **Brand-new (0 km) cars are out of scope.** Iran's new-car market is dual-priced —
  factory/allocation and free-market prices coexist for one model — so "market value"
  isn't a number and every comparison produces phantom bargains. The health engine is
  meaningless at 0 km too. `--include-new` overrides.
- **Ranking lives in Python, not SQL.** A few thousand rows in memory; keeping the
  logic readable keeps it *explainable*, which is the product.
- **SQLite, not Postgres.** One committed file means a reviewer clones and runs it.
- **Ordering is separate from explaining.** `order_all` sorts on numbers alone;
  `Ranking.page` explains only the 24 cars about to be seen — 507ms → 164ms for an
  unfiltered browse, and ~6ms per scroll once the ordering is cached per query.

## Running it

Requires Python 3.12+ and Node 20+.

```bash
docker compose up --build       # needs a built corpus in backend/data/
```

UI at http://localhost:3080 (nginx proxies `/api` to the backend).

### Backend

```bash
cd backend
./setup.sh    # creates .venv, installs deps, writes .env
```

`setup.sh` exists because `python3 -m venv` fails outright on Debian/Ubuntu systems
shipping python3 without `python3-venv` — no `ensurepip`, often no system pip. It
bootstraps pip using PyPA's official installer, so no `sudo` and no system packages.

```bash
# Sources cost wildly different amounts of time per car, so run them separately:
# Sheypoor returns ~12 listings/s because its search response carries the specs,
# Divar ~0.7 because every listing needs a detail request. --append resumes.
.venv/bin/python -m app.crawl.run --sources bama --pages 100 --details 500
.venv/bin/python -m app.crawl.run --sources sheypoor --pages 600
.venv/bin/python -m app.crawl.run --sources karnameh --pages 25
.venv/bin/python -m app.crawl.run --sources divar --pages 30 --append

.venv/bin/python -m app.ingest              # normalize → SQLite
.venv/bin/python -m app.pricing --train     # train + score, prints per-source error
.venv/bin/python -m app.enrich --only-new   # risk signals; skips what is already done

.venv/bin/uvicorn app.main:app --reload     # http://localhost:8000
```

### Frontend

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

The backend must be on port 8000 — the dev server calls it directly and CORS is
allowlisted to `localhost:5173`. Override with `VITE_API_BASE`.

### Verifying the numbers above

```bash
cd backend
.venv/bin/python -m pytest tests/ -q              # 224 tests
.venv/bin/python -m app.pricing --train           # reprints the error tables
.venv/bin/python -m tests.eval_search             # precision@5, hard and soft
.venv/bin/python -m tests.eval_search --baseline  # Phase 1: no retrieval stage
```

`--baseline` keeps pre-retrieval behaviour available on demand, so any change to
search is measured against the same yardstick.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/search?q=…` | natural-language search, ranked and explained |
| `GET /api/search?brands=…&price_max=…&sort=…` | the same endpoint, filtered by feature |
| `GET /api/features` | the filterable feature catalogue, derived from the corpus |
| `GET /api/car/{code}` | one listing with comparables and health breakdown |
| `GET /api/appraise?q=…` | price a car the user owns, from prose and/or a form |
| `GET /api/compare?codes=a,b` | side-by-side comparison |
| `GET /api/stats` | corpus summary |
| `GET /api/health` | liveness, LLM and cache status |

`/api/appraise` runs the same machinery over a car the user describes rather than one
we crawled. Refusal matters as much as assembly: a car we can't identify, or one with
no model year, gets an honest `status` and **no number**. A fabricated valuation is
worse than none — someone is about to price a real sale on it.

## Limitations

- **The corpus is a snapshot.** Prices go stale fast here; the resumable-crawl
  machinery exists, the schedule doesn't.
- **Divar is under-represented** (1,857 rows from the country's largest classifieds)
  because each listing costs one detail request. A time limit, not a technical one.
- **Spec fields come from Bama alone**, which is what the 10.2% vs 26.1% error gap
  measures. Enriching from a vehicle catalogue keyed on brand+model+year, independent
  of the ad, is the largest available accuracy win.
- **Selection bias in «توافقی» is unmeasured.** The model trains on priced listings
  and generalises to unpriced ones; validating that needs a time series we don't have.
- **Confidence is not calibrated** — 0.6 is an ordinal measure of evidence depth, not
  a claim that 60% of estimates land in band.
- **Vague queries regressed** with the retrieval stage; see Results.

## Data & attribution

Listings come from the public, unauthenticated JSON endpoints of
[Bama.ir](https://bama.ir), [Divar](https://divar.ir),
[Sheypoor](https://www.sheypoor.com) and [Karnameh](https://karnameh.com), crawled
once at modest volume with a delay between requests and a crawler that slows itself
down when a site says to. This is a non-commercial demo built for a hiring challenge;
all listing data and images remain the property of those sites and of the original
sellers.

<p align="center">
  <img src="frontend/public/brand/banner-wide.png" alt="کاپوت — زیر کاپوتِ هر آگهی را ببین" width="880">
</p>

# کاپوت · Capot

**Torob, but for the Iranian used-car market.**

*کاپوت* is the bonnet of a car, and the name is the promise: every listing is a
closed hood, and the product's whole job is to open it.

Built for the Torob AI Product Engineer challenge.

---

## The problem

Buying a used car in Iran means answering three questions that no listing site
actually answers:

1. **Is this price fair?** Listings show an asking price. Nothing tells you what
   the car is *worth*.
2. **Is this car healthy?** «دور رنگ», «موتور تعویض شده», «سند در رهن» — the
   things that matter are buried in prose, if they're mentioned at all.
3. **Does it fit what I need?** You can filter by brand and year. You cannot ask
   for "a first family car under 800M that's cheap to run."

And there's a fourth problem that makes the first one worse:

> **2,621 of the 22,820 used cars in this corpus don't publish a price at all.**
> They say «توافقی» — negotiable. On every existing site, those are a dead end:
> unsearchable, unfilterable, uncomparable.

## What Capot does

**It prices the cars that have no price.** A gradient-boosted model trained on
the 19,611 usable priced listings estimates what every hidden-price car is
actually worth, and ranks it alongside everything else with a confidence band.

Measured on a 20% held-out split: **median error 8.1%, MAPE 15.6%, R²(log) 0.917**
— and it recovers a price for **2,598 listings that published none**.

That headline number hides a split worth stating plainly:

| Source | Held-out listings | MAPE | Median APE | Avg confidence |
|---|---|---|---|---|
| Bama | 1,744 | **10.2%** | 5.9% | 0.60 |
| Divar | 373 | **19.5%** | 11.1% | 0.37 |
| Sheypoor | 1,737 | **19.9%** | 10.1% | 0.40 |
| Karnameh | 69 | **25.9%** | 19.1% | 0.22 |

Bama is twice as easy to price as anything else, and the cause is measurable
rather than mysterious: it is the only source that publishes engine size, power,
fuel consumption and seller rating, filling them on ~90% of rows where the other
three supply almost none. So confidence is discounted by how much evidence a
listing actually carries, not just by how many comparables it has.

Two results here are worth stating because they contradict what I expected.

**Adding sources raised average error, again.** Going from one source to two
took MAPE from 11.8% to 12.1%; going to four took it to 15.6%. That is not a
regression, it is the corpus getting more honest — three quarters of it is now
made of listings that publish less about themselves than Bama's do. Publishing
one blended number at uniform confidence would hide exactly that.

**Body condition did not buy price accuracy.** Sheypoor declares وضعیت بدنه on
essentially every listing where Divar omits it, so I expected Sheypoor to land
much closer to Bama. It lands at 19.9% against Divar's 19.5% — no better.
Declared paint condition turns out to matter for the *health* score, which is
what it feeds, and not for price, which leans on spec density. The corpus-wide
coverage of body status did rise from 66% to **94.3%**, which is a real gain in
the health engine and simply not a pricing one.

More data did help the source that had least of it: Divar's MAPE fell from
**28.0% to 19.5%** purely on volume, without a single change to how Divar
listings are parsed.

On top of that:

- **Fair price** — every listing gets a market estimate and a delta badge
  (`٪۱۲ زیر قیمت بازار`), backed by the real comparable listings, which you can
  inspect yourself in the detail panel.
- **Health score** — a 0–100 composite from paint condition, mileage-for-age,
  seller trust, inspection status, chassis condition where a source reports it,
  and risk phrases extracted from the ad text. Every point of it is itemised;
  nothing is a black box.
- **Need fit** — ask in plain Persian («اولین ماشین خانواده، بودجه ۸۰۰ میلیون،
  کم‌مصرف»). The query is parsed into structured intent, and results are ranked
  on value × health × fit — with the reasons shown on every card.
- **Filters** — or say nothing and tick instead. Seventeen car features, every
  one derived from the corpus and measured for coverage first, with live
  leave-one-out counts. Both doors lead to the same filter gate, so the two can
  never disagree.

## Architecture

```
   Bama        Sheypoor      Divar      Karnameh      (source adapters,
  JSON API     JSON API     JSON API   _next/data      crawl once → JSONL)
  9,798 rows  10,839 rows  1,857 rows   326 rows
      │            │            │            │
      │      specs inline   1 detail    typed records
      │      (24/request)   per listing  brand in fa+en
      └────────────┴──────┬─────┴────────────┘
                          ▼
   normalize.py ── mixed Jalali/Gregorian years, 'صفر کیلومتر' vs '240,000 km',
        │          Persian digits, negotiable → NULL (never 0),
        │          model/trim recovered from the URL slug
        ▼
   canonical.py ── Persian ↔ latin brand/model mapping, seeded from the search
        │          vocabulary and learned from the sources that publish both
        │          halves, so all four share price cohorts; duplicates linked
        ▼
     SQLite ──── listings · pricing · enrichment      22,820 used cars
        │
        ├── pricing.py  HistGradientBoosting on log(price), cohort confidence
        ├── health.py   deterministic, itemised risk scoring
        ├── enrich.py   LLM extraction from ad text (batch, cached to disk)
        ├── lexicon.py  brand/model vocabulary derived from the corpus
        ├── search.py   entity match → TF-IDF → semantic (retrieval)
        ├── features.py the filterable feature catalogue + the one filter gate
        └── rank.py     value × health × fit, within the retrieved set
        ▼
   FastAPI  →  React + Tailwind (RTL Persian, English toggle)
```

## Search: retrieval, then ranking

Phase 1 had **no retrieval stage**. `rank()` scored the whole corpus on
value/health/fit, so any query it didn't understand returned whatever was
cheapest relative to market — the same handful of cars every time. «سراتو»
returned a BMW X4 while 273 Kia Ceratos sat in the corpus unreachable.

The fix is a retrieval stage that decides *which* cars a query is about, before
ranking decides their order:

1. **Entity match** — a vocabulary of ~80 brands and ~440 models derived from
   the corpus itself (every Bama title is `brand_fa، model_fa`), so it never
   needs hand-maintaining. Normalizes Persian/Arabic digits, ZWNJ and yeh/kaf
   variants, and tolerates typos. A named car is a hard filter, not a hint.
2. **TF-IDF** over listing text with char n-grams, which handle Persian
   morphology without a stemmer.
3. **Semantic** similarity for vague intent, with an LSA fallback that needs no
   model download.

Nonsense now returns an honest empty result rather than confident garbage — a
query whose words appear in no listing and match no known intent is answered
with "no such car", not with the cheapest thing in stock.

Measured on `tests/eval_search.py`, which pairs 38 labelled Persian queries with
the constraints a correct hit must satisfy:

| | precision@5 | cases ≥80% |
|---|---|---|
| Before (rank the whole corpus) | **58.5%** | 14/26 |
| After (retrieve, then rank), 2 sources | **100%** | 26/26 |
| After, 4 sources and 22,820 listings | **93.2%** | 35/38 |

Going to four sources cost this table something, and both causes are worth
naming rather than tuning away.

**One was a real bug, and it was mine.** Bama carries no رانا at all, so nothing
taught that marque until Karnameh — which spells it `Runna` — arrived as a source
publishing both name forms. Twenty-six Ranas were then filed under `runna` while
the query resolved to `rana`, and search answered "no such car" over every one of
them: the *same* failure the brand backfill in `db.py` was written to fix, walked
in through the other door. The fix is structural rather than a spelling. The
brand vocabulary search uses now seeds the resolver, so a slug learned from a
crawl can no longer contradict the slug a buyer's query resolves to.

**Two of the three remaining failures are the test being wrong, not the search.**
Both are "this is not a car, return nothing" cases, and both now return five:

- «یخچال فریزر» (*refrigerator*) retrieves «وانت پراید **یخچال دار**» — a
  refrigerated pickup. That is a car, it is correctly matched, and the
  expectation dates from a corpus that happened not to contain one.
- «خانه ویلایی» (*villa*) retrieves «دوگانه **کارخانه**» — *factory*-fitted
  dual-fuel. This one is a genuine artifact: character n-grams are what let the
  index handle Persian morphology without a stemmer, and the price of that is
  that خانه matches inside کارخانه.

The second is a real precision cost and is left standing rather than special-
cased, because a stop-list tuned until the eval goes green would be fitting the
test rather than the language. It is recorded here instead. The honest summary is
that a corpus three times larger and drawn mostly from general classifieds makes
"return nothing" a harder promise to keep than it was with Bama alone.

A separate set of 8 deliberately vague queries («ماشین برای دختر دانشجو») scores
around 55% on the LSA fallback — up from 40% on the smaller corpus, which is the
one place the extra volume clearly helped — so the embedding model is still not
carrying its weight here. It stays available behind
`--embeddings` / an explicit index build, but the server never encodes the corpus
at start-up and the shipped default is the fallback.

The fallback is fitted once, at start-up, in a background thread, and cached to
`data/lsa.npz` under a fingerprint of the TF-IDF matrix it was fitted on. It used
to be fitted lazily, inside whichever query first needed it — which made the
first vague search of every server run wait about fourteen seconds for a matrix
decomposition. Retrieval now never fits anything itself: until the thread
finishes, a query is answered on lexical relevance alone, which it already knew
how to do. Re-ingest the corpus and the fingerprint stops matching and the cache
is refitted; leave it alone and start-up pays a 100ms file read.

## Filters: the second door

Prose is a good way in when you know what to say. It is a bad way in when you
don't, and no way at all to say "now show me the automatic ones". So the same
search takes a second kind of input: features you tick.

Seventeen features are exposed, and which ones is decided by measurement rather
than taste — every one is well populated across the 22,820 listings.
`power_hp` (1.3%), `insurance_months` (6.9%), `dealer_score` (6.9%) and
`chassis_status` (37.3%) are left out on purpose: a filter over a field that thin
deletes most of the corpus the moment it is touched, and a buyer reads that as
"you have no cars", not "we have no data". Chassis condition is the newest
example — Sheypoor is the only source that reports it, so it scores in the health
breakdown, where a missing value is simply one fewer factor, and stays out of the
filter panel, where it would have been a trapdoor.

Four things about it are worth explaining:

**The catalogue is derived, never hand-written.** `/api/features` walks the
corpus at start-up and reports what is actually there — 96 brands, 476
brand+model pairs, 70 colours, 563 cities — labelled from the rows themselves
(`brand_fa`, `model_fa`, `body_type_fa`). A brand that appears in tomorrow's
crawl is filterable without anyone editing a file, the same principle
`lexicon.py` already applies to search vocabulary. English brand names come from
the latin slug Bama publishes alongside the Persian, so 87 of them stay correct
with nobody maintaining them.

**Prose and ticks meet in one place.** Both produce an `Intent`, and
`passes_features` is the single gate both go through, so a filter cannot mean
one thing typed and another clicked. Where they overlap, the tick wins — if the
query said «اتوماتیک» and the buyer then unticks automatic, the buyer wins,
because they can see a checkbox and they cannot see a parser.

**Counts are leave-one-out.** Each feature's own selection is dropped before its
values are counted. Count them the obvious way and picking «هیوندای» reports
every other brand as zero, so a second brand can never be added and multi-select
is unusable. Done properly it also answers a question nobody asked: filter to
Pride above 20 billion toman and the panel shows you what *does* exist up there
— 131 BMWs, 7 Toyotas, 5 Benzes.

**The price filter runs on `effective_price`, not the asking price.** This is
the whole argument of the project, applied to a slider: a car whose seller wrote
«توافقی» is matched, and sorted, on our estimate. Filter to 1.5–2.5 billion and
441 of the 5,278 matches are cars that publish no price at all. Sort a filtered
set by "cheapest first" and hidden-price cars appear at the top on their
estimate. Any other choice would have made them unfilterable again, which is
precisely the thing this product exists to fix.

### The result grid scrolls, and why that made search fast

The grid used to be paged, with numbered buttons. Every fetch therefore had to
know how many pages there were, which meant ordering the entire result set and
building an explained payload for every car in it before it could return
twenty-four — about half a second for an unfiltered browse over 22,820 listings,
paid again for every page turn.

Three changes, in order of how much they mattered:

* **Ordering is separate from explaining.** `order_all` puts the candidates in
  order using only their numbers — health comes from the score
  `features.ensure_health_scores` already cached on the row, not from a fresh
  walk through a dozen factors — and `Ranking.page` builds the result payload
  for the twenty-four cars the reader is about to see. That alone took a browse
  from 507ms to 164ms.
* **The ordering is cached, keyed on the query and the filters but not on the
  window.** A scrolling grid asks for the same search once per screenful;
  `limit` and `offset` only choose where to look in an answer already computed.
* **Feature counts are sent once.** They describe the whole result set, not the
  batch, and re-sending tens of kilobytes of them per scroll would only redraw
  the panel identically.

Measured against the live corpus: the first fetch of an unfiltered browse is
~600ms and every scroll after it is **6ms**; a query like «سراتو سفید» is 60ms
then 4ms. The scroll sentinel sits a screenful below the last card, so the next
batch is usually in the grid before the reader reaches where it would have gone,
and a real button sits under it for anyone navigating by keyboard or screen
reader, whom a scroll sentinel cannot serve.

What this gave up is a linkable page number. That was the argument for numbered
pages in the first place — the URL is this app's source of truth — but a page
number was never the thing worth linking to. `?q=…&brands=…&sort=…` still
round-trips through the address bar exactly as it did; how far someone had
scrolled does not, and should not.

### A bug the sort surfaced

Ordering by price put a **1,000-toman Porsche Cayenne** first.

`pricing.py` already flags down-payment listings as `deposit`, but only by
comparing a price against its own brand+model+year cohort, and only when that
cohort has three or more members. A Cayenne sits in a cohort of one, so nothing
judged it and it kept its placeholder price. Ranking by value × health × fit had
hidden this for as long as it existed — a nonsense price buys a nonsense score
and sinks. Sorting by price puts it straight at the top.

`effective_price` now distrusts a published figure below 20M toman, or below 15%
of the car's own estimate, and falls back to the estimate exactly as it does for
a voucher. That reclassifies **20 listings**, every one of them a placeholder (a
110,000-toman Land Cruiser, a 10,000-toman Camry). The genuinely cheap cars stay
— a 180M Renault PK at 71% of its estimate, a crashed Pride at 50% — because the
threshold is deliberately far more permissive than the cohort check's own 0.35
floor. An estimate is weaker evidence than a real cohort median and is treated
that way.

### Decisions worth explaining

**Data comes from public JSON APIs**, not HTML scraping — no headless browser,
no brittle selectors. Each site is a `Source` adapter that owns only two things:
fetching raw records and turning one into a `Listing`. Everything downstream
sees only `Listing`, so adding a site never touches the product logic. Raw
records are stored exactly as returned, so re-parsing never means re-crawling.
Karnameh is the one asterisk: its JSON comes from the route its own pages are
built from rather than a declared API, which is still JSON but is addressed by a
build id that moves.

**The crawler finds each site's pace instead of being told one.** The first
attempt at making Divar faster was a pool of five concurrent workers. Measured,
it was 1.2x quicker and lost 8 listings out of 48 — because Divar limits
*bursts*, not throughput. Its detail endpoint answers in about 70ms, serves
roughly thirty requests, and then returns 429 until it refills; at five workers
half the requests come back 429 and at ten every one does. Retrying such a
request a fixed three times and moving on just converts listings into retries,
silently, since a dropped detail looks exactly like a car that failed to parse.

So a 429 now slows the whole source down rather than only the request that
tripped it, and a success decays that throttle back gently — shedding it in two
or three successes walks straight back into the limit. Measured over four pages
that took listing loss from 4.2% to 1.0%. The lesson generalises: throughput
here is a property of the site, not of our worker count. Sheypoor, needing no
detail request at all, runs at ~12 cars/s against Divar's ~0.7 without any
concurrency whatsoever.

**Divar needed a different shape of work.** It returns presentation data, not
records: prices and mileages arrive as display strings in Persian digits, and
the fields live inside typed UI widgets. It also omits وضعیت بدنه on most
listings — the strongest input to the health score — so body condition is
inferred from the title and description, worst-match-first so a seller writing
«بدون رنگ» next to «دور رنگ» can't score as clean. In exchange it offers
insurance validity and technical-inspection status, which Bama has not got.

**Five further sites were attempted; two of them worked.** Sheypoor and Karnameh
are now sources three and four, for opposite reasons — see below. Hamrah
Mechanic, Khodro45 and Iranecar are still out, and were re-checked rather than
assumed: Hamrah's `/car-buy/` is a concierge-service page whose `__NEXT_DATA__`
carries only meta tags, Khodro45's `/used-car/` ships React flight data with no
listing keys in it and its `buy.` subdomain references no API, and Iranecar is a
Nuxt SPA whose listing routes 404 on direct fetch. Each would need browser-based
reverse engineering and a bespoke, brittle parser.

**Sheypoor is the cheapest source per car, by a factor of about twenty-four.**
Its search endpoint returns a listing's entire spec sheet inline, so unlike
Divar there is no per-listing detail request: one HTTP call yields 24
fully-specified cars instead of one. It also *declares* وضعیت بدنه — measured at
60 rows out of 60, where Divar omits it on nearly every listing and it has to be
inferred from prose. Body condition is the strongest single input to the health
score, so a source that states it is worth a great deal. It is the only source
here that reports chassis condition at all.

Finding it took one non-obvious step. The category filter is `c=43627`, read from
`/api/v10.0.0/search/filters/car` rather than guessed — and getting it wrong is
silent rather than loud. Without it the endpoint cheerfully returns the whole
site (`meta.total` reads 739,791 across every category instead of 64,429 cars)
and the rows are apartments. So the adapter asserts the category from each row's
own breadcrumb instead of trusting the query it sent.

**Karnameh is here for data quality, not volume.** It is small and honest about
it: `total` reads 346 across 18 pages, and the brand-scoped routes return subsets
of that same pool rather than adding to it. What it offers is the cleanest
records of the four — typed integers where everything else publishes display
strings — and, decisively, `brand_name_en` alongside `brand_name_fa`. Cross-source
identity is learned from sources that carry both halves, which until now meant
Bama alone; Karnameh reinforces that mapping and needs no resolution itself.

It has no REST API, but it is a Next.js pages-router app, so the data its own
pages are built from is served as JSON at `/_next/data/{buildId}/…`. That
`buildId` changes on every deploy and so is scraped at the start of each crawl —
the one genuinely fragile thing in these four adapters, and it raises rather than
returning nothing, because a crawl that succeeds with zero records is far more
expensive to notice than one that crashes.

**Cross-source identity is learned, not hand-written.** Bama publishes
`brand='peugeot'` alongside `brand_fa='پژو'`; Divar gives Persian only. Bama
therefore teaches the mapping that lets Divar listings join the same price
cohorts. Duplicate detection is deliberately conservative — same brand/model/
year, mileage within 2%, price within 3%, different sources — because a false
merge hides a real listing, which is worse than showing a car twice.

**Negotiable prices are `NULL`, never `0`.** A zero would have poisoned the
regression target. Those rows are the ones the product exists to serve.

**The price model trains on `log(price)`** with absolute-error loss. Prices span
~100M to ~45B toman; without the log transform, error on a Benz would drown out
every Pride in the corpus.

**Confidence is driven by real comparable depth**, walking trim → model →
global. A thin cohort visibly lowers confidence instead of quietly bluffing a
number — a number nobody can check is worse than no number.

**The search feed omits `model` and `trim_en` entirely** (0% populated) — they
exist only on the detail endpoint. Both are recoverable from the listing URL
slug, which is what `parse_url_slug` does. Without it every car would share one
empty cohort key and the comparables would be meaningless; with it, 543 trim
cohorts have five or more priced comparables.

**Two data-quality findings changed the model materially.** Some dealers
advertise the *down-payment* as the price — brand-new cars listed at 50M toman
against a ~2.1B market value. They're ordinary `lumpsum` listings, so no field
identifies them; they're only detectable as wild outliers against their own
cohort. Excluding them cut holdout MAPE from **28% → 11.8%**. Voucher and
pre-sale listings (حواله / پیش‌فروش) needed the same treatment at *serving*
time, not just training time — otherwise they dominate every ranking as phantom
"90% below market" bargains.

**Brand-new (0 km) cars are deliberately out of scope.** Iran's new-car market
is dual-priced: a factory/allocation price and a much higher free-market price
coexist for the same model, so "market value" isn't one number and every
comparison against it produces phantom bargains. The health engine is also
meaningless at 0 km — body status is always «بدون رنگ» and there's no wear to
assess. Scoping to used cars drops ~4,000 zero-kilometre listings from the crawl.
Pass `--include-new` to `app.ingest` to override.

**Every LLM result is cached to disk and committed.** The request path never
waits on a model, and the app runs correctly with the network unplugged. If the
proxy is down, health scoring falls back to rules and query parsing falls back
to a deterministic Persian parser. An AI feature that takes the page down with
it is worse than no AI feature.

That fallback is not theoretical here, and the current state of this checkout is
worth stating plainly rather than leaving a reader to assume otherwise: the
enrichment table is **entirely rules-derived**. `data/llm_cache/` does not exist,
and every one of the 21,637 enrichment rows reproduces exactly from the keyword
scanner, so nothing in the shipped corpus has been read by a model. The product
works — red flags, positives and the health breakdown are all populated — which
is the fallback doing its job.

Getting the LLM layer in costs one pass of roughly 11.9k sequential calls, after
which the cache makes it free. Two things make that a deliberate step rather than
an automatic one. `enrich.py` has no batching or concurrency, so the pass is
measured in hours; and `--only-new` decides what to skip from the `model` column,
which now records what actually read a listing rather than what was requested.
Labelling by the flag instead marked a row `llm+rules` on any run where the model
merely *could* have been called — including runs where every call returned
nothing — and a row that lies about having been read is one `--only-new` skips
forever.

**SQLite, not Postgres.** A few thousand rows in one committed file means a
reviewer clones the repo and runs it — no database to provision.

## Running it

Requires Python 3.12+ and Node 20+.

### Backend

```bash
cd backend
./setup.sh          # creates .venv, installs deps, writes .env
```

`setup.sh` exists because `python3 -m venv` fails outright on Debian/Ubuntu
systems that ship python3 without the `python3-venv` package — there is no
`ensurepip` and often no system `pip` either. The script detects that and
bootstraps pip into the venv using PyPA's official installer, so no `sudo` and
no system packages are needed. If you'd rather fix it at the system level:

```bash
sudo apt install python3-venv python3-pip      # then ./setup.sh takes the normal path
```

Then build the corpus and serve it:

```bash
# Crawl. The sources cost wildly different amounts of time per car, so they are
# worth running separately — Sheypoor returns ~12 listings/second because its
# search response already carries the specs, Divar about 0.7 because every
# listing needs its own detail request.
.venv/bin/python -m app.crawl.run --sources bama --pages 100 --details 500
.venv/bin/python -m app.crawl.run --sources sheypoor --pages 600
.venv/bin/python -m app.crawl.run --sources karnameh --pages 25
.venv/bin/python -m app.crawl.run --sources divar --pages 30 --append   # slow; resumable

.venv/bin/python -m app.ingest                    # normalize → SQLite
.venv/bin/python -m app.pricing --train           # train + score, prints per-source error
.venv/bin/python -m app.enrich --only-new         # risk signals; skips what is already done

.venv/bin/uvicorn app.main:app --reload           # http://localhost:8000
```

Every crawl is resumable with `--append`, which matters most for Divar: it is
the one source where a full pass is measured in hours rather than minutes.
`--only-new` on the enrichment step exists for the same reason — adding a source
doubles the corpus but not the work, and without it a re-run pays the model again
for answers already in the database.

Commands are written as `.venv/bin/python` so they work whether or not you've
run `source .venv/bin/activate` first.

### Frontend

```bash
cd frontend
npm install
npm run dev                                         # http://localhost:5173
```

The backend must be running on port 8000 — the dev server calls it directly and
CORS is allowlisted to `localhost:5173`. Override with `VITE_API_BASE` if you
serve the API elsewhere.

### Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
```

### The LLM endpoint

`LLM_BASE_URL` accepts any OpenAI-compatible endpoint, so the same code works
against an Iranian proxy (AvalAI, Metis, Liara), a local Ollama, or OpenAI
directly. See `backend/.env.example`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/search?q=…` | natural-language search, ranked and explained |
| `GET /api/search?brands=…&price_max=…&sort=…` | the same endpoint, filtered by feature |
| `GET /api/features` | the filterable feature catalogue, derived from the corpus |
| `GET /api/car/{code}` | one listing with its comparables and health breakdown |
| `GET /api/compare?codes=a,b` | side-by-side comparison |
| `GET /api/stats` | corpus summary |
| `GET /api/health` | liveness, LLM and cache status |

## Brand

The name is the argument. A listing is a closed hood — the seller shows you the
paint and keeps the rest — and «کاپوت» is what opens it. The mark is a car with
its bonnet up, drawn as one component in
[`frontend/src/components/Logo.tsx`](frontend/src/components/Logo.tsx) so it
inherits the theme instead of shipping a second asset, and repeated as a
standalone tile in `frontend/public/favicon.svg` for the places that have no
container to inherit from.

The ad creatives are generated rather than designed in a separate tool:

```bash
python3 brand/build.py                 # all of them
python3 brand/build.py og ad-story     # or just these
```

`brand/tokens.css` is a copy of the product's own palette and card/chip shapes,
and `brand/build.py` lays the creatives out in that CSS and screenshots each one
with headless Chrome at its exact pixel size. That indirection is the point: an
ad built from the same tokens cannot drift away from the page it links to, and
regenerating after a palette change is one command rather than an afternoon.

| File | Size | Use |
|---|---|---|
| `frontend/public/brand/og.png` | 1200×630 | link previews — wired into `index.html` |
| `frontend/public/brand/banner-wide.png` | 1600×400 | this README, site head |
| `frontend/public/brand/ad-leaderboard.png` | 970×250 | display leaderboard |
| `frontend/public/brand/ad-square.png` | 1080×1080 | feed post |
| `frontend/public/brand/ad-story.png` | 1080×1920 | story |

Every figure that appears on a creative — 22,820 listings, 2,621 negotiable,
2,598 recovered, 8.1% median error — is a number this repo actually measured and
prints above. Marketing copy that rounds them off is the fastest way to lose the
one reader who checks.

## Data & attribution

Listings come from the public, unauthenticated JSON endpoints of
[Bama.ir](https://bama.ir), [Divar](https://divar.ir),
[Sheypoor](https://www.sheypoor.com) and [Karnameh](https://karnameh.com),
crawled once at modest volume with a delay between requests and a crawler that
slows itself down when a site says to. This is a non-commercial demo built for a
hiring challenge; all listing data and images remain the property of those sites
and of the original sellers.

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import {
  api,
  type Appraisal,
  type CarResult,
  type FeatureCatalogue,
  type FeatureCounts,
  type RetrievalInfo,
  type Stats,
} from "./api";
import { ActiveFilters } from "./components/ActiveFilters";
import { AppraiseView } from "./components/AppraiseView";
import { CarCard } from "./components/CarCard";
import { CarDetailPanel } from "./components/CarDetail";
import { FilterPanel } from "./components/FilterPanel";
import { Hero } from "./components/Hero";
import { ResultsEnd } from "./components/ResultsEnd";
import { SiteHeader } from "./components/SiteHeader";
import { SortSelect } from "./components/SortSelect";
import {
  EMPTY_INPUT,
  fillFromParsed,
  fromParams as appraisalFromParams,
  hasInput,
  isAppraiseUrl,
  toParams as appraisalToParams,
  type AppraisalInput,
} from "./appraisal";
import {
  EMPTY_FILTERS,
  countActive,
  fromParams,
  toParams,
  type Filters,
  type SortKey,
} from "./filters";
import { localizeDigits } from "./format";
import { EXAMPLE_QUERIES, t, type Lang } from "./i18n";
import { useTheme } from "./theme";

export default function App() {
  const [lang, setLang] = useState<Lang>("fa");
  const { theme, toggle: toggleTheme } = useTheme();

  // The URL is the source of truth for a search, so a filtered result set can be
  // reloaded, shared, and walked back through with the browser's own buttons.
  const initial = fromParams(window.location.search);
  const [query, setQuery] = useState(initial.q);
  const [filters, setFilters] = useState<Filters>(initial.filters);
  const [sort, setSort] = useState<SortKey>(initial.sort);

  // Everything loaded so far, not one page of it: the grid grows as the reader
  // scrolls. `null` still means "no search has run", which is what draws the
  // landing state.
  const [results, setResults] = useState<CarResult[] | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [retrieval, setRetrieval] = useState<RetrievalInfo | null>(null);
  const [catalogue, setCatalogue] = useState<FeatureCatalogue | null>(null);
  const [counts, setCounts] = useState<FeatureCounts | null>(null);
  // Two different waits, and they must not look the same. `loading` blanks the
  // grid because the result set is being replaced; `loadingMore` leaves the
  // cards alone and only speaks at the foot of the list.
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // "Price my car" is a second view of the same corpus rather than a second app,
  // so it lives in this component's URL state alongside the search — one place
  // deciding what the address bar says, exactly as before.
  const [onAppraiseView, setOnAppraiseView] = useState(isAppraiseUrl(window.location.search));
  const [appraisalInput, setAppraisalInput] = useState<AppraisalInput>(
    isAppraiseUrl(window.location.search)
      ? appraisalFromParams(window.location.search)
      : { ...EMPTY_INPUT },
  );
  const [appraisal, setAppraisal] = useState<Appraisal | null>(null);
  const [appraisalLoading, setAppraisalLoading] = useState(false);
  const [appraisalError, setAppraisalError] = useState<string | null>(null);

  const s = t(lang);
  const dir = lang === "fa" ? "rtl" : "ltr";
  const activeCount = countActive(filters);
  const hasSearched = results !== null;

  // Persian is RTL; set it on the document so native scrollbars and form
  // controls flip too, not just our own layout.
  useEffect(() => {
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
  }, [dir, lang]);

  useEffect(() => {
    api.stats().then(setStats).catch(() => setStats(null));
    // The filter panel is drawn from the corpus, so it cannot be rendered until
    // this arrives — and it must not block the rest of the page if it fails.
    api.features().then(setCatalogue).catch(() => setCatalogue(null));
  }, []);

  // Which search the results on screen belong to. A reader can retype, tick a
  // filter or scroll while a fetch is still out, and an answer to the question
  // before last must not land in the grid — appended least of all.
  const requestId = useRef(0);

  const search = useCallback(async (q: string, nextFilters: Filters, nextSort: SortKey) => {
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const data = await api.search(q, nextFilters, nextSort, 0);
      if (id !== requestId.current) return;
      setResults(data.results);
      setHasMore(data.has_more);
      setRetrieval(data.retrieval ?? null);
      setCounts(data.features ?? null);
    } catch (err) {
      if (id !== requestId.current) return;
      setError(String(err));
      setResults(null);
      setHasMore(false);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  /** The next batch, appended. The offset is what the grid already holds, so
   *  there is no page number to keep in step with anything. */
  const loadMore = useCallback(async () => {
    if (loading || loadingMore || !hasMore || results === null) return;
    const id = requestId.current;
    setLoadingMore(true);
    try {
      const data = await api.search(query, filters, sort, results.length);
      if (id !== requestId.current) return;
      // Deduplicated on `code`: a listing crossing a batch boundary while the
      // corpus is being re-ingested would otherwise appear twice and break
      // React's keys.
      setResults((current) => {
        const seen = new Set((current ?? []).map((car) => car.code));
        return [...(current ?? []), ...data.results.filter((car) => !seen.has(car.code))];
      });
      setHasMore(data.has_more);
    } catch (err) {
      if (id !== requestId.current) return;
      // The batch failed, not the search: keep the cards, stop the scroll from
      // retrying forever, and let the reader see why.
      setError(String(err));
      setHasMore(false);
    } finally {
      if (id === requestId.current) setLoadingMore(false);
    }
  }, [filters, hasMore, loading, loadingMore, query, results, sort]);

  /** Value the car the user described. The URL is written from the same params
   *  the request is built from, so the link they share reproduces the answer. */
  const runAppraisal = useCallback(async (input: AppraisalInput) => {
    if (!hasInput(input)) return;
    setAppraisalLoading(true);
    setAppraisalError(null);
    try {
      const data = await api.appraise(appraisalToParams(input));
      setAppraisal(data);
      // What the prose alone yielded, dropped into the fields it left empty, so
      // the user can see what we understood and correct it. Anything they had
      // already typed stands — the parser does not get to overrule them.
      setAppraisalInput((current) => fillFromParsed(current, data.parsed));
    } catch (err) {
      setAppraisalError(String(err));
      setAppraisal(null);
    } finally {
      setAppraisalLoading(false);
    }
  }, []);

  // One effect drives every search: typing, ticking a filter, changing the sort.
  // Keeping it in a single place is what stops the URL and the results diverging.
  const firstRun = useRef(true);
  useEffect(() => {
    // The appraisal view owns the address bar while it is open — writing the
    // search's params here would wipe the car the reader is being shown.
    if (onAppraiseView) return;

    const params = toParams(filters, query, sort);
    const url = params.toString() ? `?${params.toString()}` : window.location.pathname;
    window.history.replaceState(null, "", url);

    // On a cold load with nothing selected, leave the landing state alone
    // rather than dumping the whole corpus on the page.
    if (firstRun.current) {
      firstRun.current = false;
      if (!query && countActive(filters) === 0) return;
    }
    search(query, filters, sort);
  }, [query, filters, sort, search, onAppraiseView]);

  // The appraisal's own half of that rule.
  useEffect(() => {
    if (!onAppraiseView) return;
    const params = appraisalToParams(appraisalInput, true);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, [onAppraiseView, appraisalInput]);

  // A shared appraisal link must answer on arrival, not wait to be pressed.
  const appraisalFirstRun = useRef(true);
  useEffect(() => {
    if (!appraisalFirstRun.current) return;
    appraisalFirstRun.current = false;
    if (onAppraiseView && hasInput(appraisalInput)) runAppraisal(appraisalInput);
  }, [onAppraiseView, appraisalInput, runAppraisal]);

  // The header carries a copy of the search box, but only once the hero's own
  // box has left the screen — two identical search bars stacked on top of each
  // other on first paint would be a design error, and the sticky one exists
  // purely so the call to action survives scrolling.
  const heroSearch = useRef<HTMLDivElement>(null);
  const [heroSearchVisible, setHeroSearchVisible] = useState(true);
  useEffect(() => {
    const element = heroSearch.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      ([entry]) => setHeroSearchVisible(entry.isIntersecting),
      // The sticky bar covers the top of the viewport, so the hero box counts as
      // gone once it slides under it rather than once it leaves the window.
      { rootMargin: "-64px 0px 0px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // The banner folds down to a strapline and a box once a search has run — but
  // not while the reader is still looking at it. Reloading a shared result URL
  // fires a search immediately, and folding on that alone showed the banner for
  // one frame and then swallowed it, which reads as a glitch rather than as a
  // page getting out of the way. So the fold waits for the band to leave the
  // screen, and latches: it never grows back under someone who scrolls up.
  const heroBand = useRef<HTMLElement>(null);
  const [heroPassed, setHeroPassed] = useState(false);
  useEffect(() => {
    const element = heroBand.current;
    if (!element || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) return;
      setHeroPassed(true);
      observer.disconnect();
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Anything that changes *which* cars match starts a new list. Keeping the
  // cars already scrolled past would answer a question nobody asked.
  const resultsTop = useRef<HTMLDivElement>(null);
  const restart = () => {
    // Closes the door on the old list before the new one is asked for. Between
    // this render and the fetch the grid still holds the previous results, and
    // without this the scroll sentinel could ask to extend them — under the new
    // query, which would append somebody else's cars to them.
    setHasMore(false);
    // Back to the top of the grid, not the top of the page: the header, the
    // hero and the search box are not worth re-reading to see a new result set.
    //
    // Instantly, not smoothly. A reader who changes the sort fifty cards deep
    // would otherwise watch the whole list fly past — and the new results would
    // render while the viewport was still at the bottom, putting the scroll
    // sentinel in view and back-filling batches nobody asked for.
    resultsTop.current?.scrollIntoView({ block: "start" });
  };

  const changeQuery = (next: string) => {
    restart();
    setQuery(next);
  };
  const changeFilters = (next: Filters) => {
    restart();
    setFilters(next);
  };
  const changeSort = (next: SortKey) => {
    restart();
    setSort(next);
  };

  const applyFilters = (next: Filters) => {
    changeFilters(next);
    setDrawerOpen(false);
  };

  // Every change to the banner's height happens above the reader's scroll
  // position — the fold above, and the proof figures arriving from /api/stats.
  // Left alone that shoves whatever they were reading up or down the screen, so
  // the scroll position absorbs the difference and the cards hold still.
  const compact = hasSearched && heroPassed;
  const bandHeight = useRef(0);
  useLayoutEffect(() => {
    const element = heroBand.current;
    if (!element) return;
    const previous = bandHeight.current;
    bandHeight.current = element.offsetHeight;
    if (previous > 0 && previous !== bandHeight.current && window.scrollY > 0) {
      window.scrollBy(0, bandHeight.current - previous);
    }
  }, [compact, stats]);

  return (
    <div className="min-h-screen" dir={dir} id="top">
      <a href="#search" className="skip-link">
        {s.skipToSearch}
      </a>

      <SiteHeader
        lang={lang}
        theme={theme}
        query={query}
        loading={loading}
        showSearch={!heroSearchVisible && !onAppraiseView}
        onAppraise={onAppraiseView}
        onSearch={changeQuery}
        onToggleAppraise={() => {
          setOnAppraiseView((current) => !current);
          window.scrollTo({ top: 0 });
        }}
        onToggleTheme={toggleTheme}
        onToggleLang={() => setLang(lang === "fa" ? "en" : "fa")}
      />

      {/* The hook: a large slice of the market hides its price, and we price it
          anyway. Every figure in the banner comes from /api/stats, so the claim
          can never drift from the data behind it.

          Hidden on the appraisal view: that page makes its own, different ask,
          and a banner arguing the buyer's case above it would only be something
          to scroll past — the same argument the hero's own fold already makes. */}
      {!onAppraiseView && (
        <Hero
          lang={lang}
          stats={stats}
          query={query}
          loading={loading}
          compact={compact}
          bandRef={heroBand}
          searchRef={heroSearch}
          onSearch={changeQuery}
          onAppraise={() => {
            setOnAppraiseView(true);
            window.scrollTo({ top: 0 });
          }}
          onExplore={() =>
            // Smoothly here, unlike `restart`: this scroll *is* the answer to the
            // click, and the reader has to see the page move to understand that
            // the banner was only the first screen of it.
            resultsTop.current?.scrollIntoView({ behavior: "smooth", block: "start" })
          }
        />
      )}

      {onAppraiseView && (
        <main className="shell pb-10 pt-8">
          <AppraiseView
            input={appraisalInput}
            result={appraisal}
            loading={appraisalLoading}
            error={appraisalError}
            catalogue={catalogue}
            lang={lang}
            onChange={setAppraisalInput}
            onSubmit={() => runAppraisal(appraisalInput)}
            onOpenCar={setSelected}
          />
        </main>
      )}

      {!onAppraiseView && (
      <main className="shell pb-8 pt-6">
        <div className="lg:grid lg:grid-cols-[240px_1fr] lg:gap-6 xl:grid-cols-[280px_1fr] xl:gap-8">
          {/* Sidebar on desktop; a bottom sheet on small screens, where a
              permanent 240px column would leave no room for the cards. */}
          {catalogue && (
            <>
              <aside className="hidden lg:block">
                <div className="card sticky top-4 max-h-[calc(100vh-2rem)] overflow-y-auto p-4">
                  <h2 className="mb-1 text-sm font-semibold text-ink-900">{s.filters}</h2>
                  <FilterPanel
                    catalogue={catalogue}
                    counts={counts}
                    filters={filters}
                    lang={lang}
                    onChange={changeFilters}
                  />
                </div>
              </aside>

              <button
                type="button"
                onClick={() => setDrawerOpen(true)}
                className="mb-3 flex w-full items-center justify-center gap-2 rounded-xl border
                           border-ink-100 bg-surface px-4 py-2.5 text-sm font-medium text-ink-700
                           shadow-card lg:hidden"
              >
                {s.filters}
                {activeCount > 0 && (
                  <span className="rounded-full bg-brand px-2 py-0.5 text-[11px] font-semibold text-white">
                    {localizeDigits(String(activeCount), lang)}
                  </span>
                )}
              </button>
            </>
          )}

          <div className="min-w-0 scroll-mt-20" ref={resultsTop}>
            <ActiveFilters
              catalogue={catalogue}
              filters={filters}
              lang={lang}
              onChange={changeFilters}
            />

            {error && (
              <p className="rounded-xl border border-over/20 bg-over-soft p-4 text-sm text-over">
                {error}
              </p>
            )}

            {loading && <p className="py-12 text-center text-sm text-ink-500">{s.loading}</p>}

            {/* Four different failures, four different answers. "We don't
                understand this as a car" is not "we have none of that car", is
                not "nothing fits your budget", is not "your filters are too
                tight" — telling them apart is the whole point. */}
            {!loading && results && results.length === 0 && (
              <EmptyResult
                lang={lang}
                retrieval={retrieval}
                hasFilters={activeCount > 0}
                onSearch={changeQuery}
                onClearFilters={() => changeFilters(EMPTY_FILTERS)}
              />
            )}

            {!loading && results && results.length > 0 && (
              <>
                {/* The words were not understood but the numbers were — say so,
                    rather than letting a filtered result set look like a
                    confident answer to the whole query. */}
                {retrieval?.mode === "constraints" && (
                  <p className="mb-3 rounded-xl border border-ink-100 bg-ink-50 p-3 text-xs text-ink-700">
                    {s.wordsIgnored}
                  </p>
                )}
                <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
                  <p className="flex flex-wrap items-center gap-2 text-sm text-ink-500">
                    {/* No result count. It was never what the reader came for,
                        and the number the grid could honestly report is the size
                        of the retrieved candidate pool, not of the market. What
                        is worth saying is what the search matched *on*. */}
                    {query && <span>«{query}»</span>}
                    {retrieval?.mode === "entity" && retrieval.matched.length > 0 && (
                      <span className="chip">
                        {s.matchedOn} «{retrieval.matched.join("، ")}»
                      </span>
                    )}
                    {retrieval?.fuzzy && (
                      <span className="chip border-brand/20 bg-brand-soft text-brand-dark">
                        {s.didYouMean} «{retrieval.matched[0]}»
                      </span>
                    )}
                  </p>
                  <SortSelect value={sort} lang={lang} onChange={changeSort} />
                </div>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {results.map((car) => (
                    <CarCard key={car.code} car={car} lang={lang} onOpen={setSelected} />
                  ))}
                </div>
                <ResultsEnd
                  hasMore={hasMore}
                  loaded={results.length}
                  loading={loadingMore}
                  lang={lang}
                  onLoadMore={loadMore}
                />
              </>
            )}

            {/* Landing state. The banner above has already offered the typed
                door and four ways through it, so repeating the examples here
                would only be the same invitation twice; what is left to say is
                that there is a second door. */}
            {!loading && !hasSearched && (
              <div className="card p-10 text-center">
                <p className="mx-auto max-w-sm text-sm leading-relaxed text-ink-500">
                  {s.landingPrompt}
                </p>
              </div>
            )}
          </div>
        </div>
      </main>
      )}

      {/* Mobile filter drawer. */}
      {drawerOpen && catalogue && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-scrim/50"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-surface p-5 shadow-card">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ink-900">{s.filters}</h2>
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                className="rounded-lg border border-ink-100 px-3 py-1.5 text-xs text-ink-700"
              >
                {s.close}
              </button>
            </div>
            <FilterPanel
              catalogue={catalogue}
              counts={counts}
              filters={filters}
              lang={lang}
              onChange={applyFilters}
            />
          </div>
        </div>
      )}

      {selected && (
        <CarDetailPanel code={selected} lang={lang} onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

/** The empty state, which has to answer "why nothing?" four different ways. */
function EmptyResult({
  lang,
  retrieval,
  hasFilters,
  onSearch,
  onClearFilters,
}: {
  lang: Lang;
  retrieval: RetrievalInfo | null;
  hasFilters: boolean;
  onSearch: (q: string) => void;
  onClearFilters: () => void;
}) {
  const s = t(lang);
  const mode = retrieval?.mode;

  // A fuzzy entity match that found nothing is a spelling problem, and the
  // correction we already computed is more use than any generic advice.
  const suggestion =
    retrieval?.fuzzy && retrieval.matched.length > 0 ? retrieval.matched[0] : null;

  // Filters are the likeliest cause when they are set: the corpus has the car,
  // the buyer has narrowed it away. Say that, and offer the undo.
  const { headline, hint } = hasFilters
    ? { headline: s.noResultsFilters, hint: s.noResultsFiltersHint }
    : mode === "unknown_car"
      ? { headline: s.noSuchListing, hint: s.noSuchListingHint }
      : mode === "nonsense"
        ? { headline: s.noCarMatch, hint: s.noCarMatchHint }
        : { headline: s.noResults, hint: s.noResultsHint };

  return (
    <div className="card p-8 text-center">
      <p className="text-sm font-medium text-ink-900">{headline}</p>
      <p className="mx-auto mt-2 max-w-md text-xs text-ink-500">
        {suggestion ? `${s.didYouMean} «${suggestion}»` : hint}
      </p>
      <div className="mt-4 flex flex-wrap justify-center gap-2">
        {hasFilters ? (
          <button
            onClick={onClearFilters}
            className="chip border-brand/30 bg-brand-soft text-brand-dark hover:bg-brand/10"
          >
            {s.clearAll}
          </button>
        ) : (
          EXAMPLE_QUERIES[lang].slice(0, 3).map((example) => (
            <button
              key={example}
              onClick={() => onSearch(example)}
              className="chip hover:border-brand/30 hover:text-brand-dark"
            >
              {example}
            </button>
          ))
        )}
      </div>
    </div>
  );
}

import { useEffect, useRef } from "react";
import { t, type Lang } from "../i18n";

/**
 * The foot of the results grid: what loads the next batch, and what says there
 * isn't one.
 *
 * Numbered pages meant every search paid for its whole result set up front —
 * the backend had to order and count thousands of listings before it could draw
 * a pager, and moving one page cost that again. A grid that loads as you scroll
 * asks for twenty-four cars at a time and nothing else, which is why this
 * replaced the pager.
 *
 * The sentinel sits a screen below the last card (`rootMargin`), so the next
 * batch is usually already in the grid by the time the reader reaches where it
 * would have gone. The button underneath is not a fallback for slow loading —
 * it is the whole control for anyone whose browser has no IntersectionObserver,
 * who navigates by keyboard, or who is reading with a screen reader, none of
 * whom can trigger a scroll sentinel.
 */
export function ResultsEnd({
  hasMore,
  loaded,
  loading,
  lang,
  onLoadMore,
}: {
  hasMore: boolean;
  /** How many cards are above the sentinel. Only used to re-arm the observer
   *  once a batch has landed — see the effect below. */
  loaded: number;
  loading: boolean;
  lang: Lang;
  onLoadMore: () => void;
}) {
  const s = t(lang);
  const sentinel = useRef<HTMLDivElement>(null);

  // `onLoadMore` changes identity whenever the results do, and re-subscribing
  // an observer on every batch would fire it again against the sentinel it is
  // still overlapping. The ref keeps the effect's dependencies down to the one
  // thing that should actually rebuild the observer.
  const load = useRef(onLoadMore);
  useEffect(() => {
    load.current = onLoadMore;
  });

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasMore || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) load.current();
      },
      // A screenful of lead time: fetch the next batch while the reader is
      // still looking at the current one.
      { rootMargin: "600px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
    // Re-armed once each batch lands. An observer fires on a *change* in
    // intersection, so if the new cards do not push the sentinel out of view —
    // a short batch, a tall screen — nothing would fire again and the list
    // would stall until the reader scrolled. Re-observing re-tests where the
    // sentinel now is, and the guards inside `onLoadMore` stop that becoming a
    // loop: a fetch is already in flight, or there is nothing more to fetch.
  }, [hasMore, loaded]);

  return (
    <div className="mt-6 flex flex-col items-center gap-3">
      <div ref={sentinel} aria-hidden className="h-px w-full" />

      {/* One live region for both states, so a screen reader hears the batch
          arrive and hears when there are no more — without either message
          shifting the cards above it. */}
      <p aria-live="polite" className="text-xs text-ink-500">
        {loading ? s.loadingMore : hasMore ? "" : s.endOfResults}
      </p>

      {hasMore && (
        <button
          type="button"
          onClick={onLoadMore}
          disabled={loading}
          className="rounded-xl border border-ink-100 bg-surface px-5 py-2 text-xs font-medium
                     text-ink-700 shadow-card transition-colors hover:bg-ink-50 hover:text-ink-900
                     disabled:cursor-not-allowed disabled:opacity-50"
        >
          {s.loadMore}
        </button>
      )}
    </div>
  );
}

import type { ReactNode, RefObject } from "react";
import type { Stats } from "../api";
import { localizeDigits } from "../format";
import { t, type Lang } from "../i18n";
import { sourceLabel } from "../sources";
import { HoodMark } from "./Logo";
import { SearchBar } from "./SearchBar";

/**
 * The banner, and the only part of the page a first-time visitor is guaranteed
 * to read.
 *
 * It is centred rather than start-aligned on purpose: with a single call to
 * action, a centred column puts the claim, the proof and the search box on one
 * vertical line, so the eye lands on the box without crossing an empty half of
 * the screen — which is exactly what the start-aligned version was doing.
 *
 * The order is the argument. A category line so the reader knows what they are
 * looking at, the promise, why it is hard, the box to act in, then the numbers
 * that make the promise believable. Proof *after* the ask, never before it: it
 * is there to remove doubt on the way to pressing, not to be studied first.
 *
 * On the landing screen the band owns the whole first viewport, so a visitor
 * meets the claim and the box on their own — the grid and the filter column
 * begin one scroll down rather than crowding into the same fold and competing
 * with the ask. The cue at the foot is what says there is more, since a screen
 * that ends exactly at the fold otherwise looks like the whole page.
 *
 * Once a search has run *and* the reader has scrolled past it, the whole
 * apparatus folds down to the box and the strapline. Marketing copy that keeps
 * re-arguing its case above someone's results is just something they have to
 * scroll past. Both halves of that condition matter: folding on the search
 * alone made the banner flash and vanish under a reader who had reloaded a
 * shared result URL and not yet moved, and the fold is only invisible — and so
 * only free — while the band is off the screen.
 */
export function Hero({
  lang,
  stats,
  query,
  loading,
  compact,
  bandRef,
  searchRef,
  onSearch,
  onAppraise,
  onExplore,
}: {
  lang: Lang;
  stats: Stats | null;
  query: string;
  loading: boolean;
  compact: boolean;
  bandRef: RefObject<HTMLElement | null>;
  searchRef: RefObject<HTMLDivElement | null>;
  onSearch: (query: string) => void;
  onAppraise: () => void;
  onExplore: () => void;
}) {
  const s = t(lang);
  const n = (value: number) => localizeDigits(value.toLocaleString("en-US"), lang);

  // Busiest source first: the strip is a credibility claim, and the site a
  // reader recognises should be the one they see.
  const sources = Object.entries(stats?.by_source ?? {})
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1]);

  return (
    <section
      ref={bandRef}
      className={`hero-band ${
        compact
          ? "pb-5 pt-6"
          : // Minus the sticky header, so the band ends where the viewport does
            // and the first card sits just past the fold. `svh` because the
            // mobile URL bar must not push the cue off the screen it announces.
            "flex min-h-[calc(100svh-3.5rem)] flex-col justify-center pb-8 pt-8 sm:pt-12"
      }`}
    >
      {/* A watermark, not an illustration: the band's one nod to what the site
          is about, parked in the corner at an opacity where it reads as texture
          and never competes with the claim or the box. Hidden on phones, where
          there is no empty corner for it to fill. */}
      {!compact && <CornerCarMark />}

      <div className="shell relative text-center">
        {!compact && (
          <span
            className="inline-flex items-center gap-2 rounded-full border border-brand/20 bg-brand-soft
                       px-3.5 py-1.5 text-xs font-semibold text-brand-dark"
          >
            <SparkIcon />
            {s.heroEyebrow}
          </span>
        )}

        {/* One claim, in the buyer's own terms, promising an outcome rather than
            describing a feature. It is the strongest sentence we have; the rest
            of the banner exists to make it credible. */}
        <h1
          className={`mx-auto text-balance font-extrabold tracking-tight text-ink-900 ${
            compact
              ? "text-base sm:text-lg"
              : "mt-5 max-w-4xl text-3xl leading-[1.25] sm:text-4xl lg:text-[2.75rem]"
          }`}
        >
          {s.hiddenPriceHeadline}
        </h1>

        {!compact && (
          <p className="mx-auto mt-4 max-w-5xl text-sm leading-relaxed text-ink-500 sm:text-base">
            {s.hiddenPriceBody}
          </p>
        )}

        {/* The ask. Nothing else on the page is this size or this colour. */}
        <div
          ref={searchRef}
          id="search"
          className={`mx-auto max-w-3xl scroll-mt-24 ${compact ? "mt-3" : "mt-7"}`}
        >
          {/* Two rows of suggestions above somebody's results is a landing page
              refusing to get out of the way; the examples were the demonstration
              of how to ask, and once they have asked it is over. */}
          <SearchBar
            lang={lang}
            initial={query}
            loading={loading}
            onSearch={onSearch}
            showExamples={!compact}
          />
        </div>

        {!compact && (
          <p className="mt-3 flex items-center justify-center gap-1.5 text-xs text-ink-500">
            <CheckIcon />
            {s.heroCtaNote}
          </p>
        )}

        {/* The other door, and deliberately the quieter one. A visitor who has
            come to buy should meet exactly one loud ask; this is here for the
            other half of the market — the person holding a car and wondering
            what it is worth — and it says so in one line rather than competing
            with the box above it. */}
        {!compact && (
          <p className="mt-5 text-xs text-ink-500">
            {s.heroSellPrompt}{" "}
            <button
              type="button"
              onClick={onAppraise}
              className="font-semibold text-brand-dark underline underline-offset-2 hover:text-brand"
            >
              {s.appraiseNav}
            </button>
          </p>
        )}

        {/* Proof, in that order: scale, then the specific problem we solve, then
            how much of it we have actually solved. Real figures from the corpus,
            because a rounded marketing number is the one thing a sceptical buyer
            will check. */}
        {!compact && stats && (
          <>
            <div
              className="card mx-auto mt-9 flex max-w-3xl flex-wrap justify-center gap-y-4 px-2 py-4
                         sm:flex-nowrap"
            >
              <Figure value={n(stats.total)} label={s.totalListings} lang={lang} />
              <Figure
                value={`${localizeDigits(String(stats.negotiable_pct), lang)}٪`}
                label={s.hiddenPrice}
                lang={lang}
                tone="brand"
              />
              <Figure
                value={n(stats.hidden_prices_recovered)}
                label={s.pricesRecovered}
                lang={lang}
                tone="deal"
              />
            </div>

            {sources.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center justify-center gap-x-2 gap-y-1.5 text-xs text-ink-500">
                <span>{s.proofSources}</span>
                {sources.map(([source, count]) => (
                  <span key={source} className="chip bg-surface">
                    {sourceLabel(source, lang)}
                    <span className="text-ink-300">{n(count)}</span>
                  </span>
                ))}
                <span className="text-ink-300">·</span>
                <span>
                  {n(stats.brands)} {s.proofBrands}
                </span>
                <span className="text-ink-300">·</span>
                <span>
                  {n(stats.cities)} {s.proofCities}
                </span>
              </div>
            )}
          </>
        )}

        {/* What they walk away with, in three. Placed last because a visitor who
            already typed something never needed to read it. */}
        {!compact && (
          <div className="mx-auto mt-10 grid max-w-4xl gap-3 text-start sm:grid-cols-3">
            <Value icon={<TagIcon />} title={s.vpPrice} body={s.vpPriceBody} />
            <Value icon={<ShieldIcon />} title={s.vpHealth} body={s.vpHealthBody} />
            <Value icon={<TargetIcon />} title={s.vpFit} body={s.vpFitBody} />
          </div>
        )}

        {/* The only thing on the band that admits there is a page below it. A
            button rather than a decoration, because the visitor who takes the
            hint with a click deserves the same trip as the one who scrolls. */}
        {!compact && (
          <button
            type="button"
            onClick={onExplore}
            className="group mx-auto mt-9 inline-flex items-center gap-2 rounded-full border
                       border-ink-100 bg-surface/70 px-4 py-2 text-xs font-medium text-ink-500
                       transition-colors hover:border-brand/30 hover:text-brand-dark"
          >
            {s.heroScrollCue}
            <ChevronDownIcon />
          </button>
        )}
      </div>
    </section>
  );
}

/**
 * The brand glyph blown up to poster size and parked in the bottom corner of
 * the banner, cropped by two edges — the same ghost the share card carries, at
 * the same proportions (a third of it past the start edge, a quarter past the
 * bottom), so the page a link opens onto matches the card that was shared.
 *
 * It is the mark itself rather than a drawing of a car: one geometry, so the
 * watermark can never drift away from the logo in the header above it.
 */
function CornerCarMark() {
  return (
    <HoodMark
      // Physically left in both directions. The band is a picture, not a
      // paragraph, and mirroring the ghost with the text direction would only
      // move it under the search box on the Persian side.
      className="pointer-events-none absolute -bottom-[7rem] -left-[8.8rem] hidden h-[26rem] w-[26rem]
                 text-brand opacity-[0.07] dark:opacity-[0.055] sm:block
                 lg:-bottom-[9.7rem] lg:-left-[12.2rem] lg:h-[36rem] lg:w-[36rem]"
      strokeWidth={1.4}
    />
  );
}

/** One number in the proof bar: the figure loud, the caption quiet. */
function Figure({
  value,
  label,
  lang,
  tone = "ink",
}: {
  value: string;
  label: string;
  lang: Lang;
  tone?: "ink" | "brand" | "deal";
}) {
  const toneClass = { ink: "text-ink-900", brand: "text-brand", deal: "text-deal" }[tone];

  return (
    <div
      className="flex-1 basis-1/3 border-s border-ink-100 px-2 first:border-s-0 sm:px-3"
      dir={lang === "fa" ? "rtl" : "ltr"}
    >
      {/* Three across even on the narrowest phone, so the figures stay a row of
          proof rather than a stack of unrelated numbers — which is what sets the
          ceiling on the type size here. */}
      <p className={`text-xl font-extrabold tabular-nums sm:text-2xl lg:text-[1.75rem] ${toneClass}`}>
        {value}
      </p>
      <p className="mt-0.5 text-[11px] text-ink-500 sm:text-xs">{label}</p>
    </div>
  );
}

function Value({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <div className="flex gap-3 rounded-2xl border border-ink-100 bg-surface/60 p-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-dark">
        {icon}
      </span>
      <span>
        <span className="block text-sm font-semibold text-ink-900">{title}</span>
        <span className="mt-1 block text-xs leading-relaxed text-ink-500">{body}</span>
      </span>
    </div>
  );
}

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

function SparkIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" {...stroke} aria-hidden>
      <path d="M12 3.5 13.7 9l5.5 1.7-5.5 1.7L12 18l-1.7-5.6L4.8 10.7 10.3 9z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 text-deal" {...stroke} aria-hidden>
      <path d="m4.5 12.5 5 5 10-11" />
    </svg>
  );
}

function TagIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...stroke} aria-hidden>
      <path d="M3.5 11.2V4.8a1.3 1.3 0 0 1 1.3-1.3h6.4c.35 0 .68.14.92.38l8 8a1.3 1.3 0 0 1 0 1.84l-6.4 6.4a1.3 1.3 0 0 1-1.84 0l-8-8a1.3 1.3 0 0 1-.38-.92Z" />
      <circle cx="7.8" cy="7.8" r="1.3" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...stroke} aria-hidden>
      <path d="M12 3.2 4.8 6v5.4c0 4.3 3 7.5 7.2 9.4 4.2-1.9 7.2-5.1 7.2-9.4V6Z" />
      <path d="m9 12.2 2.2 2.2 4-4.4" />
    </svg>
  );
}

function ChevronDownIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-y-0.5"
      {...stroke}
      aria-hidden
    >
      <path d="m6 9.5 6 6 6-6" />
    </svg>
  );
}

function TargetIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...stroke} aria-hidden>
      <circle cx="12" cy="12" r="8.3" />
      <circle cx="12" cy="12" r="4.3" />
      <circle cx="12" cy="12" r="0.9" />
    </svg>
  );
}

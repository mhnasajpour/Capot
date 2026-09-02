import { t, type Lang } from "../i18n";
import type { Theme } from "../theme";
import { Logo } from "./Logo";
import { SearchBar } from "./SearchBar";
import { ThemeToggle } from "./ThemeToggle";

/**
 * The bar that never leaves.
 *
 * A landing page with one call to action has to keep that action reachable, so
 * the header is sticky and grows a copy of the search box the moment the hero's
 * own box scrolls away — a reader forty cards deep who thinks of a better
 * question should not have to scroll back up to ask it.
 *
 * That copy is laid out whether or not it is shown, and only its opacity
 * changes, so the brand and the controls never jump sideways as it appears.
 */
export function SiteHeader({
  lang,
  theme,
  query,
  loading,
  showSearch,
  onAppraise,
  onSearch,
  onToggleAppraise,
  onToggleTheme,
  onToggleLang,
}: {
  lang: Lang;
  theme: Theme;
  query: string;
  loading: boolean;
  showSearch: boolean;
  /** True while the appraisal view is the one on screen. */
  onAppraise: boolean;
  onSearch: (query: string) => void;
  onToggleAppraise: () => void;
  onToggleTheme: () => void;
  onToggleLang: () => void;
}) {
  const s = t(lang);

  return (
    <header
      className={`sticky top-0 z-30 border-b bg-surface/85 backdrop-blur-md transition-colors
                  ${showSearch ? "border-ink-100 shadow-card" : "border-transparent"}`}
    >
      <div className="shell flex items-center gap-3 py-2.5 sm:gap-4">
        {/* The brand lockup. The mark tilts a couple of degrees on hover, which
            is the hood lifting — the one bit of motion the header gets, and it
            says what the name means without a word of copy. */}
        <a
          href="#top"
          className="group flex shrink-0 items-center gap-2.5"
          aria-label={`${s.brand} — ${s.tagline}`}
        >
          <Logo
            className="h-9 w-9 transition-transform duration-200 group-hover:-rotate-3
                       group-hover:scale-105"
          />
          <span className="flex flex-col leading-tight">
            <span className="text-[17px] font-extrabold tracking-tight text-ink-900">{s.brand}</span>
            <span className="hidden text-[11px] text-ink-500 sm:block">{s.tagline}</span>
          </span>
        </a>

        {/* The persistent way back to the one action on the page. */}
        <div
          className={`min-w-0 flex-1 transition-all duration-200 md:px-4 ${
            showSearch
              ? "translate-y-0 opacity-100"
              : "pointer-events-none invisible -translate-y-1 opacity-0"
          }`}
          aria-hidden={!showSearch}
        >
          <div className="mx-auto hidden max-w-xl md:block">
            <SearchBar
              lang={lang}
              initial={query}
              loading={loading}
              onSearch={onSearch}
              variant="compact"
              showExamples={false}
            />
          </div>
        </div>

        <div className="ms-auto flex shrink-0 items-center gap-2 md:ms-0">
          {/* The other question this corpus can answer — "what is mine worth?"
              — and the only way to reach it, so it sits on every screen rather
              than only on the banner a returning visitor scrolls straight past.
              It doubles as the way back, which is why it reads as pressed while
              that view is open. */}
          <button
            onClick={onToggleAppraise}
            aria-pressed={onAppraise}
            className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors
                        ${
                          onAppraise
                            ? "border-brand/30 bg-brand-soft text-brand-dark"
                            : "border-ink-100 text-ink-700 hover:bg-ink-50"
                        }`}
          >
            {onAppraise ? s.search : s.appraiseNav}
          </button>

          {/* Where the corpus comes from, stated before anyone asks. It is the
              one credibility claim worth carrying on every screen — and it steps
              aside when the compact search needs the room. */}
          {!showSearch && (
            <span className="hidden items-center gap-1.5 rounded-full border border-ink-100 bg-ink-50
                             px-3 py-1 text-[11px] font-medium text-ink-700 xl:inline-flex">
              <span className="relative flex h-1.5 w-1.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-deal opacity-70" />
                <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-deal" />
              </span>
              {s.headerTrust}
            </span>
          )}

          <ThemeToggle theme={theme} lang={lang} onToggle={onToggleTheme} />
          <button
            onClick={onToggleLang}
            className="rounded-lg border border-ink-100 px-3 py-1.5 text-xs font-medium text-ink-700
                       transition-colors hover:bg-ink-50"
          >
            {lang === "fa" ? "English" : "فارسی"}
          </button>
        </div>
      </div>
    </header>
  );
}

import { useEffect, useState } from "react";
import { EXAMPLE_QUERIES, t, type Lang } from "../i18n";

type Variant = "hero" | "compact";

/**
 * The one thing on this page we want pressed.
 *
 * Input and button are drawn as a single raised object rather than a field with
 * a button parked next to it: a lone box on a landing page reads as a form to
 * fill in later, while one bar with a magnifier at the head and a coloured
 * button at the tail reads as the way in. `compact` is the same control shrunk
 * into the sticky header, so the way in survives scrolling past the hero.
 */
export function SearchBar({
  lang,
  initial = "",
  loading,
  onSearch,
  variant = "hero",
  showExamples = true,
}: {
  lang: Lang;
  initial?: string;
  loading: boolean;
  onSearch: (query: string) => void;
  variant?: Variant;
  showExamples?: boolean;
}) {
  const s = t(lang);
  const [value, setValue] = useState(initial);
  const hero = variant === "hero";

  // The query can change from outside this component — an example chip, or a
  // filtered URL restored on load — and the box has to show what is actually
  // being searched for.
  useEffect(() => setValue(initial), [initial]);

  const submit = (query: string) => {
    setValue(query);
    onSearch(query);
  };

  return (
    <div className="w-full">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSearch(value);
        }}
        role="search"
        className={`group flex items-center gap-2 rounded-2xl border border-ink-100 bg-surface
                    shadow-card transition-shadow focus-within:border-brand/40
                    focus-within:ring-4 focus-within:ring-brand/10 dark:focus-within:ring-brand/20
                    ${hero ? "p-2 hover:shadow-lg" : "p-1"}`}
      >
        <SearchIcon
          className={`${hero ? "ms-3 h-5 w-5" : "ms-2.5 h-4 w-4"} shrink-0 text-ink-300
                      transition-colors group-focus-within:text-brand`}
        />
        <input
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={s.searchPlaceholder}
          aria-label={s.search}
          className={`min-w-0 flex-1 border-0 bg-transparent text-ink-900 outline-none
                      placeholder:text-ink-300 ${hero ? "px-1 py-2.5 text-base" : "px-1 py-1.5 text-sm"}`}
        />
        <button
          type="submit"
          disabled={loading}
          className={`shrink-0 whitespace-nowrap rounded-xl bg-brand font-semibold text-white
                      transition-colors hover:bg-brand-strong disabled:opacity-60
                      ${hero ? "px-7 py-2.5 text-sm sm:px-9" : "px-4 py-1.5 text-xs"}`}
        >
          {loading ? s.loading : s.search}
        </button>
      </form>

      {/* Four ways in for the reader who has no words ready. On a page whose
          entire promise is "ask in your own language", a blank box is the
          highest-friction thing we could offer — these are the demonstration. */}
      {showExamples && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-500">{s.examples}:</span>
          {EXAMPLE_QUERIES[lang].map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => submit(example)}
              className="chip bg-surface transition-colors hover:border-brand/30 hover:bg-brand-soft
                         hover:text-brand-dark"
            >
              {example}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden
    >
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  );
}

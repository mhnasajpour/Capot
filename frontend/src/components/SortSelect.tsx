import { SORT_KEYS, type SortKey } from "../filters";
import { t, type Lang } from "../i18n";

/**
 * Result ordering.
 *
 * The default stays the value x health x fit ranking the product is built on —
 * these alternatives exist because browsing by filter is a different activity
 * from asking a question, and "best overall" is not always what is wanted.
 */
export function SortSelect({
  value,
  lang,
  onChange,
}: {
  value: SortKey;
  lang: Lang;
  onChange: (next: SortKey) => void;
}) {
  const s = t(lang);

  return (
    <label className="flex items-center gap-1.5 text-xs text-ink-500">
      <span className="whitespace-nowrap">{s.sortBy}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as SortKey)}
        className="rounded-lg border border-ink-100 bg-surface px-2 py-1.5 text-xs
                   text-ink-900 outline-none focus:border-brand/40"
      >
        {SORT_KEYS.map((key) => (
          <option key={key} value={key}>
            {s.sortLabels[key]}
          </option>
        ))}
      </select>
    </label>
  );
}

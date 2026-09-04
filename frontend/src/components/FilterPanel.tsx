import { useMemo, useState } from "react";
import type { FeatureCatalogue, FeatureCounts, FeatureSpec, FeatureValue } from "../api";
import { formatMileage, formatPrice, localizeDigits } from "../format";
import {
  ENUM_FIELDS,
  RANGE_FIELDS,
  clearAll,
  clearFeature,
  isFeatureActive,
  toggleValue,
  type Filters,
  type NumberKey,
} from "../filters";
import { t, type Lang } from "../i18n";

/**
 * The filter sidebar.
 *
 * Every section here is generated from `/api/features`, never hard-coded — the
 * backend derives the catalogue from the corpus, so a brand that appears in
 * tomorrow's crawl shows up here without anyone editing this file. What this
 * component decides is only *how* each kind of feature is presented.
 *
 * Counts come from the search response and are leave-one-out, which is what
 * makes multi-select work: with «هیوندای» ticked the panel still shows how many
 * Kias are available to add, instead of reporting every other brand as zero.
 */

/** Sections open on first paint. The rest stay collapsed so the panel is scannable. */
const OPEN_BY_DEFAULT = new Set(["brand", "price", "body_type"]);

/** Above this many options, the list gets a type-ahead. */
const SEARCHABLE_ABOVE = 12;
/** How many options to show before "show more". */
const VISIBLE_LIMIT = 8;

export function FilterPanel({
  catalogue,
  counts,
  filters,
  lang,
  onChange,
}: {
  catalogue: FeatureCatalogue;
  counts: FeatureCounts | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);

  return (
    <div className="flex flex-col gap-1">
      {catalogue.groups.map((group) => {
        const features = catalogue.features.filter((f) => f.group === group.key);
        if (!features.length) return null;
        return (
          <section key={group.key} className="mb-2">
            <h3 className="px-1 pb-1 pt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-300">
              {lang === "fa" ? group.label_fa : group.label_en}
            </h3>
            {features.map((feature) => (
              <FeatureSection
                key={feature.key}
                feature={feature}
                counts={counts}
                filters={filters}
                lang={lang}
                onChange={onChange}
              />
            ))}
          </section>
        );
      })}
      <button
        type="button"
        onClick={() => onChange(clearAll())}
        className="mt-2 rounded-lg border border-ink-100 px-3 py-2 text-xs font-medium
                   text-ink-700 hover:bg-ink-50"
      >
        {s.clearAll}
      </button>
    </div>
  );
}

/** One collapsible feature, dispatched by kind. */
function FeatureSection({
  feature,
  counts,
  filters,
  lang,
  onChange,
}: {
  feature: FeatureSpec;
  counts: FeatureCounts | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);
  const active = isFeatureActive(filters, feature.key);
  const [open, setOpen] = useState(OPEN_BY_DEFAULT.has(feature.key) || active);

  // A bare checkbox needs no disclosure of its own — it is one line either way.
  if (feature.kind === "bool") {
    return (
      <BoolFilter feature={feature} counts={counts} filters={filters} lang={lang} onChange={onChange} />
    );
  }

  return (
    <div className="border-b border-ink-100 last:border-0">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 px-1 py-2.5 text-start"
      >
        <span className="flex items-center gap-1.5 text-sm font-medium text-ink-900">
          {lang === "fa" ? feature.label_fa : feature.label_en}
          {active && <span className="h-1.5 w-1.5 rounded-full bg-brand" aria-hidden />}
        </span>
        <span className="flex items-center gap-1.5">
          {active && (
            <span
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onChange(clearFeature(filters, feature.key));
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.stopPropagation();
                  onChange(clearFeature(filters, feature.key));
                }
              }}
              className="text-[10px] text-ink-500 underline hover:text-brand"
            >
              {s.clearFilter}
            </span>
          )}
          <span className={`text-ink-300 transition-transform ${open ? "rotate-90" : ""}`}>
            ›
          </span>
        </span>
      </button>

      {open && (
        <div className="pb-3 pe-1 ps-1">
          {feature.kind === "enum" && (
            <EnumFilter feature={feature} counts={counts} filters={filters} lang={lang} onChange={onChange} />
          )}
          {feature.kind === "band" && (
            <BandFilter feature={feature} counts={counts} filters={filters} lang={lang} onChange={onChange} />
          )}
          {feature.kind === "range" && (
            <RangeFilter feature={feature} filters={filters} lang={lang} onChange={onChange} />
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ enum

function EnumFilter({
  feature,
  counts,
  filters,
  lang,
  onChange,
}: {
  feature: FeatureSpec;
  counts: FeatureCounts | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);
  const field = ENUM_FIELDS[feature.key];
  // Read straight out of state: `filters[field] ?? []` minted a fresh array on
  // every render, which made the memo below rebuild every render too.
  const selected = filters[field];
  const [needle, setNeedle] = useState("");
  const [expanded, setExpanded] = useState(false);

  // Live counts for the current result set; before the first search there are
  // none, so the catalogue's corpus-wide counts stand in.
  const liveCounts = useMemo(() => {
    const entries = counts?.[feature.key]?.values ?? [];
    return new Map(entries.map((e) => [e.value, e.count]));
  }, [counts, feature.key]);

  const options = useMemo(() => {
    let values = feature.values ?? [];

    // A model belongs to a brand: showing all 387 at once is noise, so the list
    // narrows to whatever brands are selected. With none selected we show the
    // most common models rather than an empty box.
    if (feature.parent === "brand" && filters.brands.length) {
      values = values.filter((v) => v.parent && filters.brands.includes(v.parent));
    }

    const query = needle.trim().toLowerCase();
    if (query) {
      values = values.filter(
        (v) =>
          v.label_fa.toLowerCase().includes(query) ||
          v.label_en.toLowerCase().includes(query) ||
          String(v.value).toLowerCase().includes(query),
      );
    }

    // Selected values stay visible even when the live count drops them, so a
    // choice never silently disappears from the panel that made it.
    const withCounts = values.map((v) => ({
      ...v,
      live: liveCounts.size ? (liveCounts.get(v.value) ?? 0) : v.count,
    }));
    withCounts.sort((a, b) => {
      const aSel = selected.includes(a.value) ? 0 : 1;
      const bSel = selected.includes(b.value) ? 0 : 1;
      return aSel - bSel || b.live - a.live;
    });
    return withCounts;
  }, [feature, filters.brands, needle, liveCounts, selected]);

  const searchable = (feature.values?.length ?? 0) > SEARCHABLE_ABOVE;
  const visible = expanded || needle ? options : options.slice(0, VISIBLE_LIMIT);

  return (
    <div className="flex flex-col gap-1.5">
      {searchable && (
        <input
          type="search"
          value={needle}
          onChange={(e) => setNeedle(e.target.value)}
          placeholder={s.searchInList}
          className="mb-1 w-full rounded-lg border border-ink-100 bg-surface px-2.5 py-1.5
                     text-xs outline-none placeholder:text-ink-300 focus:border-brand/40"
        />
      )}

      {feature.parent === "brand" && !filters.brands.length && !needle && (
        <p className="pb-1 text-[10px] text-ink-300">{s.selectBrandFirst}</p>
      )}

      {visible.length === 0 && (
        <p className="py-1 text-xs text-ink-300">{s.noMatchingOptions}</p>
      )}

      {visible.map((option) => {
        const checked = selected.includes(option.value);
        // Zero-count options are greyed rather than hidden: "we have none of
        // these right now" is information, and a list that reshuffles itself on
        // every click is disorienting.
        const empty = option.live === 0 && !checked;
        return (
          <label
            key={option.value}
            className={`flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1
                        text-xs hover:bg-ink-50 ${empty ? "opacity-40" : ""}`}
          >
            <input
              type="checkbox"
              checked={checked}
              onChange={() => onChange(toggleValue(filters, field, option.value))}
              className="h-3.5 w-3.5 shrink-0 accent-brand"
            />
            <span className="flex-1 truncate text-ink-700">
              {lang === "fa" ? option.label_fa : option.label_en}
            </span>
            <span className="shrink-0 tabular-nums text-[10px] text-ink-300">
              {localizeDigits(String(option.live), lang)}
            </span>
          </label>
        );
      })}

      {!needle && options.length > VISIBLE_LIMIT && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="mt-0.5 self-start text-[11px] font-medium text-brand hover:underline"
        >
          {expanded ? s.showLess : `${s.showMore} (${localizeDigits(String(options.length - VISIBLE_LIMIT), lang)})`}
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ band

/** Paint condition — ordered, so it is a single choice, not a multi-select. */
function BandFilter({
  feature,
  counts,
  filters,
  lang,
  onChange,
}: {
  feature: FeatureSpec;
  counts: FeatureCounts | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);
  const live = new Map((counts?.[feature.key]?.values ?? []).map((e) => [e.value, e.count]));

  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1 text-xs hover:bg-ink-50">
        <input
          type="radio"
          name={feature.key}
          checked={filters.paint === null}
          onChange={() => onChange({ ...filters, paint: null })}
          className="h-3.5 w-3.5 accent-brand"
        />
        <span className="text-ink-700">{s.anyValue}</span>
      </label>
      {(feature.values ?? []).map((band: FeatureValue) => (
        <label
          key={band.value}
          className="flex cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1 text-xs hover:bg-ink-50"
        >
          <input
            type="radio"
            name={feature.key}
            checked={filters.paint === band.value}
            onChange={() => onChange({ ...filters, paint: band.value })}
            className="h-3.5 w-3.5 shrink-0 accent-brand"
          />
          <span className="flex-1 truncate text-ink-700">
            {lang === "fa" ? band.label_fa : band.label_en}
          </span>
          <span className="shrink-0 tabular-nums text-[10px] text-ink-300">
            {localizeDigits(String(live.get(band.value) ?? band.count), lang)}
          </span>
        </label>
      ))}
    </div>
  );
}

// ----------------------------------------------------------------- range

function RangeFilter({
  feature,
  filters,
  lang,
  onChange,
}: {
  feature: FeatureSpec;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);
  const [minField, maxField] = RANGE_FIELDS[feature.key] ?? [null, null];

  // A one-sided range is a slider: "under N kilometres", "at least N health".
  // Two-sided ones get number inputs, because a dual-thumb slider is a poor way
  // to enter a specific figure and a worse one in RTL.
  if (feature.bound === "max" && maxField) {
    return <SliderFilter feature={feature} field={maxField} filters={filters} lang={lang} onChange={onChange} bound="max" />;
  }
  if (feature.bound === "min" && minField) {
    return <SliderFilter feature={feature} field={minField} filters={filters} lang={lang} onChange={onChange} bound="min" />;
  }

  return (
    <div className="flex flex-col gap-2">
      {feature.key === "price" && (
        <PricePresets filters={filters} lang={lang} onChange={onChange} max={feature.max ?? 0} />
      )}
      <div className="flex items-center gap-2">
        <NumberBox
          label={s.from}
          value={toDisplay(feature, minField ? filters[minField] : null)}
          placeholder={toDisplay(feature, feature.min ?? null)}
          step={displayStep(feature)}
          lang={lang}
          onCommit={(v) => minField && onChange({ ...filters, [minField]: fromDisplay(feature, v) })}
        />
        <span className="text-ink-300">—</span>
        <NumberBox
          label={s.to}
          value={toDisplay(feature, maxField ? filters[maxField] : null)}
          placeholder={toDisplay(feature, feature.max ?? null)}
          step={displayStep(feature)}
          lang={lang}
          onCommit={(v) => maxField && onChange({ ...filters, [maxField]: fromDisplay(feature, v) })}
        />
      </div>
      <p className="text-[10px] text-ink-300">{unitHint(feature, lang)}</p>
    </div>
  );
}

/**
 * Prices are quoted in millions here, not raw toman.
 *
 * Iranian buyers say «۸۰۰ میلیون», never «۸۰۰٬۰۰۰٬۰۰۰», and a ten-digit number
 * box invites a zero-counting mistake that silently returns the wrong cars.
 */
const PRICE_UNIT = 1_000_000;

function toDisplay(feature: FeatureSpec, value: number | null): number | null {
  if (value === null) return null;
  return feature.key === "price" ? Math.round(value / PRICE_UNIT) : value;
}

function fromDisplay(feature: FeatureSpec, value: number | null): number | null {
  if (value === null) return null;
  return feature.key === "price" ? Math.round(value * PRICE_UNIT) : value;
}

function displayStep(feature: FeatureSpec): number {
  if (feature.key === "price") return 50;
  return feature.step ?? 1;
}

function unitHint(feature: FeatureSpec, lang: Lang): string {
  const s = t(lang);
  if (feature.key === "price") return s.million;
  if (feature.unit === "km") return lang === "fa" ? "کیلومتر" : "km";
  if (feature.unit) return feature.unit;
  return "";
}

function NumberBox({
  label,
  value,
  placeholder,
  step,
  lang,
  onCommit,
}: {
  label: string;
  value: number | null;
  placeholder: number | null;
  step: number;
  lang: Lang;
  onCommit: (value: number | null) => void;
}) {
  // Local state so typing does not fire a search on every keystroke; the value
  // is committed on blur or Enter.
  const [draft, setDraft] = useState<string | null>(null);
  const shown = draft ?? (value === null ? "" : String(value));

  const commit = () => {
    if (draft === null) return;
    const trimmed = draft.trim();
    const parsed = trimmed === "" ? null : Number(trimmed);
    onCommit(parsed !== null && Number.isFinite(parsed) ? parsed : null);
    setDraft(null);
  };

  return (
    <label className="flex-1">
      <span className="mb-0.5 block text-[10px] text-ink-500">{label}</span>
      <input
        type="number"
        inputMode="numeric"
        step={step}
        value={shown}
        placeholder={placeholder === null ? "" : String(placeholder)}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
            (e.target as HTMLInputElement).blur();
          }
        }}
        dir={lang === "fa" ? "rtl" : "ltr"}
        className="w-full rounded-lg border border-ink-100 bg-surface px-2 py-1.5 text-xs
                   tabular-nums outline-none placeholder:text-ink-300 focus:border-brand/40"
      />
    </label>
  );
}

function SliderFilter({
  feature,
  field,
  filters,
  lang,
  onChange,
  bound,
}: {
  feature: FeatureSpec;
  field: NumberKey;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
  bound: "min" | "max";
}) {
  const min = feature.min ?? 0;
  const max = feature.max ?? 100;
  const current = filters[field] ?? (bound === "max" ? max : min);
  const [dragging, setDragging] = useState<number | null>(null);
  const shown = dragging ?? current;

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-ink-700">{formatRangeValue(feature, shown, lang)}</span>
        {filters[field] !== null && (
          <button
            type="button"
            onClick={() => onChange({ ...filters, [field]: null })}
            className="text-[10px] text-ink-500 underline hover:text-brand"
          >
            {t(lang).clearFilter}
          </button>
        )}
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={feature.step ?? 1}
        value={shown}
        // Track the thumb locally while dragging, commit on release — otherwise
        // every pixel of travel fires a search.
        onChange={(e) => setDragging(Number(e.target.value))}
        onPointerUp={() => {
          if (dragging !== null) onChange({ ...filters, [field]: dragging });
          setDragging(null);
        }}
        onKeyUp={() => {
          if (dragging !== null) onChange({ ...filters, [field]: dragging });
          setDragging(null);
        }}
        className="w-full accent-brand"
      />
    </div>
  );
}

function formatRangeValue(feature: FeatureSpec, value: number, lang: Lang): string {
  const prefix = feature.bound === "max" ? (lang === "fa" ? "تا " : "up to ") : (lang === "fa" ? "از " : "from ");
  if (feature.key === "price") return prefix + formatPrice(value, lang);
  if (feature.key === "mileage") return prefix + formatMileage(value, lang);
  const decimals = feature.decimals ?? 0;
  const text = localizeDigits(value.toFixed(decimals), lang);
  const unit = feature.unit ? ` ${unitHint(feature, lang)}` : "";
  // `prefix` is always non-empty, so there is no empty-string case to fall back
  // from — this used to end `|| s.anyValue`, which could never be reached.
  return `${prefix}${text}${unit}`;
}

/**
 * Price bands buyers already think in. Faster than typing two numbers, and the
 * reason the price section is open by default.
 */
function PricePresets({
  filters,
  lang,
  onChange,
  max,
}: {
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
  max: number;
}) {
  const bands: [number | null, number | null][] = [
    [null, 500_000_000],
    [500_000_000, 1_000_000_000],
    [1_000_000_000, 2_000_000_000],
    [2_000_000_000, 5_000_000_000],
    [5_000_000_000, null],
  ];

  return (
    <div className="flex flex-wrap gap-1">
      {bands.map(([lo, hi]) => {
        const selected = filters.price_min === lo && filters.price_max === hi;
        const label =
          lo === null
            ? `${lang === "fa" ? "تا" : "under"} ${formatPrice(hi, lang)}`
            : hi === null
              ? `${formatPrice(lo, lang)}+`
              : `${formatPrice(lo, lang)} – ${formatPrice(hi, lang)}`;
        return (
          <button
            key={`${lo}-${hi}`}
            type="button"
            onClick={() =>
              onChange(
                selected
                  ? { ...filters, price_min: null, price_max: null }
                  : { ...filters, price_min: lo, price_max: hi === null ? null : Math.min(hi, max || hi) },
              )
            }
            className={`chip transition-colors ${
              selected
                ? "border-brand/30 bg-brand-soft text-brand-dark"
                : "hover:border-brand/30 hover:text-brand-dark"
            }`}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

// ------------------------------------------------------------------ bool

function BoolFilter({
  feature,
  counts,
  filters,
  lang,
  onChange,
}: {
  feature: FeatureSpec;
  counts: FeatureCounts | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const key = feature.key as "below_market" | "inspected" | "has_image";
  const live = counts?.[feature.key]?.count ?? feature.count ?? 0;

  return (
    <label className="flex cursor-pointer items-center gap-2 border-b border-ink-100 px-1 py-2.5 text-sm last:border-0 hover:bg-ink-50">
      <input
        type="checkbox"
        checked={filters[key]}
        onChange={() => onChange({ ...filters, [key]: !filters[key] })}
        className="h-3.5 w-3.5 shrink-0 accent-brand"
      />
      <span className="flex-1 text-ink-900">
        {lang === "fa" ? feature.label_fa : feature.label_en}
      </span>
      <span className="shrink-0 tabular-nums text-[10px] text-ink-300">
        {localizeDigits(String(live), lang)}
      </span>
    </label>
  );
}

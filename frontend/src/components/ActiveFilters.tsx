import type { FeatureCatalogue } from "../api";
import { formatMileage, formatPrice, localizeDigits } from "../format";
import {
  BOOL_KEYS,
  LIST_KEYS,
  NUMBER_KEYS,
  clearAll,
  countActive,
  toggleValue,
  type Filters,
  type ListKey,
  type NumberKey,
} from "../filters";
import { t, type Lang } from "../i18n";

/**
 * The removable chip row above the results.
 *
 * The sidebar can be scrolled away or closed on mobile, so without this a
 * buyer loses track of what is narrowing their results and reads an empty page
 * as "you have no cars" rather than "you asked for too much".
 *
 * Labels are resolved from the catalogue, because a value like `passenger_car`
 * or `hyundai` is not what the buyer clicked on — «سدان» and «هیوندای» are.
 */
export function ActiveFilters({
  catalogue,
  filters,
  lang,
  onChange,
}: {
  catalogue: FeatureCatalogue | null;
  filters: Filters;
  lang: Lang;
  onChange: (next: Filters) => void;
}) {
  const s = t(lang);
  if (countActive(filters) === 0) return null;

  const chips: { key: string; label: string; onRemove: () => void }[] = [];

  // --- multi-selects, one chip per chosen value
  const featureForField = (field: ListKey) =>
    catalogue?.features.find((f) => FIELD_TO_FEATURE[field] === f.key);

  for (const field of LIST_KEYS) {
    const feature = featureForField(field);
    for (const value of filters[field]) {
      const option = feature?.values?.find((v) => v.value === value);
      const label = option ? (lang === "fa" ? option.label_fa : option.label_en) : value;
      chips.push({
        key: `${field}:${value}`,
        label,
        onRemove: () => onChange(toggleValue(filters, field, value)),
      });
    }
  }

  // --- numeric bounds
  for (const field of NUMBER_KEYS) {
    const value = filters[field];
    if (value === null) continue;
    chips.push({
      key: field,
      label: numberLabel(field, value, lang),
      onRemove: () => onChange({ ...filters, [field]: null }),
    });
  }

  // --- paint band
  if (filters.paint) {
    const band = catalogue?.features
      .find((f) => f.key === "paint")
      ?.values?.find((v) => v.value === filters.paint);
    chips.push({
      key: "paint",
      label: band ? (lang === "fa" ? band.label_fa : band.label_en) : filters.paint,
      onRemove: () => onChange({ ...filters, paint: null }),
    });
  }

  // --- toggles
  for (const field of BOOL_KEYS) {
    if (!filters[field]) continue;
    const feature = catalogue?.features.find((f) => f.key === field);
    chips.push({
      key: field,
      label: feature ? (lang === "fa" ? feature.label_fa : feature.label_en) : field,
      onRemove: () => onChange({ ...filters, [field]: false } as Filters),
    });
  }

  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <button
          key={chip.key}
          type="button"
          onClick={chip.onRemove}
          className="chip border-brand/20 bg-brand-soft text-brand-dark transition-colors hover:bg-brand/10"
        >
          <span>{chip.label}</span>
          <span className="text-brand/60" aria-hidden>
            ✕
          </span>
        </button>
      ))}
      <button
        type="button"
        onClick={() => onChange(clearAll())}
        className="text-[11px] font-medium text-ink-500 underline hover:text-brand"
      >
        {s.clearAll}
      </button>
    </div>
  );
}

/** Filter field -> the catalogue feature that carries its labels. */
const FIELD_TO_FEATURE: Record<ListKey, string> = {
  brands: "brand", models: "model", body_types: "body_type",
  transmissions: "transmission", fuels: "fuel", colors: "color",
  cities: "city", sellers: "seller", sources: "source",
};

function numberLabel(field: NumberKey, value: number, lang: Lang): string {
  const s = t(lang);
  const upTo = lang === "fa" ? "تا" : "up to";
  const from = lang === "fa" ? "از" : "from";
  const n = (v: number) => localizeDigits(String(v), lang);

  switch (field) {
    case "price_min":
      return `${from} ${formatPrice(value, lang)}`;
    case "price_max":
      return `${upTo} ${formatPrice(value, lang)}`;
    case "year_min":
      return `${from} ${n(value)}`;
    case "year_max":
      return `${upTo} ${n(value)}`;
    case "mileage_min":
      return `${from} ${formatMileage(value, lang)}`;
    case "mileage_max":
      return `${upTo} ${formatMileage(value, lang)}`;
    case "engine_min":
      return `${from} ${n(value)}L`;
    case "engine_max":
      return `${upTo} ${n(value)}L`;
    case "consumption_max":
      return `${upTo} ${n(value)} ${lang === "fa" ? "لیتر" : "L/100km"}`;
    case "min_health":
      return `${s.health} ${n(value)}+`;
    default:
      return `${field}: ${n(value)}`;
  }
}


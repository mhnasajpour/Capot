/**
 * Filter state, and the URL it serialises to.
 *
 * The URL is the single source of truth on purpose: a filtered search is a
 * thing people send each other («ببین چی پیدا کردم»), and losing it on refresh
 * would make the panel feel disposable. Every selection round-trips through the
 * address bar, so back/forward and reload all behave.
 *
 * The shape mirrors `backend/app/features.py::Filters` exactly — same keys, same
 * comma-separated lists — so there is no translation layer to drift.
 */

export type SortKey =
  | "rank"
  | "price_asc"
  | "price_desc"
  | "year_desc"
  | "mileage_asc"
  | "health_desc"
  | "discount_desc";

export const SORT_KEYS: SortKey[] = [
  "rank", "price_asc", "price_desc", "year_desc",
  "mileage_asc", "health_desc", "discount_desc",
];

/** Multi-select features. The key is both the state field and the query param. */
export const LIST_KEYS = [
  "brands", "models", "body_types", "transmissions", "fuels",
  "colors", "cities", "sellers", "sources",
] as const;

/** Numeric bounds. */
export const NUMBER_KEYS = [
  "price_min", "price_max", "year_min", "year_max", "mileage_min",
  "mileage_max", "engine_min", "engine_max", "consumption_max", "min_health",
] as const;

export const BOOL_KEYS = ["below_market", "inspected", "has_image"] as const;

export type ListKey = (typeof LIST_KEYS)[number];
export type NumberKey = (typeof NUMBER_KEYS)[number];
export type BoolKey = (typeof BOOL_KEYS)[number];

export type Filters = Record<ListKey, string[]> &
  Record<NumberKey, number | null> &
  Record<BoolKey, boolean> & { paint: string | null };

export const EMPTY_FILTERS: Filters = {
  brands: [], models: [], body_types: [], transmissions: [], fuels: [],
  colors: [], cities: [], sellers: [], sources: [],
  price_min: null, price_max: null, year_min: null, year_max: null,
  mileage_min: null, mileage_max: null, engine_min: null, engine_max: null,
  consumption_max: null, min_health: null,
  paint: null,
  below_market: false, inspected: false, has_image: false,
};

/** Which feature key in the catalogue owns which filter fields. */
export const FEATURE_FIELDS: Record<string, (ListKey | NumberKey | BoolKey | "paint")[]> = {
  brand: ["brands"],
  model: ["models"],
  body_type: ["body_types"],
  transmission: ["transmissions"],
  fuel: ["fuels"],
  color: ["colors"],
  city: ["cities"],
  seller: ["sellers"],
  source: ["sources"],
  price: ["price_min", "price_max"],
  year: ["year_min", "year_max"],
  mileage: ["mileage_min", "mileage_max"],
  engine: ["engine_min", "engine_max"],
  consumption: ["consumption_max"],
  health: ["min_health"],
  paint: ["paint"],
  below_market: ["below_market"],
  inspected: ["inspected"],
  has_image: ["has_image"],
};

const isListKey = (key: string): key is ListKey =>
  (LIST_KEYS as readonly string[]).includes(key);
const isNumberKey = (key: string): key is NumberKey =>
  (NUMBER_KEYS as readonly string[]).includes(key);
const isBoolKey = (key: string): key is BoolKey =>
  (BOOL_KEYS as readonly string[]).includes(key);

/** Add or remove one value from a multi-select. */
export function toggleValue(filters: Filters, key: ListKey, value: string): Filters {
  const current = filters[key];
  const next = current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
  return { ...filters, [key]: next };
}

/** How many distinct choices are active — the number on the mobile button. */
export function countActive(filters: Filters): number {
  let n = 0;
  for (const key of LIST_KEYS) n += filters[key].length;
  for (const key of NUMBER_KEYS) if (filters[key] !== null) n += 1;
  for (const key of BOOL_KEYS) if (filters[key]) n += 1;
  if (filters.paint) n += 1;
  return n;
}

/** Is any field belonging to this catalogue feature set? */
export function isFeatureActive(filters: Filters, featureKey: string): boolean {
  return (FEATURE_FIELDS[featureKey] ?? []).some((field) => {
    if (field === "paint") return filters.paint !== null;
    if (isListKey(field)) return filters[field].length > 0;
    if (isNumberKey(field)) return filters[field] !== null;
    if (isBoolKey(field)) return filters[field];
    return false;
  });
}

/** Reset only the fields belonging to one feature. */
export function clearFeature(filters: Filters, featureKey: string): Filters {
  const next = { ...filters };
  for (const field of FEATURE_FIELDS[featureKey] ?? []) {
    if (field === "paint") next.paint = null;
    else if (isListKey(field)) next[field] = [];
    else if (isNumberKey(field)) next[field] = null;
    else if (isBoolKey(field)) next[field] = false;
  }
  return next;
}

export function clearAll(): Filters {
  return { ...EMPTY_FILTERS };
}

/**
 * Serialise to query params. Only what is set is written, so a search with no
 * filters produces the same bare URL it always did.
 *
 * How far the reader has scrolled is deliberately not part of this. The results
 * grid loads as you go, so there is no page number to link to — and a shared
 * link should reopen the search, not someone else's scroll position.
 */
export function toParams(
  filters: Filters,
  q: string,
  sort: SortKey,
): URLSearchParams {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  for (const key of LIST_KEYS) {
    if (filters[key].length) params.set(key, filters[key].join(","));
  }
  for (const key of NUMBER_KEYS) {
    const value = filters[key];
    if (value !== null) params.set(key, String(value));
  }
  for (const key of BOOL_KEYS) {
    if (filters[key]) params.set(key, "true");
  }
  if (filters.paint) params.set("paint", filters.paint);
  if (sort !== "rank") params.set("sort", sort);
  return params;
}

/** Read state back out of a query string. Anything unparseable is ignored. */
export function fromParams(
  search: string,
): { q: string; filters: Filters; sort: SortKey } {
  const params = new URLSearchParams(search);
  const filters: Filters = { ...EMPTY_FILTERS };

  for (const key of LIST_KEYS) {
    const raw = params.get(key);
    if (raw) filters[key] = raw.split(",").map((v) => v.trim()).filter(Boolean);
  }
  for (const key of NUMBER_KEYS) {
    const raw = params.get(key);
    if (raw !== null && raw !== "") {
      const value = Number(raw);
      if (Number.isFinite(value)) filters[key] = value;
    }
  }
  for (const key of BOOL_KEYS) {
    filters[key] = params.get(key) === "true";
  }
  filters.paint = params.get("paint");

  const sort = params.get("sort") as SortKey | null;
  return {
    q: params.get("q") ?? "",
    filters,
    sort: sort && SORT_KEYS.includes(sort) ? sort : "rank",
  };
}

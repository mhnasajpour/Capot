import { toParams, type Filters, type SortKey } from "./filters";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

/** How many results one fetch brings back. Divides evenly by 1, 2, 3 and 4, so
 *  a batch never ends in a half-empty row at any of the grid's breakpoints. */
export const PAGE_SIZE = 24;

export interface PriceBlock {
  asking: number | null;
  effective: number | null;
  is_estimated: boolean;
  is_negotiable: boolean;
  fair_price: number | null;
  delta_pct: number | null;
  confidence: number | null;
  n_comparables: number | null;
  cohort_level: string | null;
  price_flag: string | null;
}

export interface HealthFactor {
  key: string;
  label_fa: string;
  label_en: string;
  impact: number;
}

export interface HealthBlock {
  score: number;
  band_fa: string;
  band_en: string;
  factors: HealthFactor[];
}

export interface Reason {
  fa: string;
  en: string;
  kind: string;
}

export interface CarResult {
  code: string;
  url: string;
  title: string;
  brand_fa: string | null;
  trim: string | null;
  year_display: number | null;
  year_calendar: string | null;
  age: number | null;
  mileage_km: number | null;
  body_status: string | null;
  body_type: string | null;
  body_type_fa: string | null;
  transmission: string | null;
  fuel: string | null;
  body_color: string | null;
  seller: string;
  dealer_name: string | null;
  dealer_score: number | null;
  city: string | null;
  source: string;
  duplicate_of: string[] | null;
  insurance_months: number | null;
  location: string | null;
  image: string | null;
  authenticated: boolean;
  life_styles: string[];
  consumption_l100: number | null;
  power_hp: number | null;
  price: PriceBlock;
  health: HealthBlock;
  scores: { total: number; value: number; health: number; fit: number };
  reasons: Reason[];
}

/** Why retrieval returned what it returned. `mode` is what the empty state
 *  reads to tell the three different failures apart:
 *    entity      — the query named a car and we have it
 *    text        — matched on words the listings actually use
 *    semantic    — matched on intent alone («ماشین برای دختر دانشجو»)
 *    constraints — the wording meant nothing to us, the budget/spec did
 *    none        — no relevance signal; ranking saw the whole corpus
 *    unknown_car — a real car, but no listing of it
 *    nonsense    — nothing in the query refers to a car at all
 */
export type RetrievalMode =
  | "entity" | "text" | "semantic" | "constraints"
  | "none" | "unknown_car" | "nonsense" | "empty";

export interface RetrievalInfo {
  mode: RetrievalMode;
  matched: string[];
  models: string[];
  fuzzy: boolean;
  n_candidates: number;
}

/** One selectable value of an enum or band feature. */
export interface FeatureValue {
  value: string;
  label_fa: string;
  label_en: string;
  count: number;
  /** Enum values scoped by another feature — a model belongs to a brand. */
  parent?: string;
  /** Band values only: the paint grade this band admits. */
  min_grade?: number;
}

/** One filterable car feature, as the backend derived it from the corpus. */
export interface FeatureSpec {
  key: string;
  kind: "enum" | "range" | "band" | "bool";
  group: string;
  label_fa: string;
  label_en: string;
  unit?: string;
  step?: number;
  decimals?: number;
  parent?: string;
  /** Ranges that only make sense as a ceiling ("max") or a floor ("min"). */
  bound?: "both" | "max" | "min";
  values?: FeatureValue[];
  /** Range features: percentile-clamped bounds, plus the true extremes. */
  min?: number;
  max?: number;
  true_min?: number;
  true_max?: number;
  count?: number;
}

export interface FeatureCatalogue {
  total: number;
  groups: { key: string; label_fa: string; label_en: string }[];
  features: FeatureSpec[];
}

/**
 * Live counts for the current result set, keyed by feature.
 *
 * These are **leave-one-out**: a feature's own selection is dropped before its
 * values are counted, so picking «هیوندای» still shows how many Kias are
 * available to add. Counting with the selection applied would report every
 * sibling as zero and make multi-select impossible.
 */
export type FeatureCounts = Record<
  string,
  {
    values?: { value: string; count: number }[];
    count?: number;
    available_min?: number | null;
    available_max?: number | null;
  }
>;

export interface SearchResponse {
  query: string;
  intent: Record<string, unknown>;
  retrieval?: RetrievalInfo;
  /** What the backend actually honoured — echoed back for the chip row. */
  applied?: Record<string, unknown>;
  /** Only ever sent with the first batch of a search: the counts describe the
   *  whole result set, not the batch, so re-sending them with every scroll
   *  would be tens of kilobytes to redraw the panel identically. */
  features?: FeatureCounts | null;
  /** How many results are in this batch. */
  count: number;
  /** How many matched in total. Not shown to the reader — the grid just keeps
   *  loading until `has_more` goes false — but it is what `has_more` is
   *  computed from, and it is worth having in the payload for debugging. */
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
  results: CarResult[];
}

export interface Comparable {
  code: string;
  title: string;
  year_display: number | null;
  mileage_km: number | null;
  price_toman: number | null;
  body_status: string | null;
  url: string;
  source: string | null;
}

export interface CarDetail extends Omit<CarResult, "price" | "scores" | "reasons"> {
  price_block: PriceBlock;
  comparables: Comparable[];
  description: string | null;
  /** Columns the detail endpoint returns from the row but search results omit. */
  model_fa: string | null;
  inside_color: string | null;
  engine_volume_l: number | null;
  acceleration_s: number | null;
  chassis_status: string | null;
  dealer_ad_count: number | null;
  image_count: number | null;
  modified_date: string | null;
  red_flags: { code: string; label_fa: string; label_en: string; severity: string }[] | null;
  positives: string[] | null;
}

/**
 * One car as its owner described it — what the backend understood, echoed back
 * so the form can show it and the user can correct it.
 */
export interface AppraisalCar {
  brand: string | null;
  model: string | null;
  year: number | null;
  mileage_km: number | null;
  transmission: string | null;
  fuel: string | null;
  body_status: string | null;
  body_type: string | null;
  body_color: string | null;
  city: string | null;
  seller: string | null;
  engine_volume_l: number | null;
  description: string | null;
}

export interface AppraisalPrice {
  fair_price: number;
  /** The range around the estimate, from the model's own held-out error. */
  low: number;
  high: number;
  confidence: number;
  n_comparables: number;
  cohort_level: string;
}

/**
 * `status` is the first thing to read. Only `ok` carries a price:
 *   ok           — valued, with a band and the ads behind it
 *   unknown_car  — we could not identify the car, so we will not price it
 *   need_year    — no model year, which is the strongest single input
 *
 * `warnings` are things that are true of a real estimate but qualify it:
 * `brand_new` (zero-km cars are out of the corpus on purpose), `no_mileage`,
 * `no_comparables`.
 */
export interface Appraisal {
  status: "ok" | "unknown_car" | "need_year";
  input: AppraisalCar;
  /** What the prose alone yielded, before the form was overlaid onto it. */
  parsed: AppraisalCar;
  warnings: string[];
  price: AppraisalPrice | null;
  health: HealthBlock | null;
  flags: {
    red_flags: { code: string; label_fa: string; label_en: string; severity: string }[];
    positives: string[];
  };
  /** Live ads for cars like theirs — the same payload the result grid renders. */
  matches: CarResult[];
  /** How closely "like theirs" had to be read: model_year | model | brand | none. */
  match_level: string;
}

export interface Stats {
  total: number;
  negotiable: number;
  negotiable_pct: number;
  priced: number;
  with_estimate: number;
  enriched: number;
  brands: number;
  cities: number;
  by_source: Record<string, number>;
  cross_listed: number;
  hidden_prices_recovered: number;
}

async function get<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

export const api = {
  /**
   * The query string is built by `filters.ts`, so it matches the URL exactly —
   * plus the window this fetch wants.
   *
   * `offset` is how many results the grid already holds, which is the only
   * thing a scrolling list ever needs to say. It stays out of the address bar:
   * a link to a search is a link to the search, not to how far someone had
   * scrolled through it.
   */
  search: (q: string, filters: Filters, sort: SortKey, offset = 0, limit = PAGE_SIZE) => {
    const params = toParams(filters, q, sort);
    params.set("limit", String(limit));
    params.set("offset", String(Math.max(0, offset)));
    return get<SearchResponse>(`/api/search?${params.toString()}`);
  },
  features: () => get<FeatureCatalogue>("/api/features"),
  car: (code: string) => get<CarDetail>(`/api/car/${encodeURIComponent(code)}`),
  stats: () => get<Stats>("/api/stats"),
  /**
   * Value the car the user owns. The params are built by `appraisal.ts` and are
   * the same ones the address bar carries, so an appraisal survives a reload and
   * can be sent to somebody — the rule the filtered search already follows.
   */
  appraise: (params: URLSearchParams) => get<Appraisal>(`/api/appraise?${params.toString()}`),
};

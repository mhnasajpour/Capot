/**
 * The "price my car" form, and the URL it serialises to.
 *
 * Same contract as [filters.ts](./filters.ts): the address bar is the source of
 * truth, the keys here are the query params the backend reads, and there is no
 * translation layer between the two to drift. An appraisal is a thing someone
 * sends to the person they are selling to, so losing it on refresh would make
 * the whole page feel disposable.
 *
 * Every field is a string, including the numeric ones. A form field holds text
 * until the user is done typing it, and coercing "۱۲" to 12 mid-keystroke is how
 * a field starts fighting the person filling it in. The backend parses these
 * anyway — it has to, because they also arrive from a URL somebody edited.
 */

import type { AppraisalCar } from "./api";

/** The car's own fields, in the order the form asks for them. */
export const INPUT_KEYS = [
  "brand", "model", "year", "mileage", "transmission",
  "fuel", "body_status", "body_type", "color", "city", "engine",
] as const;

export type InputKey = (typeof INPUT_KEYS)[number];

/** `q` is the prose; the rest is what they stated explicitly. */
export type AppraisalInput = Record<InputKey, string> & { q: string };

export const EMPTY_INPUT: AppraisalInput = {
  q: "",
  brand: "", model: "", year: "", mileage: "", transmission: "",
  fuel: "", body_status: "", body_type: "", color: "", city: "", engine: "",
};

/** Which catalogue feature supplies each field's options. */
export const FIELD_FEATURE: Partial<Record<InputKey, string>> = {
  brand: "brand",
  model: "model",
  transmission: "transmission",
  fuel: "fuel",
  body_type: "body_type",
  color: "color",
  city: "city",
};

/** Has the user given us anything to work with? */
export function hasInput(input: AppraisalInput): boolean {
  return Boolean(input.q.trim()) || INPUT_KEYS.some((key) => input[key].trim());
}

/** The minimum an appraisal needs before it can return a number at all. */
export function isPriceable(input: AppraisalInput): boolean {
  // Prose can supply all three, so anything typed counts as possibly enough —
  // the backend is the one that decides, and says why when it is not.
  return Boolean(input.q.trim()) || Boolean(input.brand && input.model && input.year);
}

/**
 * Serialise for both the address bar and the API — deliberately one function, so
 * the URL someone shares is exactly the request that produced what they saw.
 * `appraise=1` is what tells `App` to show this view rather than the results grid.
 */
export function toParams(input: AppraisalInput, includeView = false): URLSearchParams {
  const params = new URLSearchParams();
  if (includeView) params.set("appraise", "1");
  if (input.q.trim()) params.set("q", input.q.trim());
  for (const key of INPUT_KEYS) {
    const value = input[key].trim();
    if (value) params.set(key, value);
  }
  return params;
}

/** Read the form back out of a query string. */
export function fromParams(search: string): AppraisalInput {
  const params = new URLSearchParams(search);
  const input: AppraisalInput = { ...EMPTY_INPUT, q: params.get("q") ?? "" };
  for (const key of INPUT_KEYS) {
    input[key] = params.get(key) ?? "";
  }
  return input;
}

/** Is this URL asking for the appraisal view? */
export function isAppraiseUrl(search: string): boolean {
  return new URLSearchParams(search).get("appraise") === "1";
}

/**
 * Fill the empty form fields from what the parser read out of the prose.
 *
 * Only the empty ones. The backend already resolves the same precedence when it
 * prices the car — an explicit value beats a parsed one — and this is that rule
 * made visible: the user sees what we understood, in the fields, and can change
 * any of it. Overwriting a field they had typed in would be the parser winning
 * an argument it is not entitled to win.
 */
export function fillFromParsed(input: AppraisalInput, parsed: AppraisalCar): AppraisalInput {
  const asText = (value: string | number | null) =>
    value === null || value === undefined ? "" : String(value);

  const parsedByKey: Record<InputKey, string> = {
    brand: asText(parsed.brand),
    model: asText(parsed.model),
    year: asText(parsed.year),
    mileage: asText(parsed.mileage_km),
    transmission: asText(parsed.transmission),
    fuel: asText(parsed.fuel),
    body_status: asText(parsed.body_status),
    body_type: asText(parsed.body_type),
    color: asText(parsed.body_color),
    city: asText(parsed.city),
    engine: asText(parsed.engine_volume_l),
  };

  const next = { ...input };
  for (const key of INPUT_KEYS) {
    if (!next[key].trim() && parsedByKey[key]) next[key] = parsedByKey[key];
  }
  return next;
}

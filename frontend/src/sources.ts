import type { Lang } from "./i18n";

/**
 * Where a listing came from, and how to link back to it.
 *
 * The sites do not store their URLs the same way — Bama gives a path
 * (`/car/detail-…`) while Divar, Sheypoor and Karnameh give absolute URLs — so
 * linking back needs to handle both shapes. Keeping the mapping here means the
 * card badge and the detail button can never disagree about what a source is
 * called.
 */
const SOURCES: Record<string, { base: string; fa: string; en: string }> = {
  bama: { base: "https://bama.ir", fa: "باما", en: "Bama" },
  divar: { base: "https://divar.ir", fa: "دیوار", en: "Divar" },
  sheypoor: { base: "https://www.sheypoor.com", fa: "شیپور", en: "Sheypoor" },
  karnameh: { base: "https://karnameh.com", fa: "کارنامه", en: "Karnameh" },
};

const FALLBACK = { base: "", fa: "منبع", en: "source" };

export function sourceLabel(source: string | null | undefined, lang: Lang): string {
  const entry = SOURCES[source ?? ""] ?? FALLBACK;
  return lang === "fa" ? entry.fa : entry.en;
}

/** Absolute link to the original ad, whichever shape the source stored. */
export function listingUrl(source: string | null | undefined, url: string | null | undefined): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  const entry = SOURCES[source ?? ""] ?? FALLBACK;
  return `${entry.base}${url}`;
}

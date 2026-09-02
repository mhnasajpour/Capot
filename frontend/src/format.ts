import type { Lang } from "./i18n";

/**
 * Iranian prices are quoted in toman and run into the billions, so raw digit
 * strings are unreadable. Buyers say "۸۵۰ میلیون" or "۲.۳ میلیارد" — we match
 * that, and render Persian digits in Persian mode.
 */
export function formatPrice(toman: number | null | undefined, lang: Lang): string {
  if (toman === null || toman === undefined || Number.isNaN(toman)) return "—";

  const fa = lang === "fa";
  if (toman >= 1_000_000_000) {
    const value = toman / 1_000_000_000;
    // One decimal unless it lands on a round billion.
    const text = value >= 10 ? value.toFixed(1) : value.toFixed(2).replace(/0$/, "");
    const clean = text.replace(/\.0+$/, "");
    return `${localizeDigits(clean, lang)} ${fa ? "میلیارد" : "B"}`;
  }
  if (toman >= 1_000_000) {
    const value = Math.round(toman / 1_000_000);
    return `${localizeDigits(String(value), lang)} ${fa ? "میلیون" : "M"}`;
  }
  return localizeDigits(toman.toLocaleString("en-US"), lang);
}

export function formatNumber(value: number | null | undefined, lang: Lang): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return localizeDigits(value.toLocaleString("en-US"), lang);
}

/** Swap ASCII digits for Persian ones when rendering Persian. */
export function localizeDigits(text: string, lang: Lang): string {
  if (lang !== "fa") return text;
  const persian = "۰۱۲۳۴۵۶۷۸۹";
  return text.replace(/\d/g, (d) => persian[Number(d)]);
}

export function formatMileage(km: number | null | undefined, lang: Lang): string {
  if (km === null || km === undefined) return "—";
  if (km === 0) return lang === "fa" ? "صفر کیلومتر" : "0 km";
  if (km >= 1000) {
    return `${localizeDigits(Math.round(km / 1000).toString(), lang)}${
      lang === "fa" ? " هزار کیلومتر" : "k km"
    }`;
  }
  return `${localizeDigits(String(km), lang)}${lang === "fa" ? " کیلومتر" : " km"}`;
}

/**
 * Listing timestamps are ISO strings from the crawl. A buyer only cares how
 * stale the ad is, and a Gregorian date would need Jalali conversion to mean
 * anything to a Persian reader — so this reports the age, not the date.
 */
export function formatRelativeDate(iso: string | null | undefined, lang: Lang): string | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;

  const fa = lang === "fa";
  const days = Math.floor((Date.now() - ts) / 86_400_000);
  if (days <= 0) return fa ? "امروز" : "today";
  if (days === 1) return fa ? "دیروز" : "yesterday";
  if (days < 14) return `${localizeDigits(String(days), lang)} ${fa ? "روز پیش" : "days ago"}`;
  if (days < 60) {
    const weeks = Math.round(days / 7);
    return `${localizeDigits(String(weeks), lang)} ${fa ? "هفته پیش" : "weeks ago"}`;
  }
  const months = Math.round(days / 30);
  return `${localizeDigits(String(months), lang)} ${fa ? "ماه پیش" : "months ago"}`;
}

export function formatPercent(value: number | null | undefined, lang: Lang): string {
  if (value === null || value === undefined) return "—";
  const rounded = Math.abs(value) >= 10 ? Math.round(value) : Number(value.toFixed(1));
  return `${localizeDigits(String(Math.abs(rounded)), lang)}٪`.replace("٪", lang === "fa" ? "٪" : "%");
}

/**
 * Colour ramp for the health score: red -> amber -> green. These are applied as
 * inline styles, so they resolve through the theme variables in index.css —
 * the light ramp is too dark to read once the page turns black.
 */
export function healthColor(score: number): string {
  if (score >= 80) return "var(--health-excellent)";
  if (score >= 65) return "var(--health-good)";
  if (score >= 50) return "var(--health-fair)";
  if (score >= 35) return "var(--health-poor)";
  return "var(--health-bad)";
}

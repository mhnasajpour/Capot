import type { PriceBlock } from "../api";
import { formatPercent, formatPrice, localizeDigits } from "../format";
import { t, type Lang } from "../i18n";

/**
 * Price display. Three distinct states, and the distinction is the product:
 *
 *   published + delta   -> asking price, plus how far off market it is
 *   hidden  ("توافقی")  -> our estimate, clearly labelled as an estimate
 *   unknown             -> honest dash, never a fabricated number
 */
export function PriceDisplay({ price, lang }: { price: PriceBlock; lang: Lang }) {
  const s = t(lang);

  const isDeposit = price.price_flag === "deposit";

  if (price.is_estimated && price.effective) {
    return (
      <div>
        <div className="flex items-baseline gap-2">
          <span className="text-xl font-bold text-ink-900">
            ≈ {formatPrice(price.effective, lang)}
          </span>
          <span className="text-xs text-ink-500">{lang === "fa" ? "تومان" : "toman"}</span>
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="chip bg-brand-soft text-brand-dark border-brand/20">
            {s.estimatedPrice}
          </span>
          {/* A deposit listing needs a warning, not the neutral "hidden price"
              note — its advertised figure actively misleads. */}
          {isDeposit ? (
            <span className="chip bg-over-soft text-over border-over/20">{s.depositWarning}</span>
          ) : (
            <span className="text-[11px] text-ink-500 line-through">{s.hiddenPrice}</span>
          )}
        </div>
      </div>
    );
  }

  if (!price.effective) {
    return <div className="text-ink-500 text-sm">{s.hiddenPrice}</div>;
  }

  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span className="text-xl font-bold text-ink-900">{formatPrice(price.effective, lang)}</span>
        <span className="text-xs text-ink-500">{lang === "fa" ? "تومان" : "toman"}</span>
      </div>
      {price.delta_pct !== null && <DeltaBadge price={price} lang={lang} />}
    </div>
  );
}

/** How the asking price compares with the model's fair price. */
export function DeltaBadge({ price, lang }: { price: PriceBlock; lang: Lang }) {
  const s = t(lang);
  const delta = price.delta_pct;
  if (delta === null || delta === undefined) return null;

  const below = delta <= -3;
  const above = delta >= 3;
  const label = below ? s.belowMarket : above ? s.aboveMarket : s.atMarket;
  const tone = below
    ? "bg-deal-soft text-deal border-deal/20"
    : above
      ? "bg-over-soft text-over border-over/20"
      : "bg-ink-50 text-ink-700 border-ink-100";

  return (
    <div className="mt-1 flex flex-wrap items-center gap-1.5">
      <span className={`chip ${tone}`}>
        {below || above ? `${formatPercent(delta, lang)} ` : ""}
        {label}
      </span>
      {price.n_comparables ? (
        <span className="text-[11px] text-ink-500">
          {s.basedOn} {localizeDigits(String(price.n_comparables), lang)} {s.listings}
        </span>
      ) : null}
    </div>
  );
}

/** Fair price with its confidence, used in the detail panel. */
export function FairPriceRow({ price, lang }: { price: PriceBlock; lang: Lang }) {
  const s = t(lang);
  if (!price.fair_price) return null;

  const confidencePct = price.confidence ? Math.round(price.confidence * 100) : null;

  return (
    <div className="rounded-xl bg-ink-50 border border-ink-100 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm text-ink-500">{s.fairPrice}</span>
        <span className="font-bold text-ink-900">{formatPrice(price.fair_price, lang)}</span>
      </div>
      {confidencePct !== null && (
        <div className="mt-2">
          <div className="flex items-center justify-between text-[11px] text-ink-500 mb-1">
            <span>{s.confidence}</span>
            <span>{localizeDigits(String(confidencePct), lang)}٪</span>
          </div>
          <div className="h-1 w-full rounded-full bg-ink-100 overflow-hidden">
            <div
              className="h-full rounded-full bg-ink-700 animate-grow"
              style={{ width: `${confidencePct}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

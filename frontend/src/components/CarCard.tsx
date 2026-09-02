import type { CarResult } from "../api";
import { formatMileage, localizeDigits } from "../format";
import { t, type Lang } from "../i18n";
import { sourceLabel } from "../sources";
import { CarArt } from "./CarArt";
import { HealthMeter } from "./Health";
import { PriceDisplay } from "./Price";

/** Colour the reason chips by what they are telling the buyer. */
const REASON_TONE: Record<string, string> = {
  deal: "bg-deal-soft text-deal border-deal/20",
  warning: "bg-over-soft text-over border-over/20",
  estimate: "bg-brand-soft text-brand-dark border-brand/20",
  health_risk: "bg-over-soft text-over border-over/20",
  health_positive: "bg-deal-soft text-deal border-deal/20",
  fit: "bg-ink-50 text-ink-700 border-ink-100",
  neutral: "bg-ink-50 text-ink-700 border-ink-100",
};

export function CarCard({
  car,
  lang,
  onOpen,
}: {
  car: CarResult;
  lang: Lang;
  onOpen: (code: string) => void;
}) {
  const s = t(lang);

  return (
    <article
      className="card overflow-hidden flex flex-col hover:shadow-lg transition-shadow cursor-pointer"
      onClick={() => onOpen(car.code)}
    >
      <div className="relative aspect-[4/3] bg-ink-100">
        {car.image ? (
          <img
            src={car.image}
            alt={car.title}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <CarArt car={car} lang={lang} />
        )}

        {car.price.is_estimated && (
          <span className="absolute top-2 start-2 chip bg-surface/95 text-brand-dark border-brand/20 shadow-sm">
            {s.estimatedPrice}
          </span>
        )}
        {car.authenticated && (
          <span className="absolute top-2 end-2 chip bg-surface/95 text-deal border-deal/20 shadow-sm">
            ✓ {lang === "fa" ? "کارشناسی‌شده" : "Inspected"}
          </span>
        )}
      </div>

      <div className="p-4 flex-1 flex flex-col gap-3">
        <div>
          <h3 className="font-semibold text-ink-900 leading-snug line-clamp-1">{car.title}</h3>
          <p className="text-xs text-ink-500 mt-0.5 line-clamp-1">
            {car.year_display ? localizeDigits(String(car.year_display), lang) : "—"}
            {car.trim ? ` · ${car.trim}` : ""}
            {car.mileage_km !== null ? ` · ${formatMileage(car.mileage_km, lang)}` : ""}
          </p>
        </div>

        <PriceDisplay price={car.price} lang={lang} />

        <HealthMeter health={car.health} lang={lang} />

        {car.reasons.length > 0 && (
          <div>
            <p className="text-[11px] font-medium text-ink-500 mb-1.5">{s.whyThisCar}</p>
            <div className="flex flex-wrap gap-1.5">
              {car.reasons.slice(0, 3).map((reason, i) => (
                <span
                  key={i}
                  className={`chip ${REASON_TONE[reason.kind] ?? REASON_TONE.neutral}`}
                >
                  {lang === "fa" ? reason.fa : reason.en}
                </span>
              ))}
            </div>
          </div>
        )}

        <div className="mt-auto pt-2 flex items-center justify-between text-[11px] text-ink-500 border-t border-ink-100">
          <span className="flex items-center gap-1.5 line-clamp-1">
            <SourceBadge source={car.source} duplicates={car.duplicate_of} lang={lang} />
            {car.seller}
            {car.city ? ` · ${car.city}` : ""}
          </span>
          <span className="text-ink-700 font-medium">{s.detail} ←</span>
        </div>
      </div>
    </article>
  );
}

/** Which site the listing came from, and whether it appears on more than one.
 *  Cross-listing is worth surfacing: the same car advertised in two places is a
 *  signal in itself, and it explains why a result isn't duplicated below. */
function SourceBadge({
  source,
  duplicates,
  lang,
}: {
  source: string;
  duplicates: string[] | null;
  lang: Lang;
}) {
  const s = t(lang);
  const crossListed = (duplicates?.length ?? 0) > 0;
  const label = sourceLabel(source, lang);

  return (
    <span className="inline-flex items-center gap-1">
      <span className="rounded px-1.5 py-0.5 bg-ink-50 border border-ink-100 text-ink-700 font-medium">
        {label}
      </span>
      {crossListed && (
        <span className="rounded px-1.5 py-0.5 bg-brand-soft border border-brand/20 text-brand-dark font-medium">
          {s.crossListed}
        </span>
      )}
    </span>
  );
}

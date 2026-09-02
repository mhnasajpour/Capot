import { useEffect, useState } from "react";
import { api, type CarDetail as CarDetailType } from "../api";
import { formatMileage, formatPrice, formatRelativeDate, localizeDigits } from "../format";
import { t, type Lang } from "../i18n";
import { CarArt } from "./CarArt";
import { HealthFactors } from "./Health";
import { DeltaBadge, FairPriceRow } from "./Price";
import { listingUrl, sourceLabel } from "../sources";

/**
 * Detail drawer. Its job is to let a buyer *audit* the two claims the card
 * makes: the fair price (shown against the actual comparable listings behind
 * it) and the health score (shown as its full factor breakdown).
 */
export function CarDetailPanel({
  code,
  lang,
  onClose,
}: {
  code: string;
  lang: Lang;
  onClose: () => void;
}) {
  const s = t(lang);
  const [car, setCar] = useState<CarDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setCar(null);
    setError(null);
    api
      .car(code)
      .then((data) => active && setCar(data))
      .catch((err) => active && setError(String(err)));
    return () => {
      active = false;
    };
  }, [code]);

  // Escape closes the drawer — expected behaviour for anything modal.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-scrim/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative ms-auto h-full w-full max-w-xl overflow-y-auto bg-ink-50 shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-100 bg-surface/95 px-5 py-3 backdrop-blur">
          <h2 className="font-semibold text-ink-900 line-clamp-1">
            {car?.title ?? s.loading}
          </h2>
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm text-ink-700 hover:bg-ink-50"
          >
            {s.close}
          </button>
        </div>

        {error && <p className="p-5 text-sm text-over">{error}</p>}
        {!car && !error && <p className="p-5 text-sm text-ink-500">{s.loading}</p>}

        {car && (
          <div className="space-y-4 p-5">
            {car.image ? (
              <img
                src={car.image}
                alt={car.title}
                className="aspect-[4/3] w-full rounded-2xl object-cover"
              />
            ) : (
              // The drawing fills its box, so the 4:3 has to come from the parent
              // here — `h-full` on the art would otherwise collapse in flow.
              <div className="aspect-[4/3] w-full overflow-hidden rounded-2xl">
                <CarArt car={car} lang={lang} />
              </div>
            )}

            {/* Price: the asking number, our fair number, and the gap. */}
            <section className="card p-4 space-y-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs text-ink-500">
                    {car.price_block.is_estimated ? s.estimatedPrice : s.askingPrice}
                  </p>
                  <p className="text-2xl font-bold text-ink-900">
                    {car.price_block.is_estimated ? "≈ " : ""}
                    {formatPrice(car.price_block.effective, lang)}
                  </p>
                </div>
                <DeltaBadge price={car.price_block} lang={lang} />
              </div>
              <FairPriceRow price={car.price_block} lang={lang} />
            </section>

            {/* Health: the full breakdown, not just the number. */}
            <section className="card p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="font-semibold text-ink-900">{s.health}</h3>
                <span className="text-lg font-bold text-ink-900">
                  {localizeDigits(String(car.health.score), lang)}
                  <span className="text-sm font-normal text-ink-500">
                    {" "}
                    · {lang === "fa" ? car.health.band_fa : car.health.band_en}
                  </span>
                </span>
              </div>
              <HealthFactors health={car.health} lang={lang} />
            </section>

            <SpecGrid car={car} lang={lang} />

            {car.comparables.length > 0 && (
              <section className="card p-4">
                <h3 className="mb-3 font-semibold text-ink-900">{s.comparables}</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-ink-500">
                        <th className="pb-2 text-start font-medium">{s.year}</th>
                        <th className="pb-2 text-start font-medium">{s.mileage}</th>
                        <th className="pb-2 text-start font-medium">{s.body}</th>
                        <th className="pb-2 text-end font-medium">{s.askingPrice}</th>
                        <th className="pb-2 text-end font-medium">{s.sourceCol}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {car.comparables.map((peer) => (
                        <tr key={peer.code} className="border-t border-ink-100">
                          <td className="py-2">
                            {peer.year_display
                              ? localizeDigits(String(peer.year_display), lang)
                              : "—"}
                          </td>
                          <td className="py-2">{formatMileage(peer.mileage_km, lang)}</td>
                          <td className="py-2 text-xs text-ink-500">{peer.body_status ?? "—"}</td>
                          <td className="py-2 text-end font-medium tabular-nums">
                            {formatPrice(peer.price_toman, lang)}
                          </td>
                          <td className="py-2 text-end">
                            {listingUrl(peer.source, peer.url) ? (
                              <a
                                href={listingUrl(peer.source, peer.url)}
                                target="_blank"
                                rel="noreferrer"
                                className="whitespace-nowrap text-xs font-medium text-ink-700 underline underline-offset-2 hover:text-ink-900"
                              >
                                {sourceLabel(peer.source, lang)} ↗
                              </a>
                            ) : (
                              <span className="text-xs text-ink-500">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {car.description && (
              <section className="card p-4">
                <p className="whitespace-pre-line text-sm leading-relaxed text-ink-700">
                  {car.description}
                </p>
              </section>
            )}

            <a
              href={listingUrl(car.source, car.url)}
              target="_blank"
              rel="noreferrer"
              className="block rounded-xl bg-ink-900 py-3 text-center text-sm font-semibold text-ink-50 hover:bg-ink-800"
            >
              {s.viewOn} {sourceLabel(car.source, lang)} ↗
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

/** One row of the spec grid. `wide` spans both columns for long values. */
type Spec = { label: string; value: string; wide?: boolean };

/**
 * Everything the corpus knows about this car, minus what it doesn't.
 *
 * Coverage is wildly uneven across the four sources — Bama carries engine and
 * acceleration figures, Divar carries chassis seals, only dealer ads carry an
 * insurance balance, and `power_hp` is present on barely one listing in a
 * hundred. A fixed grid therefore printed a column of em-dashes on most cars.
 * Rows are built conditionally instead: a field the listing lacks is absent,
 * not empty, so the grid is short on a thin ad and rich on a full one.
 */
function SpecGrid({ car, lang }: { car: CarDetailType; lang: Lang }) {
  const s = t(lang);
  const specs: Spec[] = [];

  // Crawled text fields arrive with their own placeholders — Bama writes "-"
  // for an unknown interior colour — which would otherwise render as content.
  const text = (value: string | null | undefined): string | null => {
    const trimmed = value?.trim();
    if (!trimmed || ["-", "—", "نامشخص", "ندارد"].includes(trimmed)) return null;
    return trimmed;
  };
  const add = (label: string, value: string | null, wide = false) => {
    if (value) specs.push({ label, value, wide });
  };
  const num = (value: number | null | undefined, unit?: string): string | null => {
    if (value === null || value === undefined) return null;
    const digits = localizeDigits(String(value), lang);
    return unit ? `${digits} ${unit}` : digits;
  };

  add(s.year, num(car.year_display));
  add(s.mileage, car.mileage_km === null ? null : formatMileage(car.mileage_km, lang));
  add(s.body, text(car.body_status));
  add(s.transmission, text(car.transmission));
  add(s.fuel, text(car.fuel));
  add(s.trim, text(car.trim));
  add(s.bodyType, text(car.body_type_fa ?? car.body_type));
  add(s.engine, num(car.engine_volume_l, s.liter));
  add(s.power, num(car.power_hp, s.hp));
  add(s.consumption, num(car.consumption_l100, "L/100"));
  add(s.acceleration, num(car.acceleration_s, s.second));
  add(s.color, text(car.body_color));
  add(s.insideColor, text(car.inside_color));
  add(s.insurance, num(car.insurance_months, s.monthsUnit));
  add(s.inspection, car.authenticated ? s.inspected : null);
  // `location` is "city / neighbourhood" where a neighbourhood is known, so it
  // already contains the city — printing both would repeat it.
  add(s.city, text(car.location) ?? text(car.city));
  add(s.seller, text(car.dealer_name) ?? text(car.seller));
  add(
    s.dealerRating,
    car.dealer_score === null || car.dealer_score === undefined
      ? null
      : [
          `${localizeDigits(car.dealer_score.toFixed(1), lang)} ${s.of} ${localizeDigits("5", lang)}`,
          car.dealer_ad_count ? num(car.dealer_ad_count, s.adsUnit) : null,
        ]
          .filter(Boolean)
          .join(" · "),
  );
  add(s.updatedAt, formatRelativeDate(car.modified_date, lang));
  // Chassis reads as a sentence ("جلو سالم و پلمپ، عقب ضربه خورده"), so it gets
  // the full width rather than being clipped to a half column.
  add(s.chassis, text(car.chassis_status), true);

  if (specs.length === 0) return null;

  return (
    <section className="card p-4">
      <h3 className="mb-3 font-semibold text-ink-900">{s.specs}</h3>
      <div className="grid grid-cols-2 gap-x-4 gap-y-3">
        {specs.map(({ label, value, wide }) => (
          <div key={label} className={wide ? "col-span-2" : undefined}>
            <p className="text-[11px] text-ink-500">{label}</p>
            <p className={`text-sm font-medium text-ink-900 ${wide ? "" : "line-clamp-1"}`}>
              {value}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

import type { HealthBlock } from "../api";
import { healthColor, localizeDigits } from "../format";
import { t, type Lang } from "../i18n";

/**
 * The health score with its reasoning. The number alone would be an unfalsifiable
 * claim, so the factors that produced it are always one click away — and the two
 * biggest movers are shown inline without any click at all.
 */
export function HealthMeter({
  health,
  lang,
  showFactors = 0,
}: {
  health: HealthBlock;
  lang: Lang;
  showFactors?: number;
}) {
  const s = t(lang);
  const color = healthColor(health.score);
  const band = lang === "fa" ? health.band_fa : health.band_en;

  return (
    <div>
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-ink-500">{s.health}</span>
        <span className="font-semibold" style={{ color }}>
          {localizeDigits(String(health.score), lang)} · {band}
        </span>
      </div>

      <div className="h-1.5 w-full rounded-full bg-ink-100 overflow-hidden">
        <div
          className="h-full rounded-full animate-grow"
          style={{ width: `${health.score}%`, backgroundColor: color }}
        />
      </div>

      {showFactors > 0 && (
        <ul className="mt-2 space-y-1">
          {health.factors.slice(0, showFactors).map((factor) => (
            <li key={factor.key} className="flex items-start gap-1.5 text-xs text-ink-700">
              <span className={factor.impact >= 0 ? "text-deal" : "text-over"}>
                {factor.impact >= 0 ? "+" : "−"}
              </span>
              <span>{lang === "fa" ? factor.label_fa : factor.label_en}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Full factor list for the detail panel, with the point impact made explicit. */
export function HealthFactors({ health, lang }: { health: HealthBlock; lang: Lang }) {
  return (
    <ul className="space-y-2">
      {health.factors.map((factor) => (
        <li key={factor.key} className="flex items-center justify-between gap-3 text-sm">
          <span className="text-ink-700">{lang === "fa" ? factor.label_fa : factor.label_en}</span>
          <span
            className={`font-semibold tabular-nums ${factor.impact >= 0 ? "text-deal" : "text-over"}`}
          >
            {factor.impact >= 0 ? "+" : "−"}
            {localizeDigits(String(Math.abs(factor.impact)), lang)}
          </span>
        </li>
      ))}
    </ul>
  );
}

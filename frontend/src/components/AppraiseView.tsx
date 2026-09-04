import { useMemo, type ReactNode } from "react";
import type { Appraisal, FeatureCatalogue, FeatureValue } from "../api";
import {
  EMPTY_INPUT,
  FIELD_FEATURE,
  hasInput,
  type AppraisalInput,
  type InputKey,
} from "../appraisal";
import { formatPrice, localizeDigits } from "../format";
import { t, type Lang } from "../i18n";
import { CarCard } from "./CarCard";
import { HealthFactors } from "./Health";

/**
 * "What is my car worth?" — the one question this product could answer and had
 * no door for.
 *
 * Two doors again, and for the same reason `features.py` gave search a second
 * one: prose is a good way in when you know what to say about your car, and a
 * bad one when you don't. So there is a textarea and a form, and they are not
 * alternatives — what the prose yields lands *in* the form fields, visibly, and
 * anything the user then changes wins. That is the same precedence
 * `Filters.apply_to` applies to search, made literal: they can see a field, they
 * cannot see a parser.
 *
 * The result leads with the range rather than the point estimate. A single
 * number implies a precision the model does not have, and this page exists to
 * be honest about a number somebody is about to sell a real car on.
 */
export function AppraiseView({
  input,
  result,
  loading,
  error,
  catalogue,
  lang,
  onChange,
  onSubmit,
  onOpenCar,
}: {
  input: AppraisalInput;
  result: Appraisal | null;
  loading: boolean;
  error: string | null;
  catalogue: FeatureCatalogue | null;
  lang: Lang;
  onChange: (next: AppraisalInput) => void;
  onSubmit: () => void;
  onOpenCar: (code: string) => void;
}) {
  const s = t(lang);
  const set = (key: InputKey | "q", value: string) => onChange({ ...input, [key]: value });

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-6 text-center">
        <h1 className="text-balance text-2xl font-extrabold tracking-tight text-ink-900 sm:text-3xl">
          {s.appraiseHeadline}
        </h1>
        <p className="mx-auto mt-3 max-w-2xl text-sm leading-relaxed text-ink-500">
          {s.appraiseBody}
        </p>
      </header>

      <form
        className="card space-y-5 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <textarea
          value={input.q}
          onChange={(e) => set("q", e.target.value)}
          rows={3}
          placeholder={s.appraisePlaceholder}
          className="w-full resize-y rounded-xl border border-ink-100 bg-surface p-3 text-sm
                     leading-relaxed text-ink-900 placeholder:text-ink-300
                     focus:border-brand/40 focus:outline-none focus:ring-4 focus:ring-brand/10"
        />

        <div>
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold text-ink-900">{s.appraiseDetails}</h2>
            {/* Only shown once the parser has actually filled something in —
                before that there is nothing to have got wrong. */}
            {result && (
              <p className="text-[11px] text-ink-500">{s.appraiseUnderstood}</p>
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <EnumField
              field="brand" label={s.fieldBrand} required
              input={input} catalogue={catalogue} lang={lang} onChange={set}
            />
            <EnumField
              field="model" label={s.fieldModel} required
              input={input} catalogue={catalogue} lang={lang} onChange={set}
              // Models are namespaced by brand — «۲۰۶» is a Peugeot, «۳۱۵» an
              // MVM — so the list is scoped the way the filter panel scopes it.
              scopeTo={input.brand}
            />
            <NumberField
              field="year" label={s.fieldYear} required
              placeholder={lang === "fa" ? "1395" : "2016"}
              input={input} lang={lang} onChange={set}
            />
            <NumberField
              field="mileage" label={s.fieldMileage}
              input={input} lang={lang} onChange={set}
            />
            <EnumField
              field="body_status" label={s.fieldBodyStatus}
              input={input} catalogue={catalogue} lang={lang} onChange={set}
              // Paint condition is a free-text phrase on listings rather than a
              // catalogue enum, so the options are the grades `normalize.py`
              // actually recognises, worst last.
              options={PAINT_OPTIONS}
            />
            <EnumField
              field="transmission" label={s.transmission}
              input={input} catalogue={catalogue} lang={lang} onChange={set}
            />
            <EnumField
              field="fuel" label={s.fuel}
              input={input} catalogue={catalogue} lang={lang} onChange={set}
            />
            <EnumField
              field="color" label={s.fieldColor}
              input={input} catalogue={catalogue} lang={lang} onChange={set}
            />
            <EnumField
              field="city" label={s.fieldCity}
              input={input} catalogue={catalogue} lang={lang} onChange={set}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => onChange({ ...EMPTY_INPUT })}
            className="text-xs text-ink-500 underline-offset-2 hover:text-ink-900 hover:underline"
          >
            {s.clearAll}
          </button>
          <button
            type="submit"
            disabled={loading || !hasInput(input)}
            className="rounded-xl bg-brand px-6 py-2.5 text-sm font-semibold text-white
                       transition-colors hover:bg-brand-dark disabled:cursor-not-allowed
                       disabled:bg-ink-100 disabled:text-ink-300"
          >
            {loading ? s.loading : result ? s.appraiseAgain : s.appraiseSubmit}
          </button>
        </div>
      </form>

      {error && (
        <p className="mt-4 rounded-xl border border-over/20 bg-over-soft p-4 text-sm text-over">
          {error}
        </p>
      )}

      {!loading && !result && !error && (
        <p className="card mt-4 p-10 text-center text-sm text-ink-500">{s.appraiseEmpty}</p>
      )}

      {result && !loading && (
        <div className="mt-6 space-y-5">
          <Verdict result={result} lang={lang} />
          {result.status === "ok" && (
            <>
              <HealthSection result={result} lang={lang} />
              <MatchesSection result={result} lang={lang} onOpenCar={onOpenCar} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The number, as a range first.
 *
 * The band comes from the model's own held-out error, widened by how thin the
 * comparable evidence is, so it is the honest width rather than a decorative
 * one. The point estimate sits inside it in smaller type — it is what the model
 * says, but the range is what the model *knows*.
 */
function Verdict({ result, lang }: { result: Appraisal; lang: Lang }) {
  const s = t(lang);

  if (result.status === "unknown_car") {
    return <Refusal headline={s.appraiseUnknownCar} hint={s.appraiseUnknownCarHint} />;
  }
  if (result.status === "need_year" || !result.price) {
    return <Refusal headline={s.appraiseNeedYear} hint={s.appraiseNeedYearHint} />;
  }

  const { price } = result;
  const confidencePct = Math.round(price.confidence * 100);
  const warningText: Record<string, string> = {
    brand_new: s.appraiseWarnBrandNew,
    no_mileage: s.appraiseWarnNoMileage,
    no_comparables: s.appraiseWarnNoComparables,
  };

  return (
    <section className="card p-6">
      <p className="text-xs font-medium text-ink-500">{s.appraiseEstimate}</p>

      <p className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-3xl font-extrabold tracking-tight text-ink-900 sm:text-4xl">
          {formatPrice(price.low, lang)} – {formatPrice(price.high, lang)}
        </span>
        <span className="text-sm text-ink-500">{lang === "fa" ? "تومان" : "toman"}</span>
      </p>

      <p className="mt-2 text-sm text-ink-500">
        {s.fairPrice}: <span className="font-semibold text-ink-700">≈ {formatPrice(price.fair_price, lang)}</span>
      </p>

      <div className="mt-5 border-t border-ink-100 pt-4">
        <div className="mb-1.5 flex items-center justify-between text-[11px] text-ink-500">
          <span>
            {s.confidence}
            {price.n_comparables > 0 && (
              <>
                {" · "}
                {s.appraiseBasedOnFa}{" "}
                {localizeDigits(String(price.n_comparables), lang)} {s.appraiseComparables}
              </>
            )}
          </span>
          <span>{localizeDigits(String(confidencePct), lang)}٪</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-100">
          <div
            className="h-full rounded-full bg-brand animate-grow"
            style={{ width: `${Math.max(confidencePct, 2)}%` }}
          />
        </div>
      </div>

      {result.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {result.warnings.map((warning) => (
            <li
              key={warning}
              className="rounded-xl border border-over/20 bg-over-soft px-3 py-2 text-xs text-over"
            >
              {warningText[warning] ?? warning}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** No price, and why. The two refusals are different and are told apart. */
function Refusal({ headline, hint }: { headline: string; hint: string }) {
  return (
    <section className="card p-8 text-center">
      <p className="text-sm font-semibold text-ink-900">{headline}</p>
      <p className="mx-auto mt-2 max-w-md text-xs leading-relaxed text-ink-500">{hint}</p>
    </section>
  );
}

function HealthSection({ result, lang }: { result: Appraisal; lang: Lang }) {
  const s = t(lang);
  if (!result.health) return null;

  return (
    <section className="card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold text-ink-900">{s.health}</h2>
        <span className="text-lg font-bold text-ink-900">
          {localizeDigits(String(result.health.score), lang)}
          <span className="text-sm font-normal text-ink-500">
            {" · "}
            {lang === "fa" ? result.health.band_fa : result.health.band_en}
          </span>
        </span>
      </div>
      <HealthFactors health={result.health} lang={lang} />
    </section>
  );
}

/** The ads themselves — the same cards the result grid draws. */
function MatchesSection({
  result,
  lang,
  onOpenCar,
}: {
  result: Appraisal;
  lang: Lang;
  onOpenCar: (code: string) => void;
}) {
  const s = t(lang);
  const level = s.appraiseMatchLevel[result.match_level as keyof typeof s.appraiseMatchLevel];

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="font-semibold text-ink-900">{s.appraiseSimilar}</h2>
        {level && <span className="chip">{level}</span>}
      </div>
      {result.matches.length === 0 ? (
        <p className="card p-8 text-center text-sm text-ink-500">{s.appraiseSimilarNone}</p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {result.matches.map((car) => (
            <CarCard key={car.code} car={car} lang={lang} onOpen={onOpenCar} />
          ))}
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------- fields

/** Paint condition, as the phrases `normalize.BODY_STATUS_GRADE` grades. */
const PAINT_OPTIONS: FeatureValue[] = [
  { value: "بدون رنگ", label_fa: "بدون رنگ", label_en: "No repaint", count: 0 },
  { value: "صافکاری بدون رنگ", label_fa: "صافکاری بدون رنگ", label_en: "Dent work, no paint", count: 0 },
  { value: "خط و خش جزئی", label_fa: "خط و خش جزئی", label_en: "Light scuffs", count: 0 },
  { value: "یک لکه رنگ", label_fa: "یک لکه رنگ", label_en: "One painted panel", count: 0 },
  { value: "دو لکه رنگ", label_fa: "دو لکه رنگ", label_en: "Two painted panels", count: 0 },
  { value: "چند لکه رنگ", label_fa: "چند لکه رنگ", label_en: "A few painted panels", count: 0 },
  { value: "دور رنگ", label_fa: "دور رنگ", label_en: "Fully resprayed", count: 0 },
  { value: "تعویض شده", label_fa: "تعویض شده", label_en: "Panel replaced", count: 0 },
];

function FieldShell({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center gap-1 text-[11px] font-medium text-ink-500">
        {label}
        {required && <span className="text-brand">*</span>}
      </span>
      {children}
    </label>
  );
}

const CONTROL =
  "w-full rounded-xl border border-ink-100 bg-surface px-3 py-2 text-sm text-ink-900 " +
  "focus:border-brand/40 focus:outline-none focus:ring-4 focus:ring-brand/10";

/**
 * A select whose options come from the corpus, via the same `/api/features`
 * catalogue the filter panel is drawn from. A brand that appears in tomorrow's
 * crawl is appraisable without anyone editing this file — the property
 * `features.py` exists to preserve.
 */
function EnumField({
  field,
  label,
  required,
  input,
  catalogue,
  lang,
  onChange,
  scopeTo,
  options,
}: {
  field: InputKey;
  label: string;
  required?: boolean;
  input: AppraisalInput;
  catalogue: FeatureCatalogue | null;
  lang: Lang;
  onChange: (key: InputKey, value: string) => void;
  scopeTo?: string;
  options?: FeatureValue[];
}) {
  const s = t(lang);

  const values = useMemo(() => {
    if (options) return options;
    const key = FIELD_FEATURE[field];
    const feature = catalogue?.features.find((f) => f.key === key);
    let list = feature?.values ?? [];
    // Models arrive as 'brand/model' keys scoped by brand, exactly as the filter
    // panel receives them; the form stores the bare slug the backend prices on.
    if (field === "model") {
      list = scopeTo ? list.filter((value) => value.parent === scopeTo) : [];
      return list.map((value) => ({ ...value, value: value.value.split("/")[1] ?? value.value }));
    }
    return list;
  }, [catalogue, field, options, scopeTo]);

  const disabled = field === "model" && !scopeTo;

  return (
    <FieldShell label={label} required={required}>
      <select
        value={input[field]}
        disabled={disabled}
        onChange={(e) => onChange(field, e.target.value)}
        className={`${CONTROL} disabled:cursor-not-allowed disabled:bg-ink-50 disabled:text-ink-300`}
      >
        <option value="">{disabled ? s.selectBrandFirst : s.anyValue}</option>
        {values.map((value) => (
          <option key={value.value} value={value.value}>
            {lang === "fa" ? value.label_fa : value.label_en}
          </option>
        ))}
      </select>
    </FieldShell>
  );
}

/**
 * A numeric field that stays a string until the user is done with it.
 *
 * Persian digits are accepted and folded to ASCII on the way out, because
 * someone typing «۱۲۰۰۰۰» into a Persian interface has not made a mistake —
 * `normalize.fa_to_en_digits` does the same for every number the crawl reads.
 */
function NumberField({
  field,
  label,
  required,
  placeholder,
  input,
  lang,
  onChange,
}: {
  field: InputKey;
  label: string;
  required?: boolean;
  placeholder?: string;
  input: AppraisalInput;
  lang: Lang;
  onChange: (key: InputKey, value: string) => void;
}) {
  return (
    <FieldShell label={label} required={required}>
      <input
        type="text"
        inputMode="numeric"
        dir="ltr"
        value={localizeDigits(input[field], lang)}
        placeholder={placeholder}
        onChange={(e) => onChange(field, toAsciiDigits(e.target.value))}
        className={`${CONTROL} placeholder:text-ink-300`}
      />
    </FieldShell>
  );
}

/** «۱۲۰۰۰۰» -> "120000". The mirror of `format.localizeDigits`. */
function toAsciiDigits(text: string): string {
  return text
    .replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)))
    .replace(/[^\d.]/g, "");
}

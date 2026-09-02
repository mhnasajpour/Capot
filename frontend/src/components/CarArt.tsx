import { useId } from "react";
import {
  GROUND_Y,
  bodyPath,
  lampsOf,
  luminance,
  paintOf,
  seedOf,
  shade,
  silhouetteOf,
} from "../carArt";
import { t, type Lang } from "../i18n";

/** The fields the drawing needs. Both `CarResult` and `CarDetail` satisfy it. */
export interface ArtCar {
  code: string;
  body_type: string | null;
  body_type_fa: string | null;
  body_color: string | null;
}

/**
 * The stand-in shown where a listing has no photo: the car the ad describes,
 * drawn from its body type and paint colour, standing on a small studio set.
 *
 * Everything below is derived from those two fields plus the listing code —
 * the code only picks between equivalent variants (which rims, where the light
 * falls), so the drawing is stable across renders without two identical cars
 * appearing in the grid.
 */
export function CarArt({
  car,
  lang,
  caption = true,
  className = "",
}: {
  car: ArtCar;
  lang: Lang;
  /** The «no photo» badge. On by default — the drawing must never pass for one. */
  caption?: boolean;
  className?: string;
}) {
  // Gradient and clip references have to be unique per instance, or every card
  // on the page is painted with the first card's colour. `useId` alone is unique
  // within a React root; the listing code keeps it unique across roots too.
  const id = `${useId().replace(/[^a-zA-Z0-9]/g, "")}${car.code.replace(/[^a-zA-Z0-9]/g, "")}`;
  const paint = paintOf(car.body_color);
  const shape = silhouetteOf(car.body_type);
  const lamps = lampsOf(car.body_type);
  const seed = seedOf(car.code);
  const s = t(lang);

  const body = bodyPath(shape);
  const lum = luminance(paint.hex);
  const dark = lum < 0.38;
  // A white car reflects the studio almost as brightly as the wall behind it, so
  // the highlight that makes a black car look like metal has to come off as the
  // paint gets lighter — otherwise the roof simply dissolves into the backdrop.
  const gloss = 0.34 - lum * 0.26;
  // The outline has to contrast with the paint, not with the page: a light rim
  // on a black car, a dark one on a white car. Otherwise one of the two most
  // common colours in the corpus loses its shape in one of the two themes.
  const outline = dark ? shade(paint.hex, 0.52 - lum * 0.5) : shade(paint.hex, -0.34);
  const glassTop = "#4A596B";
  const glassBottom = "#232C38";

  // Studio lighting: the key light drifts across the backdrop from listing to
  // listing so a full grid of these does not read as one repeated tile.
  const keyX = 120 + (seed % 160);
  const rim = seed % 3;

  // Screen readers should get the same two facts the drawing carries, and be
  // told it is a drawing — not left to infer a photo exists.
  const described =
    lang === "fa"
      ? [paint.fa, car.body_type_fa].filter(Boolean).join(" ") || "خودرو"
      : `${paint.fa ? `${paint.en.toLowerCase()} ` : ""}car`;
  const label = `${s.illustration}: ${described} — ${s.noPhoto}`;

  return (
    <div className={`relative h-full w-full overflow-hidden ${className}`}>
      <svg viewBox="0 0 400 300" className="h-full w-full" role="img" aria-label={label}>
        <defs>
          {/* Backdrop: page colours, so the set follows the theme. */}
          <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "rgb(var(--ink-50))" }} />
            <stop offset="62%" style={{ stopColor: "rgb(var(--ink-100))" }} />
            <stop offset="100%" style={{ stopColor: "rgb(var(--ink-100))" }} />
          </linearGradient>

          {/* Key light, tinted by the car's own paint — a red car warms the wall
              behind it. On a white or silver car the tint is imperceptible,
              which is correct. */}
          <radialGradient id={`${id}-key`}>
            <stop offset="0%" stopColor={paint.hex} stopOpacity="0.17" />
            <stop offset="55%" stopColor={paint.hex} stopOpacity="0.06" />
            <stop offset="100%" stopColor={paint.hex} stopOpacity="0" />
          </radialGradient>

          {/* Paint: sky reflected off the top, ground bounced back up the sills. */}
          <linearGradient id={`${id}-paint`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={shade(paint.hex, gloss)} />
            <stop offset="34%" stopColor={paint.hex} />
            <stop offset="74%" stopColor={shade(paint.hex, -0.16)} />
            <stop offset="100%" stopColor={shade(paint.hex, -0.04)} />
          </linearGradient>

          <linearGradient id={`${id}-glass`} x1="0" y1="0" x2="0.35" y2="1">
            <stop offset="0%" stopColor={glassTop} />
            <stop offset="100%" stopColor={glassBottom} />
          </linearGradient>

          {/* One diagonal sheen bar, clipped to the body and again to the glass:
              the same light crossing both, which is what sells it as a surface. */}
          <linearGradient id={`${id}-sheen`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0" />
            <stop offset="50%" stopColor="#FFFFFF" stopOpacity={gloss} />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </linearGradient>

          <radialGradient id={`${id}-shadow`}>
            <stop offset="0%" stopColor="#000000" stopOpacity="0.32" />
            <stop offset="60%" stopColor="#000000" stopOpacity="0.12" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0" />
          </radialGradient>

          {/* The floor reflection fades out over its own height. */}
          <linearGradient id={`${id}-fade`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#FFFFFF" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#FFFFFF" stopOpacity="0" />
          </linearGradient>
          <mask id={`${id}-mirror`}>
            <rect x="0" y={GROUND_Y} width="400" height={300 - GROUND_Y} fill={`url(#${id}-fade)`} />
          </mask>

          <clipPath id={`${id}-clip`}>
            <path d={body} />
          </clipPath>
          <clipPath id={`${id}-glassclip`}>
            {shape.glass.map((pane, i) => (
              <path key={i} d={pane} />
            ))}
          </clipPath>
        </defs>

        <rect width="400" height="300" fill={`url(#${id}-bg)`} />
        <ellipse cx={keyX} cy="150" rx="215" ry="165" fill={`url(#${id}-key)`} />
        <line
          x1="0"
          y1={GROUND_Y}
          x2="400"
          y2={GROUND_Y}
          style={{ stroke: "rgb(var(--ink-300))" }}
          strokeOpacity="0.35"
        />

        {/* Reflection first, so the car and its shadow sit on top of it. */}
        <g
          mask={`url(#${id}-mirror)`}
          transform={`translate(0, ${GROUND_Y * 2}) scale(1, -1)`}
          opacity="0.28"
        >
          <path d={body} fill={paint.hex} />
          <Wheels shape={shape} rim={rim} flat />
        </g>

        <ellipse cx="200" cy={GROUND_Y + 3} rx="168" ry="16" fill={`url(#${id}-shadow)`} />
        {shape.wheels.map((w, i) => (
          <ellipse key={i} cx={w.cx} cy={GROUND_Y + 1} rx={w.r * 0.9} ry="5" fill={`url(#${id}-shadow)`} />
        ))}

        <Wheels shape={shape} rim={rim} />

        <path
          d={body}
          fill={`url(#${id}-paint)`}
          stroke={outline}
          strokeWidth="2.2"
          strokeLinejoin="round"
        />

        <g clipPath={`url(#${id}-clip)`}>
          <rect
            x="-60"
            y="60"
            width="520"
            height="44"
            fill={`url(#${id}-sheen)`}
            transform="rotate(-9 200 150)"
          />
        </g>

        {/* Lamps, before the glass so a wrapped-round tail lamp keeps its edge. */}
        <g clipPath={`url(#${id}-clip)`}>
          <Lamp x={lamps.front[0]} y={lamps.front[1]} tone="#FFF3D6" />
          <Lamp x={lamps.rear[0]} y={lamps.rear[1]} tone="#D6483C" />
        </g>

        {shape.glass.map((pane, i) => (
          <path
            key={i}
            d={pane}
            fill={`url(#${id}-glass)`}
            stroke="#93A2B4"
            strokeOpacity="0.55"
            strokeWidth="1.3"
            strokeLinejoin="round"
          />
        ))}
        <g clipPath={`url(#${id}-glassclip)`}>
          <rect
            x="-60"
            y="52"
            width="520"
            height="30"
            fill={`url(#${id}-sheen)`}
            transform="rotate(-9 200 150)"
          />
        </g>

        <g clipPath={`url(#${id}-clip)`}>
          {shape.lines.map((line, i) => (
            <path
              key={i}
              d={line}
              fill="none"
              stroke={outline}
              strokeOpacity="0.5"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
          ))}
        </g>
      </svg>

      {caption && (
        <span className="absolute bottom-2 start-2 chip bg-surface/90 text-ink-500 border-ink-100 shadow-sm backdrop-blur-sm">
          {paint.fa && (
            <span
              className="h-2.5 w-2.5 rounded-full border border-ink-300/60"
              style={{ backgroundColor: paint.hex }}
            />
          )}
          {lang === "fa" ? paint.fa : paint.fa ? paint.en : null}
          {paint.fa ? " · " : ""}
          {s.noPhoto}
        </span>
      )}
    </div>
  );
}

/** Tyre, rim and hub. `flat` drops the detail for the floor reflection, where
 *  spokes would only read as noise. */
function Wheels({
  shape,
  rim,
  flat = false,
}: {
  shape: ReturnType<typeof silhouetteOf>;
  rim: number;
  flat?: boolean;
}) {
  return (
    <>
      {shape.wheels.map((w, i) => {
        const cy = GROUND_Y - w.r;
        if (flat) return <circle key={i} cx={w.cx} cy={cy} r={w.r} fill="#1A1E24" />;
        const inner = w.r * 0.6;
        return (
          <g key={i}>
            <circle cx={w.cx} cy={cy} r={w.r} fill="#191D23" />
            <circle cx={w.cx} cy={cy} r={w.r * 0.82} fill="none" stroke="#2C323A" strokeWidth="2" />
            <circle cx={w.cx} cy={cy} r={inner} fill="#B9C0C8" />
            <circle cx={w.cx} cy={cy} r={inner} fill="none" stroke="#8C939C" strokeWidth="1.5" />
            <Rim cx={w.cx} cy={cy} r={inner} variant={rim} />
            <circle cx={w.cx} cy={cy} r={w.r * 0.16} fill="#767E88" />
          </g>
        );
      })}
    </>
  );
}

/** Three rim patterns. Which one a car gets is decided by its listing code, so
 *  the grid varies without any two renders of the same car disagreeing. */
function Rim({ cx, cy, r, variant }: { cx: number; cy: number; r: number; variant: number }) {
  if (variant === 2) {
    return <circle cx={cx} cy={cy} r={r * 0.62} fill="none" stroke="#8C939C" strokeWidth="3" />;
  }
  const count = variant === 0 ? 5 : 8;
  const width = variant === 0 ? 4 : 2.2;
  return (
    <>
      {Array.from({ length: count }, (_, i) => {
        const angle = (i / count) * Math.PI * 2;
        return (
          <line
            key={i}
            x1={cx + Math.cos(angle) * r * 0.22}
            y1={cy + Math.sin(angle) * r * 0.22}
            x2={cx + Math.cos(angle) * r * 0.86}
            y2={cy + Math.sin(angle) * r * 0.86}
            stroke="#8C939C"
            strokeWidth={width}
            strokeLinecap="round"
          />
        );
      })}
    </>
  );
}

function Lamp({ x, y, tone }: { x: number; y: number; tone: string }) {
  return (
    <g>
      <ellipse cx={x} cy={y} rx="12" ry="6.5" fill={tone} opacity="0.92" />
      <ellipse cx={x} cy={y - 1.5} rx="8" ry="3" fill="#FFFFFF" opacity="0.5" />
    </g>
  );
}

/**
 * Illustrated stand-ins for listings that arrive without a photo.
 *
 * About one ad in nine on Bama has no image at all, and a grey «—» box tells the
 * buyer nothing while making a perfectly good listing look broken. The ad does
 * however state the body type and the paint colour, so we can draw the car it
 * describes: the right silhouette, in the right colour, on a small studio set.
 *
 * The point is not to pretend we have a photo — the card says «no photo» either
 * way — it is that the placeholder carries two real facts off the ad instead of
 * none, and that a grid of them stays legible rather than turning into a wall of
 * empty rectangles.
 *
 * Everything here is pure: same listing in, same drawing out, no assets to load.
 */

/* ------------------------------------------------------------------ paint -- */

/** A Persian paint name, its screen colour, and its English reading. */
interface Paint {
  hex: string;
  en: string;
}

/**
 * Persian colour names as the sources actually write them, mapped to paint that
 * reads as car paint rather than as a swatch: whites are warmed off pure white
 * and blacks lifted off pure black, because neither extreme looks like metal.
 */
const PAINTS: Record<string, Paint> = {
  "سفید": { hex: "#EDEFF2", en: "White" },
  "سفید صدفی": { hex: "#EDE9DC", en: "Pearl white" },
  "مشکی": { hex: "#252A31", en: "Black" },
  "کربن بلک": { hex: "#1D2126", en: "Carbon black" },
  "امبر بلک": { hex: "#282320", en: "Amber black" },
  "خاکستری": { hex: "#878E97", en: "Grey" },
  "طوسی": { hex: "#979EA6", en: "Grey" },
  "نقره ای": { hex: "#C0C6CC", en: "Silver" },
  "تیتانیوم": { hex: "#A5ABB2", en: "Titanium" },
  "نوک مدادی": { hex: "#484E56", en: "Graphite" },
  "ذغالی": { hex: "#363A40", en: "Charcoal" },
  "سربی": { hex: "#696F77", en: "Lead grey" },
  "دلفینی": { hex: "#6C7987", en: "Dolphin grey" },
  "نقرآبی": { hex: "#7A91AC", en: "Silver blue" },
  "آبی": { hex: "#2E6AB4", en: "Blue" },
  "اطلسی": { hex: "#3A5BA0", en: "Atlas blue" },
  "سرمه ای": { hex: "#1F2C4E", en: "Navy" },
  "قرمز": { hex: "#C0392B", en: "Red" },
  "گیلاسی": { hex: "#A22433", en: "Cherry" },
  "آلبالویی": { hex: "#7C2030", en: "Sour cherry" },
  "زرشکی": { hex: "#78202F", en: "Burgundy" },
  "عنابی": { hex: "#6D2331", en: "Maroon" },
  "مارون": { hex: "#6C2B2F", en: "Maroon" },
  "بادمجانی": { hex: "#4B2C4E", en: "Aubergine" },
  "بنفش": { hex: "#6A3F9E", en: "Purple" },
  "یاسی": { hex: "#9A88C2", en: "Lilac" },
  "سبز": { hex: "#2F7C50", en: "Green" },
  "یشمی": { hex: "#316B5D", en: "Jade" },
  "زیتونی": { hex: "#6B7044", en: "Olive" },
  "زرد": { hex: "#E0B23E", en: "Yellow" },
  "طلایی": { hex: "#C7A24C", en: "Gold" },
  "طلائی": { hex: "#C7A24C", en: "Gold" },
  "برنز": { hex: "#A67B4D", en: "Bronze" },
  "مسی": { hex: "#AE6B3E", en: "Copper" },
  "نارنجی": { hex: "#D3722C", en: "Orange" },
  "اخرائی": { hex: "#9A5C3C", en: "Ochre" },
  "قهوه ای": { hex: "#5C4235", en: "Brown" },
  "موکا": { hex: "#6D584B", en: "Mocha" },
  "عدسی": { hex: "#8A705C", en: "Lentil brown" },
  "تارتوفو": { hex: "#6A5C50", en: "Tartufo" },
  "شتری": { hex: "#B69A73", en: "Camel" },
  "خاکی": { hex: "#A59772", en: "Khaki" },
  "بژ": { hex: "#D3C5A9", en: "Beige" },
  "کرم": { hex: "#E1D7BF", en: "Cream" },
  "پوست پیازی": { hex: "#E5CFC5", en: "Onion skin" },
};

/** Silver stands in for «other» and for anything the sources spell in a way we
 *  have not seen — a neutral is the honest guess, not a made-up colour. */
const UNKNOWN_PAINT: Paint = { hex: "#B4BAC2", en: "Unspecified" };

/** Persian text arrives with Arabic letterforms and zero-width joiners mixed in
 *  («نقره‌ای», «نقره ای», «نقرهاي» are one colour), so match on a flattened key. */
function normalize(name: string): string {
  return name
    .replace(/‌/g, " ")
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/\s+/g, " ")
    .trim();
}

export function paintOf(bodyColor: string | null | undefined): Paint & { fa: string | null } {
  const key = bodyColor ? normalize(bodyColor) : "";
  const paint = PAINTS[key];
  return paint ? { ...paint, fa: key } : { ...UNKNOWN_PAINT, fa: null };
}

/** Mix a colour toward black (`amount` < 0) or white (> 0). Used for the panel
 *  shading and the outline, so a single paint value drives the whole car. */
export function shade(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const target = amount < 0 ? 0 : 255;
  const k = Math.abs(amount);
  const mix = (c: number) => Math.round(c + (target - c) * k);
  const r = mix((n >> 16) & 255);
  const g = mix((n >> 8) & 255);
  const b = mix(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, "0")}`;
}

/** Perceived lightness, 0–1. Decides whether a white car needs a firmer outline
 *  and whether the caption sitting on the paint should be dark or light. */
export function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return (0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255;
}

/* ------------------------------------------------------------- silhouettes -- */

/**
 * One car drawn side-on inside a 400×300 box (the 4:3 the card already reserves
 * for a photo). Every silhouette shares a ground line at y=238 and a nose at the
 * left, so the whole grid lines up no matter which body types come back.
 */
export interface Silhouette {
  /** Wheels front-first; `r` also sets how big the arch cut out of the body is. */
  wheels: { cx: number; r: number }[];
  /** Rocker height — where the body stops and the arches are cut from. */
  sill: number;
  /** Nose to tail over the roof, from the bottom of one bumper to the other. */
  top: string;
  /** Window panes, drawn over the paint. */
  glass: string[];
  /** Shut lines and creases — what stops the body reading as a flat blob. */
  lines: string[];
}

const GROUND = 238;

/** Wheel centres sit on the ground line, so only the radius has to be given. */
const wheel = (cx: number, r: number) => ({ cx, r });

/**
 * The eight body types Bama files listings under. They are hand-drawn rather
 * than generated from parameters because the difference between a hatchback and
 * a crossover *is* the roofline: parameterising it would flatten the one thing
 * the drawing exists to show.
 */
export const SILHOUETTES: Record<string, Silhouette> = {
  // Three-box saloon: long boot, roof peak over the rear seat.
  passenger_car: {
    wheels: [wheel(112, 33), wheel(290, 33)],
    sill: 203,
    top: `M 32 203 L 32 178
          C 30 156 40 142 60 138
          L 146 124 L 188 86
          Q 196 82 206 82 L 252 82
          Q 264 82 270 88
          L 302 124 L 346 130
          C 366 134 370 154 368 178 L 368 203`,
    glass: [
      "M 160 118 L 194 94 L 214 94 L 214 118 Z",
      "M 222 94 L 250 94 L 286 118 L 222 118 Z",
    ],
    lines: ["M 218 122 L 218 190", "M 226 138 L 244 138"],
  },

  // Hatchback: the roof carries on to a tailgate that stops over the rear axle.
  hatchback: {
    wheels: [wheel(110, 32), wheel(282, 32)],
    sill: 206,
    top: `M 36 206 L 36 182
          C 34 160 44 146 64 142
          L 146 128 L 186 90
          Q 194 86 204 86 L 272 86
          Q 288 86 296 98
          L 324 142
          C 338 152 342 166 340 184 L 340 206`,
    glass: [
      "M 160 122 L 194 98 L 216 98 L 216 122 Z",
      "M 224 98 L 268 98 L 292 122 L 224 122 Z",
    ],
    lines: ["M 220 126 L 220 192", "M 228 142 L 246 142"],
  },

  // Crossover: hatchback proportions lifted onto bigger wheels, with the plastic
  // cladding along the sill that is the whole visual point of the class.
  crossover: {
    wheels: [wheel(114, 36), wheel(288, 36)],
    sill: 199,
    top: `M 34 199 L 34 174
          C 32 150 42 136 62 132
          L 142 118 L 180 80
          Q 188 76 198 76 L 268 76
          Q 284 76 292 84
          L 322 120 L 352 126
          C 366 130 370 148 368 172 L 368 199`,
    glass: [
      "M 156 112 L 188 90 L 212 90 L 212 112 Z",
      "M 220 90 L 266 90 L 288 112 L 220 112 Z",
    ],
    lines: ["M 216 116 L 216 188", "M 224 132 L 242 132", "M 60 188 L 344 188"],
  },

  // Full SUV: a box on tall wheels, roof running flat to a near-vertical tail.
  suv: {
    wheels: [wheel(116, 39), wheel(292, 39)],
    sill: 195,
    top: `M 32 195 L 32 168
          C 30 144 40 128 60 124
          L 138 110 L 174 72
          Q 180 68 192 68 L 308 68
          Q 322 68 328 78
          L 344 112
          C 356 122 360 140 358 162 L 358 195`,
    glass: [
      "M 152 104 L 182 82 L 208 82 L 208 104 Z",
      "M 216 82 L 262 82 L 262 104 L 216 104 Z",
      "M 270 82 L 302 82 L 316 104 L 270 104 Z",
    ],
    lines: ["M 212 108 L 212 184", "M 266 108 L 266 184", "M 220 126 L 238 126", "M 56 184 L 336 184"],
  },

  // Coupé: long bonnet, cabin pushed back, roof falling straight into the boot.
  coupe: {
    wheels: [wheel(118, 33), wheel(288, 33)],
    sill: 203,
    top: `M 30 203 L 30 178
          C 28 158 38 144 58 140
          L 156 124 L 200 88
          Q 208 84 218 84 L 256 84
          L 318 122 L 348 128
          C 366 132 372 152 370 176 L 370 203`,
    glass: [
      "M 172 118 L 206 96 L 228 96 L 228 118 Z",
      "M 236 96 L 254 96 L 292 118 L 236 118 Z",
    ],
    lines: ["M 232 122 L 232 190", "M 240 140 L 258 140"],
  },

  // Roadster with the roof down: a stub of windscreen, then the open cabin and
  // the tonneau behind it — the only silhouette with a dip in the middle.
  convertible: {
    wheels: [wheel(114, 33), wheel(288, 33)],
    sill: 203,
    top: `M 32 203 L 32 178
          C 30 158 40 144 60 140
          L 150 126 L 180 96 L 192 96
          L 200 118 L 266 120
          Q 282 118 288 126
          L 348 132
          C 366 136 370 154 368 178 L 368 203`,
    glass: ["M 172 122 L 184 100 L 190 100 L 194 122 Z"],
    lines: ["M 210 126 L 210 190", "M 218 144 L 236 144", "M 204 122 L 262 124"],
  },

  // Pickup: cab and bed as two separate volumes, split by the bulkhead.
  pickup: {
    wheels: [wheel(112, 35), wheel(296, 35)],
    sill: 200,
    top: `M 32 200 L 32 174
          C 30 152 40 138 60 134
          L 132 120 L 168 82
          Q 174 78 186 78 L 246 78
          L 254 116 L 266 116 L 266 106
          L 364 106 L 364 200`,
    glass: [
      "M 152 110 L 180 90 L 206 90 L 206 110 Z",
      "M 214 90 L 240 90 L 246 110 L 214 110 Z",
    ],
    lines: ["M 210 114 L 210 186", "M 218 132 L 236 132", "M 272 120 L 358 120"],
  },

  // Van: one volume, blunt nose, windscreen raked from the bumper to the roof.
  van: {
    wheels: [wheel(110, 34), wheel(300, 34)],
    sill: 201,
    top: `M 30 201 L 30 166
          C 28 142 34 122 52 112
          L 100 84
          Q 110 74 128 72 L 330 72
          Q 350 74 354 92
          L 358 132 L 358 201`,
    glass: [
      "M 74 116 L 112 88 L 140 88 L 140 116 Z",
      "M 148 88 L 210 88 L 210 116 L 148 116 Z",
      "M 218 88 L 286 88 L 286 116 L 218 116 Z",
    ],
    lines: ["M 144 120 L 144 190", "M 214 120 L 214 190", "M 152 138 L 172 138"],
  },
};

/** Anything unfamiliar — or a listing with no body type at all — gets the saloon,
 *  which is what two in three Iranian listings are. */
export const DEFAULT_BODY = "passenger_car";

export function silhouetteOf(bodyType: string | null | undefined): Silhouette {
  return SILHOUETTES[bodyType ?? ""] ?? SILHOUETTES[DEFAULT_BODY];
}

/** The underside: bumper to bumper along the rocker, with an arch cut around
 *  each wheel. Generated rather than drawn, because it is the one part of the
 *  outline that follows mechanically from where the wheels are. */
function underside(s: Silhouette): string {
  const arches = [...s.wheels].reverse().map((w) => {
    const rx = w.r + 5;
    const ry = w.r + 3;
    // Sweep 0 puts the arc above the rocker line — the opening, not a bulge.
    return `L ${w.cx + rx} ${s.sill} A ${rx} ${ry} 0 0 0 ${w.cx - rx} ${s.sill}`;
  });
  return `${arches.join(" ")} Z`;
}

/** The closed outline of the body, ready for `d`. */
export function bodyPath(s: Silhouette): string {
  return `${s.top.replace(/\s+/g, " ").trim()} ${underside(s)}`;
}

/** Where each wheel sits, now that the ground line is known. */
export function wheelsOf(s: Silhouette) {
  return s.wheels.map((w) => ({ ...w, cy: GROUND - w.r }));
}

/* -------------------------------------------------------------------- seed -- */

/**
 * A listing code turned into a small stable number. Two cars of the same model
 * and colour should not be pixel-identical in the grid, but they must also not
 * change every time the list re-renders, so the variation is hashed off the code
 * rather than randomised.
 */
export function seedOf(code: string): number {
  let h = 2166136261;
  for (let i = 0; i < code.length; i++) {
    h ^= code.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

/** Where the lamps sit on each silhouette — the cheapest detail that turns a
 *  shape into a car, and the one that tells the nose from the tail. */
export const LAMPS: Record<string, { front: [number, number]; rear: [number, number] }> = {
  passenger_car: { front: [50, 152], rear: [352, 150] },
  hatchback: { front: [54, 156], rear: [328, 158] },
  crossover: { front: [52, 146], rear: [354, 146] },
  suv: { front: [50, 140], rear: [344, 138] },
  coupe: { front: [48, 154], rear: [354, 150] },
  convertible: { front: [50, 154], rear: [352, 152] },
  pickup: { front: [50, 148], rear: [356, 140] },
  van: { front: [44, 150], rear: [352, 152] },
};

export function lampsOf(bodyType: string | null | undefined) {
  return LAMPS[bodyType ?? ""] ?? LAMPS[DEFAULT_BODY];
}

/** The ground line every silhouette stands on, exported for the reflection. */
export const GROUND_Y = GROUND;

/** @type {import('tailwindcss').Config} */

/**
 * Every colour resolves to a CSS variable rather than a literal, so the light
 * and dark palettes are swapped once on <html> instead of every class needing a
 * `dark:` twin. The `<alpha-value>` placeholder is what keeps Tailwind's own
 * opacity modifiers (`border-brand/20`, `bg-scrim/50`) working through the
 * indirection.
 */
const themed = (name) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        // Vazirmatn renders Persian properly; the rest are Latin fallbacks.
        sans: ["Vazirmatn", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
      colors: {
        // The ink scale is a contrast ramp, not a set of fixed greys: 900 is
        // always the strongest text and 50 always the page, so the numbers keep
        // meaning the same thing after the dark palette inverts them.
        ink: {
          900: themed("ink-900"),
          800: themed("ink-800"),
          700: themed("ink-700"),
          500: themed("ink-500"),
          300: themed("ink-300"),
          100: themed("ink-100"),
          50: themed("ink-50"),
        },
        // Cards and inputs: white on the light theme, one step *above* the page
        // on the dark one, so panels keep lifting off the background either way.
        surface: themed("surface"),
        // Modal backdrops, which must darken the page in both themes — ink-900
        // would turn into a white veil once the scale inverts.
        scrim: themed("scrim"),
        deal: { DEFAULT: themed("deal"), soft: themed("deal-soft") },
        over: { DEFAULT: themed("over"), soft: themed("over-soft") },
        brand: {
          DEFAULT: themed("brand"),
          // Text on a brand-soft chip: darker than the brand on light, lighter
          // on dark. `strong` is the separate fill used for button hovers.
          dark: themed("brand-dark"),
          strong: themed("brand-strong"),
          soft: themed("brand-soft"),
        },
      },
      boxShadow: {
        card: "var(--shadow-card)",
      },
    },
  },
  plugins: [],
};

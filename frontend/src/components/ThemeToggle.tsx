import { t, type Lang } from "../i18n";
import type { Theme } from "../theme";

/**
 * Light/dark switch. It shows the theme you would *get* by pressing it, not the
 * one you are already in — a sun while dark, a moon while light — which is what
 * makes a single unlabelled button legible.
 */
export function ThemeToggle({
  theme,
  lang,
  onToggle,
}: {
  theme: Theme;
  lang: Lang;
  onToggle: () => void;
}) {
  const s = t(lang);
  const label = theme === "dark" ? s.themeLight : s.themeDark;

  return (
    <button
      type="button"
      onClick={onToggle}
      title={label}
      aria-label={label}
      className="rounded-lg border border-ink-100 p-1.5 text-ink-700 transition-colors
                 hover:bg-ink-50 hover:text-ink-900"
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
    </button>
  );
}

function SunIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      aria-hidden
    >
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4 17 7M7 17l-1.6 1.6" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20.5 14.6A8.6 8.6 0 0 1 9.4 3.5a8.6 8.6 0 1 0 11.1 11.1Z" />
    </svg>
  );
}

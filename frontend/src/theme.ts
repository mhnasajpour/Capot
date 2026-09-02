import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

/** Kept in sync with the pre-paint script in index.html, which reads the same key. */
const STORAGE_KEY = "capot-theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** The choice the visitor made themselves, if they ever made one. */
function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    // Blocked storage (private mode, third-party frame) is not a failure —
    // it just means we follow the operating system for this visit.
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.(DARK_QUERY).matches ? "dark" : "light";
}

/**
 * Whole-app theme.
 *
 * Until someone touches the switch we follow the operating system — including
 * when it flips mid-session, which is the point of an automatic night mode. The
 * moment they do touch it, their choice is stored and outranks the system for
 * good, because an app that keeps overriding a deliberate click is broken.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());

  // The palette is a class on <html>; `color-scheme` is what makes the native
  // controls we don't style — selects, checkboxes, scrollbars — follow it too.
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
  }, [theme]);

  useEffect(() => {
    if (storedTheme()) return;
    const media = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setTheme(event.matches ? "dark" : "light");
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => {
      const next: Theme = current === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        // Not persisting is survivable; not switching would not be.
      }
      return next;
    });
  }, []);

  return { theme, toggle };
}

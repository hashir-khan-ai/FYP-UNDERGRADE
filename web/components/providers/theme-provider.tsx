"use client";

import * as React from "react";

export type ThemeMode = "dark" | "light";
export type ThemePreference = "system" | "dark" | "light";

interface ThemeContextValue {
  theme: ThemeMode;
  preference: ThemePreference;
  setTheme: (next: ThemeMode) => void;
  setPreference: (next: ThemePreference) => void;
  toggleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeContextValue>({
  theme: "dark",
  preference: "system",
  setTheme: () => {},
  setPreference: () => {},
  toggleTheme: () => {},
});

const STORAGE_KEY = "crcs_theme";

function getSystemTheme(): ThemeMode {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "dark";
  }
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = React.useState<ThemePreference>("system");
  const [systemTheme, setSystemTheme] = React.useState<ThemeMode>("dark");

  React.useEffect(() => {
    setSystemTheme(getSystemTheme());
    try {
      const saved = window.localStorage.getItem(STORAGE_KEY);
      if (saved === "light" || saved === "dark") {
        setPreferenceState(saved);
      } else {
        setPreferenceState("system");
      }
    } catch {
      setPreferenceState("system");
    }

    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: light)");
    const onChange = (event: MediaQueryListEvent) => {
      setSystemTheme(event.matches ? "light" : "dark");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  const theme: ThemeMode = preference === "system" ? systemTheme : preference;

  React.useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const setPreference = React.useCallback((next: ThemePreference) => {
    setPreferenceState(next);
    try {
      if (next === "system") {
        window.localStorage.removeItem(STORAGE_KEY);
      } else {
        window.localStorage.setItem(STORAGE_KEY, next);
      }
    } catch {
      // Ignore storage errors in sandboxed contexts
    }
  }, []);

  const setTheme = React.useCallback(
    (next: ThemeMode) => {
      setPreference(next);
    },
    [setPreference],
  );

  const toggleTheme = React.useCallback(() => {
    const nextTheme: ThemeMode = theme === "dark" ? "light" : "dark";
    setPreference(nextTheme);
  }, [theme, setPreference]);

  const value = React.useMemo(
    () => ({ theme, preference, setTheme, setPreference, toggleTheme }),
    [theme, preference, setTheme, setPreference, toggleTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  return React.useContext(ThemeContext);
}

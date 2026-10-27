import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { ThemeContext } from "../lib/theme";
import type { Theme } from "../lib/theme";
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem("energy-theme");
      return saved === "light" || saved === "dark" ? saved : "system";
    } catch {
      return "system";
    }
  });
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
  );
  const dark = theme === "dark" || (theme === "system" && systemDark);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    try {
      localStorage.setItem("energy-theme", theme);
    } catch {
      /* Appearance can remain in memory. */
    }
  }, [dark, theme]);
  return (
    <ThemeContext.Provider value={{ theme, setTheme, dark }}>
      {children}
    </ThemeContext.Provider>
  );
}

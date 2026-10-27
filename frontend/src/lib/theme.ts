import { createContext, useContext } from "react";
export type Theme = "light" | "dark" | "system";
export const ThemeContext = createContext<{
  theme: Theme;
  setTheme: (theme: Theme) => void;
  dark: boolean;
} | null>(null);
export function useTheme() {
  const value = useContext(ThemeContext);
  if (!value) throw new Error("ThemeProvider is required");
  return value;
}

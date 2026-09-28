// Dark by default; the choice is remembered in this browser only.
export type Theme = "dark" | "light";
const STORAGE_KEY = "betting-ml.theme";

export function getTheme(): Theme {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // storage unavailable: the theme lasts for this page load
  }
}

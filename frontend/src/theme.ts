export type Theme = "light" | "dark" | "system";
const KEY = "bancada-theme";

export function loadTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* sem storage (janela privada): segue o sistema */
  }
  return "system";
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", theme);
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    /* preferência não persiste; a página continua correta */
  }
}

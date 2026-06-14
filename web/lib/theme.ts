"use client";

import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
const KEY = "botsentry-theme";

export function getTheme(): Theme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export function setTheme(t: Theme): void {
  if (t === "dark") document.documentElement.setAttribute("data-theme", "dark");
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem(KEY, t); } catch { /* ignore */ }
  window.dispatchEvent(new CustomEvent("themechange", { detail: t }));
}

/** Subscribe to the active theme; re-renders on toggle. */
export function useTheme(): Theme {
  const [t, setT] = useState<Theme>("light");
  useEffect(() => {
    setT(getTheme());
    const h = () => setT(getTheme());
    window.addEventListener("themechange", h);
    return () => window.removeEventListener("themechange", h);
  }, []);
  return t;
}

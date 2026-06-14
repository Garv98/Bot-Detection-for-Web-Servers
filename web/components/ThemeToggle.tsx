"use client";

import { Sun, Moon } from "lucide-react";
import { useTheme, setTheme } from "@/lib/theme";

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const theme = useTheme();
  const dark = theme === "dark";
  const common = {
    border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text-2)",
    transition: "all .15s ease",
  } as const;
  if (compact) {
    return (
      <button onClick={() => setTheme(dark ? "light" : "dark")}
        aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
        title={dark ? "Light mode" : "Dark mode"}
        style={{ ...common, width: 32, height: 32, borderRadius: 9, display: "grid", placeItems: "center" }}>
        {dark ? <Moon size={15} /> : <Sun size={15} />}
      </button>
    );
  }
  return (
    <button onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      style={{ ...common, display: "flex", alignItems: "center", gap: 10, width: "100%", padding: "9px 12px", borderRadius: 10, fontSize: 13, fontWeight: 500 }}>
      {dark ? <Moon size={16} /> : <Sun size={16} />}
      {dark ? "Dark" : "Light"}
    </button>
  );
}

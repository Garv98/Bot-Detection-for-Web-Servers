"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ShieldAlert, Radar, LayoutDashboard, Brain, BarChart3, Search, CornerDownLeft,
} from "lucide-react";

type Cmd = { id: string; label: string; hint: string; icon: typeof Search; run: (r: ReturnType<typeof useRouter>) => void };

const COMMANDS: Cmd[] = [
  { id: "overview", label: "Overview", hint: "go to /", icon: ShieldAlert, run: (r) => r.push("/") },
  { id: "playground", label: "Detection Playground", hint: "go to /playground", icon: Radar, run: (r) => r.push("/playground") },
  { id: "dashboard", label: "Admin Dashboard", hint: "go to /dashboard", icon: LayoutDashboard, run: (r) => r.push("/dashboard") },
  { id: "model", label: "Model Insights", hint: "go to /model", icon: Brain, run: (r) => r.push("/model") },
  { id: "analytics", label: "Analytics", hint: "go to /analytics", icon: BarChart3, run: (r) => r.push("/analytics") },
];

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") {
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) { setQ(""); setSel(0); setTimeout(() => inputRef.current?.focus(), 20); }
  }, [open]);

  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return needle ? COMMANDS.filter((c) => c.label.toLowerCase().includes(needle) || c.hint.includes(needle)) : COMMANDS;
  }, [q]);

  useEffect(() => { setSel((s) => Math.min(s, Math.max(results.length - 1, 0))); }, [results]);

  if (!open) return null;

  const exec = (c?: Cmd) => { if (c) { c.run(router); setOpen(false); } };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); exec(results[sel]); }
  };

  return (
    <div role="dialog" aria-modal="true" aria-label="Command palette"
      onClick={() => setOpen(false)}
      style={{ position: "fixed", inset: 0, zIndex: 2000, background: "rgba(30,35,70,0.28)", backdropFilter: "blur(3px)", display: "flex", alignItems: "flex-start", justifyContent: "center", paddingTop: "12vh" }}>
      <div className="card" onClick={(e) => e.stopPropagation()}
        style={{ width: "min(560px, 92vw)", padding: 0, overflow: "hidden", boxShadow: "var(--shadow-lg)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
          <Search size={16} color="var(--muted)" />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKeyDown}
            placeholder="Jump to…" aria-label="Search commands"
            style={{ border: "none", background: "transparent", padding: 0, fontSize: 15, boxShadow: "none" }} />
          <kbd className="mono" style={kbd}>esc</kbd>
        </div>
        <div style={{ padding: 8, maxHeight: 360, overflowY: "auto" }}>
          {results.length === 0 ? (
            <div style={{ padding: 20, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>No matches</div>
          ) : results.map((c, i) => {
            const Icon = c.icon;
            const active = i === sel;
            return (
              <button key={c.id} onMouseEnter={() => setSel(i)} onClick={() => exec(c)}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
                  borderRadius: 8, border: "none", textAlign: "left",
                  background: active ? "var(--panel-3)" : "transparent", color: "var(--text)",
                }}>
                <Icon size={16} color={active ? "var(--accent)" : "var(--muted)"} />
                <span style={{ flex: 1, fontSize: 14 }}>{c.label}</span>
                <span style={{ fontSize: 11, color: "var(--muted-2)" }}>{c.hint}</span>
                {active && <CornerDownLeft size={13} color="var(--muted)" />}
              </button>
            );
          })}
        </div>
        <div style={{ padding: "8px 14px", borderTop: "1px solid var(--border)", fontSize: 11, color: "var(--muted-2)", display: "flex", gap: 14 }}>
          <span><kbd className="mono" style={kbd}>↑</kbd> <kbd className="mono" style={kbd}>↓</kbd> navigate</span>
          <span><kbd className="mono" style={kbd}>↵</kbd> open</span>
          <span style={{ marginLeft: "auto" }}><kbd className="mono" style={kbd}>⌃K</kbd> toggle</span>
        </div>
      </div>
    </div>
  );
}

const kbd: React.CSSProperties = {
  fontSize: 10, padding: "1px 5px", borderRadius: 5, background: "var(--panel-3)",
  border: "1px solid var(--border)", color: "var(--muted)",
};

"use client";

import { useMemo, useState, type ComponentType, type ReactNode } from "react";
import { ChevronDown, ChevronUp, ChevronsUpDown } from "lucide-react";

type IconType = ComponentType<{ size?: number | string; color?: string; className?: string }>;

export function PageHeader({ title, subtitle, right }: {
  title: string; subtitle?: string; right?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 24, flexWrap: "wrap", gap: 12 }}>
      <div>
        <h1 style={{ fontSize: 26, fontWeight: 700, margin: 0, letterSpacing: -0.3 }}>{title}</h1>
        {subtitle && <p style={{ color: "var(--muted)", margin: "6px 0 0", fontSize: 14 }}>{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Card({ children, className = "", style }: {
  children: ReactNode; className?: string; style?: React.CSSProperties;
}) {
  return <div className={`card ${className}`} style={{ padding: 20, ...style }}>{children}</div>;
}

export function StatCard({ label, value, sub, accent, icon: Icon, trend }: {
  label: string; value: ReactNode; sub?: string; accent?: string;
  icon?: IconType; trend?: { value: number; label: string };
}) {
  const accentColor = accent ?? "var(--accent)";
  const up = trend ? trend.value >= 0 : false;
  return (
    <Card style={{ display: "flex", flexDirection: "column", gap: 6, position: "relative", borderBottom: `2px solid ${accentColor}` }}>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.6 }}>{label}</span>
        {Icon && <Icon size={20} color="var(--muted)" />}
      </div>
      <span className="mono" style={{ fontSize: 28, fontWeight: 700, color: accent ?? "var(--text)" }}>{value}</span>
      {trend && (
        <span className="mono" style={{ fontSize: 12, fontWeight: 600, color: up ? "var(--safe)" : "var(--bot)" }}>
          {up ? "▲" : "▼"} {up ? "+" : ""}{trend.value.toFixed(1)}%
          <span style={{ color: "var(--muted-2)", fontWeight: 400, marginLeft: 6 }}>{trend.label}</span>
        </span>
      )}
      {sub && <span style={{ fontSize: 12, color: "var(--muted)" }}>{sub}</span>}
    </Card>
  );
}

export function Badge({ children, tone = "neutral" }: {
  children: ReactNode; tone?: "bot" | "safe" | "neutral" | "warn";
}) {
  const colors = {
    bot: { bg: "var(--bot-dim)", fg: "#b91c1c", bd: "rgba(239,68,68,0.35)" },
    safe: { bg: "var(--safe-dim)", fg: "#047857", bd: "rgba(16,185,129,0.35)" },
    warn: { bg: "rgba(245,158,11,0.14)", fg: "#b45309", bd: "rgba(245,158,11,0.4)" },
    neutral: { bg: "rgba(99,102,241,0.10)", fg: "var(--text-2)", bd: "var(--border)" },
  }[tone];
  return (
    <span style={{
      fontSize: 12, padding: "3px 10px", borderRadius: 999,
      background: colors.bg, color: colors.fg, border: `1px solid ${colors.bd}`,
      fontWeight: 600, whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

/** Threat severity label derived from a 0–1 risk score. */
export function ThreatBadge({ score }: { score: number }) {
  const level =
    score > 0.7 ? { label: "CRITICAL", c: "#b91c1c", bg: "var(--bot-dim)" }
    : score > 0.4 ? { label: "HIGH", c: "#c2410c", bg: "rgba(234,88,12,0.12)" }
    : score > 0.2 ? { label: "MEDIUM", c: "#b45309", bg: "rgba(245,158,11,0.14)" }
    : { label: "LOW", c: "#047857", bg: "var(--safe-dim)" };
  return (
    <span className="status-pill" style={{ background: level.bg, color: level.c, border: `1px solid ${level.c}40` }}>
      {level.label}
    </span>
  );
}

/** IP address rendered in a styled monospace pill, with an optional /24 below. */
export function IPTag({ ip, cidr }: { ip: string; cidr?: string }) {
  return (
    <span style={{ display: "inline-flex", flexDirection: "column", gap: 2, lineHeight: 1.2 }}>
      <span className="ip-addr">{ip}</span>
      {cidr && <span style={{ fontSize: 10, color: "var(--muted)", paddingLeft: 2 }}>{cidr}</span>}
    </span>
  );
}

/** Horizontal risk bar: green→amber→red gradient fill with a % label. */
export function RiskBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 90 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 999, background: "var(--panel-3)", overflow: "hidden" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 999,
          background: "linear-gradient(90deg, var(--safe), var(--warn), var(--bot))",
          backgroundSize: `${100 / Math.max(pct, 1) * 100}% 100%`,
          transition: "width .5s cubic-bezier(.2,.7,.3,1)",
        }} />
      </div>
      <span className="mono" style={{ fontSize: 11, color: "var(--muted)", width: 30, textAlign: "right" }}>
        {Math.round(pct)}%
      </span>
    </div>
  );
}

export function ChartCard({ title, hint, children, height = 280, right }: {
  title: string; hint?: string; children: ReactNode; height?: number; right?: ReactNode;
}) {
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 14, gap: 10, flexWrap: "wrap" }}>
        <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>{title}</h3>
        {right ?? (hint && <span style={{ fontSize: 12, color: "var(--muted)" }}>{hint}</span>)}
      </div>
      <div style={{ height }}>{children}</div>
    </Card>
  );
}

/** Animated SVG ring spinner in --accent. */
export function Spinner({ label = "Loading…", size = 22 }: { label?: string; size?: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--muted)", fontSize: 14, padding: 20 }}>
      <svg width={size} height={size} viewBox="0 0 24 24" className="spin" style={{ flexShrink: 0 }}>
        <circle cx="12" cy="12" r="9" fill="none" stroke="var(--panel-3)" strokeWidth="3" />
        <path d="M12 3 a9 9 0 0 1 9 9" fill="none" stroke="var(--accent)" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label}
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%", radius = 8, style }: {
  height?: number | string; width?: number | string; radius?: number; style?: React.CSSProperties;
}) {
  return <div className="skeleton" style={{ height, width, borderRadius: radius, ...style }} />;
}

export function SkeletonCard({ lines = 3, height = 110 }: { lines?: number; height?: number }) {
  return (
    <Card style={{ minHeight: height, display: "flex", flexDirection: "column", gap: 10 }}>
      <Skeleton height={12} width="40%" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} height={14} width={`${90 - i * 15}%`} />
      ))}
    </Card>
  );
}

/** Dismissible banner: info / warn / error. */
export function Alert({ tone = "info", title, body, onDismiss }: {
  tone?: "info" | "warn" | "error"; title: string; body?: ReactNode; onDismiss?: () => void;
}) {
  const c = { info: "var(--info)", warn: "var(--warn)", error: "var(--bot)" }[tone];
  return (
    <div className="card" style={{ padding: "12px 16px", borderLeft: `3px solid ${c}`, display: "flex", gap: 12, alignItems: "flex-start" }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: c }}>{title}</div>
        {body && <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>{body}</div>}
      </div>
      {onDismiss && (
        <button onClick={onDismiss} style={{ background: "transparent", border: "none", color: "var(--muted)", fontSize: 18, lineHeight: 1, padding: 0 }} aria-label="Dismiss">×</button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DataTable — sticky header, sortable columns, hover, empty + loading states
// ---------------------------------------------------------------------------
export type Column<T> = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  sortValue?: (row: T) => number | string;
  render: (row: T) => ReactNode;
  width?: number | string;
};

export function DataTable<T>({ columns, rows, loading = false, empty = "No data", rowKey }: {
  columns: Column<T>[]; rows: T[]; loading?: boolean; empty?: ReactNode;
  rowKey: (row: T, i: number) => string;
}) {
  const [sort, setSort] = useState<{ key: string; dir: "asc" | "desc" } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      const cmp = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [rows, sort, columns]);

  const toggle = (key: string) =>
    setSort((s) => s?.key === key ? (s.dir === "asc" ? { key, dir: "desc" } : null) : { key, dir: "asc" });

  return (
    <div style={{ overflowX: "auto", maxHeight: 460, overflowY: "auto", borderRadius: 10 }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ position: "sticky", top: 0, zIndex: 1, background: "var(--panel-2)" }}>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const Sortable = c.sortValue != null;
              return (
                <th key={c.key} onClick={Sortable ? () => toggle(c.key) : undefined}
                  style={{
                    padding: "10px 10px", textAlign: c.align ?? "left", color: "var(--muted)",
                    fontWeight: 500, whiteSpace: "nowrap", cursor: Sortable ? "pointer" : "default",
                    borderBottom: "1px solid var(--border)", width: c.width, userSelect: "none",
                  }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4, verticalAlign: "middle" }}>
                    {c.header}
                    {Sortable && (active
                      ? (sort!.dir === "asc" ? <ChevronUp size={13} /> : <ChevronDown size={13} />)
                      : <ChevronsUpDown size={13} style={{ opacity: 0.4 }} />)}
                  </span>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                {columns.map((c) => <td key={c.key} style={{ padding: "10px" }}><Skeleton height={14} /></td>)}
              </tr>
            ))
          ) : sorted.length === 0 ? (
            <tr><td colSpan={columns.length} style={{ padding: 28, textAlign: "center", color: "var(--muted)" }}>{empty}</td></tr>
          ) : (
            sorted.map((row, i) => (
              <tr key={rowKey(row, i)} className="row-hover" style={{ borderTop: "1px solid var(--border)" }}>
                {columns.map((c) => (
                  <td key={c.key} style={{ padding: "9px 10px", textAlign: c.align ?? "left" }}>{c.render(row)}</td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Glassmorphism primitives (premium light theme)
// ---------------------------------------------------------------------------

/** Frosted glass panel. `hero` adds a gradient top accent; `lift` enables hover. */
export function GlassCard({ children, className = "", style, hero = false, lift = false }: {
  children: ReactNode; className?: string; style?: React.CSSProperties; hero?: boolean; lift?: boolean;
}) {
  return (
    <div className={`card ${lift ? "lift" : ""} ${className}`}
      style={{ padding: 20, position: "relative", overflow: "hidden", ...style }}>
      {hero && (
        <span aria-hidden style={{
          position: "absolute", inset: "0 0 auto 0", height: 3,
          background: "linear-gradient(90deg, var(--accent), var(--accent-blue), var(--accent-violet))",
        }} />
      )}
      {children}
    </div>
  );
}

/** Brief-compat alias of StatCard. */
export const MetricCard = StatCard;
/** Brief-compat alias of ThreatBadge. */
export const RiskBadge = ThreatBadge;
/** Brief-compat aliases. */
export const SkeletonLoader = Skeleton;
export const LoadingState = Spinner;

/** Small dot + label status indicator (live / offline / warn / muted). */
export function StatusIndicator({ tone = "ok", label, pulse = false }: {
  tone?: "ok" | "bot" | "warn" | "muted"; label: ReactNode; pulse?: boolean;
}) {
  const color = { ok: "var(--safe)", bot: "var(--bot)", warn: "var(--warn)", muted: "var(--muted)" }[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color: tone === "muted" ? "var(--muted)" : color }}>
      <span className={pulse ? "live-dot" : ""} style={{ width: 8, height: 8, borderRadius: "50%", background: color, flexShrink: 0 }} />
      {label}
    </span>
  );
}

/** Centered empty-state placeholder for charts/feeds with no data yet. */
export function EmptyState({ icon: Icon, title, hint, action }: {
  icon?: IconType; title: string; hint?: ReactNode; action?: ReactNode;
}) {
  return (
    <div style={{ display: "grid", placeItems: "center", textAlign: "center", padding: "32px 20px", gap: 10, color: "var(--muted)" }}>
      {Icon && (
        <div style={{ width: 48, height: 48, borderRadius: 14, display: "grid", placeItems: "center", background: "var(--panel-3)", color: "var(--accent)" }}>
          <Icon size={22} />
        </div>
      )}
      <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>{title}</div>
      {hint && <div style={{ fontSize: 13, maxWidth: 320 }}>{hint}</div>}
      {action}
    </div>
  );
}

export const fmt = (n: number) => n.toLocaleString("en-US");

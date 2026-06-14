"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ReferenceLine,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import type {
  CIDRActivity, FeatureImportance, RiskBin, ScatterPoint, TimePoint, TopBot, TopPath,
} from "@/lib/api";
import { IPTag } from "@/components/ui";

// Single source of truth for chart colors (the one place hex is allowed).
// Light glassmorphism palette — keep keys in sync with globals.css tokens.
// Neutral grid/axis tones read well on both light and dark backgrounds; the
// vivid bot/human/accent colors work on both. The tooltip uses CSS vars (DOM
// inline styles resolve var()), so it re-themes automatically.
const CHART_THEME = {
  background: "transparent",
  gridColor: "rgba(120,130,170,0.22)",
  textColor: "#7c87a8",
  botColor: "#ef4444",
  humanColor: "#3b82f6",
  accentColor: "#6366f1",
  safeColor: "#10b981",
  warnColor: "#f59e0b",
};
const { gridColor: GRID, textColor: AXIS, botColor: BOT, humanColor: HUMAN, accentColor: ACCENT } = CHART_THEME;

const tooltipStyle = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  fontSize: 12,
  color: "var(--text)",
  boxShadow: "var(--shadow)",
  backdropFilter: "blur(10px)",
};

export function ThroughputChart({ data }: { data: TimePoint[] }) {
  const rows = data.map((d) => ({
    time: new Date(d.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    bots: d.bots, humans: d.humans, total: d.bots + d.humans,
    botPct: d.bots + d.humans > 0 ? (d.bots / (d.bots + d.humans)) * 100 : 0,
  }));
  const mean = rows.length ? rows.reduce((a, r) => a + r.total, 0) / rows.length : 0;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={rows}>
        <defs>
          <linearGradient id="gTotal" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={HUMAN} stopOpacity={0.5} />
            <stop offset="100%" stopColor={HUMAN} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="time" stroke={AXIS} fontSize={11} />
        <YAxis stroke={AXIS} fontSize={11} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} content={<ThroughputTip />} />
        {mean > 0 && (
          <ReferenceLine y={mean} stroke={ACCENT} strokeDasharray="4 4"
            label={{ value: `mean ${mean.toFixed(0)}`, fill: ACCENT, fontSize: 10, position: "insideTopRight" }} />
        )}
        <Area type="monotone" dataKey="total" stroke={HUMAN} fill="url(#gTotal)" strokeWidth={2} name="requests" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function ThroughputTip({ active, payload, label }: {
  active?: boolean; payload?: { payload: { bots: number; humans: number; total: number; botPct: number } }[]; label?: string;
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div style={{ ...tooltipStyle, padding: "8px 10px" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label}</div>
      <div style={{ color: HUMAN }}>humans: {p.humans.toLocaleString()}</div>
      <div style={{ color: BOT }}>bots: {p.bots.toLocaleString()}</div>
      <div style={{ color: AXIS, marginTop: 2 }}>bot share: {p.botPct.toFixed(1)}%</div>
    </div>
  );
}

/** Proportional (percentage) stacked area: bot vs human share over time. */
export function BotHumanArea({ data }: { data: TimePoint[] }) {
  const rows = data.map((d) => ({
    time: new Date(d.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    bots: d.bots, humans: d.humans,
  }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={rows} stackOffset="expand">
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="time" stroke={AXIS} fontSize={11} />
        <YAxis stroke={AXIS} fontSize={11} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} />
        <Tooltip contentStyle={tooltipStyle}
          formatter={(v) => (typeof v === "number" ? v.toLocaleString() : String(v))} />
        <Legend wrapperStyle={{ fontSize: 12, color: AXIS }} iconType="circle" />
        <Area type="monotone" dataKey="humans" stackId="1" stroke={HUMAN} fill={HUMAN} fillOpacity={0.35} name="humans" />
        <Area type="monotone" dataKey="bots" stackId="1" stroke={BOT} fill={BOT} fillOpacity={0.45} name="bots" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function RiskDistChart({ data, logScale = true }: { data: RiskBin[]; logScale?: boolean }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="requests_per_hour_bucket" stroke={AXIS} fontSize={11} />
        <YAxis stroke={AXIS} fontSize={11}
          scale={logScale ? "log" : "auto"} domain={logScale ? [1, "auto"] : [0, "auto"]} allowDataOverflow={logScale} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 12, color: AXIS }} iconType="circle" />
        <Bar dataKey="humans" stackId="a" fill={HUMAN} fillOpacity={0.7} name="humans" />
        <Bar dataKey="bots" stackId="a" fill={BOT} name="bots" />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Ranked horizontal list of top flagged IPs with inline risk bars. */
export function TopBotsChart({ data }: { data: TopBot[] }) {
  const rows = [...data].slice(0, 12);
  const max = Math.max(1, ...rows.map((r) => r.req_count));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, height: "100%", overflowY: "auto" }}>
      {rows.map((r, i) => (
        <div key={r.ip} className="row-hover" style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px", borderRadius: 8 }}>
          <span className="mono" style={{ width: 22, color: "var(--muted-2)", fontSize: 12, textAlign: "right" }}>{i + 1}</span>
          <div style={{ width: 120, flexShrink: 0 }}><IPTag ip={r.ip} /></div>
          <div style={{ flex: 1, minWidth: 60 }}>
            <div style={{ height: 6, borderRadius: 999, background: "var(--panel-3)", overflow: "hidden" }}>
              <div style={{ width: `${(r.req_count / max) * 100}%`, height: "100%", background: BOT, borderRadius: 999 }} />
            </div>
          </div>
          <span className="mono" style={{ width: 64, textAlign: "right", fontSize: 12, color: "var(--text-2)" }}>{r.req_count.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

export function ImportanceChart({ data }: { data: FeatureImportance[] }) {
  const rows = [...data].reverse();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout="vertical" margin={{ left: 60, right: 36 }}>
        <defs>
          <linearGradient id="gImp" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#c7d2fe" />
            <stop offset="100%" stopColor={ACCENT} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" stroke={AXIS} fontSize={11} />
        <YAxis type="category" dataKey="feature" stroke={AXIS} fontSize={10} width={130} />
        <Tooltip contentStyle={tooltipStyle} formatter={(v) => (typeof v === "number" ? v.toFixed(3) : String(v))} cursor={{ fill: "rgba(59,158,255,0.06)" }} />
        <Bar dataKey="importance" fill="url(#gImp)" radius={[0, 4, 4, 0]}
          label={{ position: "right", fill: AXIS, fontSize: 10, formatter: (v) => Number(v).toFixed(3) }} />
      </BarChart>
    </ResponsiveContainer>
  );
}

const QUADRANTS = [
  { x: "2%", y: "6%", text: "Low activity bots", anchor: "start" as const },
  { x: "98%", y: "6%", text: "High risk", anchor: "end" as const },
  { x: "2%", y: "94%", text: "Normal humans", anchor: "start" as const },
  { x: "98%", y: "94%", text: "Power users", anchor: "end" as const },
];

export function BehaviorScatter({ data }: { data: ScatterPoint[] }) {
  const bots = data.filter((d) => d.is_robot === 1);
  const humans = data.filter((d) => d.is_robot === 0);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ScatterChart margin={{ left: 4, bottom: 6, right: 8, top: 8 }}>
        <defs>
          <filter id="botGlow" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="0" stdDeviation="2" floodColor={BOT} floodOpacity="0.7" />
          </filter>
        </defs>
        <CartesianGrid stroke={GRID} />
        <XAxis type="number" dataKey="requests_per_hour" name="req/hr" stroke={AXIS}
          fontSize={11} scale="log" domain={[0.1, "auto"]} allowDataOverflow
          label={{ value: "requests/hour (log)", position: "insideBottom", offset: -2, fill: AXIS, fontSize: 11 }} />
        <YAxis type="number" dataKey="ua_entropy" name="UA entropy" stroke={AXIS} fontSize={11}
          label={{ value: "UA entropy", angle: -90, position: "insideLeft", fill: AXIS, fontSize: 11 }} />
        <ZAxis type="number" dataKey="req_count" range={[24, 220]} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} content={<ScatterTip />} />
        {QUADRANTS.map((q) => (
          <text key={q.text} x={q.x} y={q.y} fill="var(--muted-2)" fontSize={10} textAnchor={q.anchor}>{q.text}</text>
        ))}
        <Scatter name="humans" data={humans} fill="none" stroke={HUMAN} strokeWidth={1.4} shape="circle" />
        <Scatter name="bots" data={bots} fill={BOT} fillOpacity={0.85} filter="url(#botGlow)" shape="circle" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

function ScatterTip({ active, payload }: {
  active?: boolean; payload?: { payload: ScatterPoint }[];
}) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const ip = p.ip.length > 18 ? p.ip.slice(0, 16) + "…" : p.ip;
  return (
    <div style={{ ...tooltipStyle, padding: "8px 10px" }}>
      <div className="mono" style={{ fontWeight: 600, marginBottom: 4 }}>{ip}</div>
      <div>req/hr: {p.requests_per_hour.toFixed(1)}</div>
      <div>UA entropy: {p.ua_entropy.toFixed(2)}</div>
      <div style={{ marginTop: 4, color: p.is_robot ? BOT : HUMAN, fontWeight: 600 }}>
        {p.is_robot ? "ROBOT" : "HUMAN"}
      </div>
    </div>
  );
}

const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/** Heat scale: panel → blue → amber → red. */
function heatColor(t: number): string {
  if (t <= 0) return "rgba(99,102,241,0.05)";
  const stops: [number, [number, number, number]][] = [
    [0.0, [224, 231, 255]],
    [0.35, [129, 140, 248]],
    [0.7, [245, 158, 11]],
    [1.0, [239, 68, 68]],
  ];
  let lo = stops[0], hi = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i][0] && t <= stops[i + 1][0]) { lo = stops[i]; hi = stops[i + 1]; break; }
  }
  const f = (t - lo[0]) / Math.max(hi[0] - lo[0], 1e-6);
  const c = [0, 1, 2].map((k) => Math.round(lo[1][k] + (hi[1][k] - lo[1][k]) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export function Heatmap({ data }: { data: { dow: number; hour: number; requests: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.requests));
  const lookup = new Map(data.map((d) => [`${d.dow}-${d.hour}`, d.requests]));
  return (
    <div>
      <div style={{ overflowX: "auto" }}>
        <div style={{ display: "grid", gridTemplateColumns: `40px repeat(24, 1fr)`, gap: 2, minWidth: 620 }}>
          <div />
          {Array.from({ length: 24 }, (_, h) => (
            <div key={h} style={{ fontSize: 9, color: "var(--muted)", textAlign: "center" }}>{h}</div>
          ))}
          {DOW.map((label, d) => (
            <HeatRow key={d} label={label} d={d} lookup={lookup} max={max} />
          ))}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10, fontSize: 10, color: "var(--muted)" }}>
        <span>less</span>
        <div style={{ flex: 1, maxWidth: 160, height: 8, borderRadius: 4, background: `linear-gradient(90deg, ${heatColor(0.01)}, ${heatColor(0.35)}, ${heatColor(0.7)}, ${heatColor(1)})` }} />
        <span>more</span>
      </div>
    </div>
  );
}

function HeatRow({ label, d, lookup, max }: {
  label: string; d: number; lookup: Map<string, number>; max: number;
}) {
  return (
    <>
      <div style={{ fontSize: 10, color: "var(--muted)", display: "flex", alignItems: "center" }}>{label}</div>
      {Array.from({ length: 24 }, (_, h) => {
        const v = lookup.get(`${d}-${h}`) ?? 0;
        return (
          <div key={h} title={`${label} ${h}:00 — ${v} req`}
            style={{ height: 22, borderRadius: 4, background: heatColor(v / max) }} />
        );
      })}
    </>
  );
}

// ---- New analytics charts -------------------------------------------------

/** Top /24 subnets by event count, colored by bot ratio. */
export function CIDRActivityChart({ data }: { data: CIDRActivity[] }) {
  const rows = [...data].slice(0, 15);
  const max = Math.max(1, ...rows.map((r) => r.total));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, height: "100%", overflowY: "auto" }}>
      {rows.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13, padding: 12 }}>No CIDR activity yet.</div>}
      {rows.map((r) => {
        const ratioColor = r.bot_ratio > 0.5 ? BOT : r.bot_ratio > 0.2 ? CHART_THEME.warnColor : HUMAN;
        return (
          <div key={r.cidr_block} className="row-hover" style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 8px", borderRadius: 8 }}>
            <span className="mono" style={{ width: 130, fontSize: 11, color: "var(--accent)", flexShrink: 0 }}>{r.cidr_block}</span>
            <div style={{ flex: 1, minWidth: 60 }}>
              <div style={{ height: 6, borderRadius: 999, background: "var(--panel-3)", overflow: "hidden" }}>
                <div style={{ width: `${(r.total / max) * 100}%`, height: "100%", background: ratioColor, borderRadius: 999 }} />
              </div>
            </div>
            <span className="mono" style={{ width: 52, textAlign: "right", fontSize: 12, color: "var(--text-2)" }}>{r.total.toLocaleString()}</span>
            <span className="mono" style={{ width: 44, textAlign: "right", fontSize: 11, color: ratioColor }}>{Math.round(r.bot_ratio * 100)}%</span>
          </div>
        );
      })}
    </div>
  );
}

/** Top requested paths as a horizontal stacked bar (bots vs humans). */
export function TopPathsChart({ data }: { data: TopPath[] }) {
  const rows = [...data].slice(0, 20).reverse();
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={rows} layout="vertical" margin={{ left: 40, right: 16 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" stroke={AXIS} fontSize={11} />
        <YAxis type="category" dataKey="path" stroke={AXIS} fontSize={10} width={150}
          tickFormatter={(v) => { const s = String(v ?? ""); return s.length > 22 ? s.slice(0, 20) + "…" : s; }} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 12, color: AXIS }} iconType="circle" />
        <Bar dataKey="humans" stackId="p" fill={HUMAN} fillOpacity={0.75} name="humans" radius={[0, 0, 0, 0]} />
        <Bar dataKey="bots" stackId="p" fill={BOT} name="bots" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export { CHART_THEME };

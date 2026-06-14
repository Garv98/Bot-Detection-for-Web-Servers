"use client";

import { useMemo, useState } from "react";
import { Bot, User, ShieldCheck, Loader2, Activity, Layers, Copy, Download, Network, Plus, Gauge, Ban } from "lucide-react";
import { api, type CheckResult, type BulkRow, type Signal, type Decision } from "@/lib/api";
import { Card, PageHeader, Badge, Spinner, DataTable, type Column } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { ensureAdminToken, setAdminToken } from "@/lib/admin";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { motion } from "framer-motion";

type Preset = { group: string; label: string; ip: string; ua: string; path: string };

const PRESETS: Preset[] = [
  { group: "Real traffic", label: "DotBot crawler", ip: "216.244.58782",
    ua: "Mozilla/5.0 (compatible; DotBot/1.2; +https://opensiteexplorer.org/dotbot)", path: "/Record/9a2f" },
  { group: "Real traffic", label: "ICC-Crawler", ip: "202.180.35500",
    ua: "ICC-Crawler/2.0 (Mozilla-compatible; http://ucri.nict.go.jp/en/icccrawler.html)", path: "/Record/6e32" },
  { group: "Real traffic", label: "Campus user", ip: "155.207.48922",
    ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/64 Safari/537.36", path: "/Search/Results" },
  { group: "Synthetic UA", label: "Googlebot", ip: "66.249.66.1",
    ua: "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)", path: "/x" },
  { group: "Synthetic UA", label: "Chrome user", ip: "203.0.113.10",
    ua: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", path: "/home" },
  { group: "Synthetic UA", label: "Python scraper", ip: "45.130.1.9",
    ua: "python-requests/2.31.0", path: "/api/data" },
];

const SEV_COLOR: Record<string, string> = {
  danger: "var(--bot)", warn: "var(--warn)", ok: "var(--safe)", info: "var(--info)",
};

function threatLabel(score: number, isBot: boolean): string {
  if (isBot || score > 0.7) return "CRITICAL";
  if (score > 0.4) return "HIGH";
  if (score > 0.2) return "MEDIUM";
  return "SAFE";
}

function RingGauge({ score, isBot, loading }: { score: number; isBot: boolean; loading?: boolean }) {
  const pct = Math.round(score * 100);
  const color = isBot ? "var(--bot)" : score > 0.3 ? "var(--warn)" : "var(--safe)";
  const r = 70, C = 2 * Math.PI * r;
  const offset = C * (1 - pct / 100);
  return (
    <div style={{ position: "relative", width: 180, height: 180 }} className={loading ? "skeleton" : ""}>
      <svg width="180" height="180" style={{ transform: "rotate(-90deg)" }}>
        <circle cx="90" cy="90" r={r} fill="none" stroke="var(--panel-3)" strokeWidth="14" />
        {/* tick marks every 15° */}
        {Array.from({ length: 24 }, (_, i) => {
          const a = (i / 24) * 2 * Math.PI;
          const inner = r + 9, outer = r + 14;
          return (
            <line key={i}
              x1={90 + inner * Math.cos(a)} y1={90 + inner * Math.sin(a)}
              x2={90 + outer * Math.cos(a)} y2={90 + outer * Math.sin(a)}
              stroke="var(--border)" strokeWidth="1.5" />
          );
        })}
        <circle cx="90" cy="90" r={r} fill="none" stroke={color} strokeWidth="14"
          strokeLinecap="round" strokeDasharray={C} strokeDashoffset={offset}
          style={{ transition: "stroke-dashoffset .8s cubic-bezier(.2,.7,.3,1), stroke .4s" }} />
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>
        <div>
          <div className="mono" style={{ fontSize: 42, fontWeight: 800, color, lineHeight: 1 }}>
            <AnimatedNumber value={pct} format={(n) => `${Math.round(n)}`} />
          </div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 2 }}>risk / 100</div>
          <div className="mono" style={{ fontSize: 11, fontWeight: 700, color, marginTop: 4, letterSpacing: 0.5 }}>
            {threatLabel(score, isBot)}
          </div>
        </div>
      </div>
    </div>
  );
}

function SignalRow({ s }: { s: Signal }) {
  const c = SEV_COLOR[s.severity] ?? SEV_COLOR.info;
  return (
    <div title={s.note} style={{
      display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
      borderLeft: `3px solid ${c}`, background: "var(--panel-2)", borderRadius: 8, cursor: "default",
    }} className="hoverable">
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{s.label}</div>
        <div style={{ fontSize: 11, color: "var(--muted)" }}>{s.note}</div>
      </div>
      <div className="mono" style={{ fontSize: 13, fontWeight: 700, color: c, whiteSpace: "nowrap" }}>{s.value}</div>
    </div>
  );
}

const DECISION_META: Record<Decision, { color: string; Icon: typeof ShieldCheck; label: string }> = {
  allow: { color: "var(--safe)", Icon: ShieldCheck, label: "ALLOW" },
  throttle: { color: "var(--warn)", Icon: Gauge, label: "THROTTLE" },
  block: { color: "var(--bot)", Icon: Ban, label: "BLOCK" },
};

function DecisionBanner({ decision, httpStatus, action }: {
  decision?: Decision; httpStatus?: number; action?: string;
}) {
  if (!decision) return null;
  const m = DECISION_META[decision];
  return (
    <motion.div
      key={decision}
      initial={{ opacity: 0, scale: 0.96, y: 6 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.2, 0.7, 0.3, 1] }}
      style={{
        width: "100%", display: "flex", alignItems: "center", gap: 12, padding: "14px 16px",
        borderRadius: 14, background: `color-mix(in srgb, ${m.color} 12%, var(--panel-2))`,
        border: `1px solid color-mix(in srgb, ${m.color} 35%, transparent)`,
        borderLeft: `4px solid ${m.color}`,
      }}>
      <m.Icon size={22} color={m.color} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontWeight: 800, color: m.color, letterSpacing: 0.6, fontSize: 15 }}>{m.label}</span>
          <span className="mono" style={{
            fontSize: 11, fontWeight: 700, padding: "2px 7px", borderRadius: 6,
            background: "var(--panel-3)", color: httpStatus === 200 ? "var(--safe)" : "var(--bot)",
          }}>HTTP {httpStatus}</span>
        </div>
        <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 2 }}>{action}</div>
      </div>
    </motion.div>
  );
}

type HistItem = { ip: string; risk: number; isBot: boolean; at: string };

export default function PlaygroundPage() {
  const toast = useToast();
  const [ip, setIp] = useState(PRESETS[0].ip);
  const [ua, setUa] = useState(PRESETS[0].ua);
  const [path, setPath] = useState(PRESETS[0].path);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistItem[]>([]);

  const [bulkText, setBulkText] = useState("216.244.58782\n155.207.48922\n66.249.66.1\n8.8.8.8");
  const [bulkRows, setBulkRows] = useState<BulkRow[] | null>(null);
  const [bulkLoading, setBulkLoading] = useState(false);

  const applyPreset = (p: Preset) => { setIp(p.ip); setUa(p.ua); setPath(p.path); };

  const runCheck = async () => {
    setLoading(true); setError(null);
    try {
      const r = await api.check(ip, ua, path);
      setResult(r);
      setHistory((h) => [
        { ip: r.ip, risk: r.risk_score, isBot: r.is_bot,
          at: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) },
        ...h,
      ].slice(0, 8));
    } catch { setError("Request failed — is the API reachable?"); }
    finally { setLoading(false); }
  };

  const runBulk = async () => {
    setBulkLoading(true);
    const ips = bulkText.split("\n").map((s) => s.trim()).filter(Boolean);
    try { setBulkRows(await api.bulkScore(ips)); }
    catch { setBulkRows([]); }
    finally { setBulkLoading(false); }
  };

  const groups = Array.from(new Set(PRESETS.map((p) => p.group)));

  const copyFlagged = () => {
    const flagged = (bulkRows ?? []).filter((r) => r.is_bot).map((r) => r.ip);
    if (!flagged.length) return toast.show({ tone: "info", title: "No flagged IPs to copy" });
    navigator.clipboard.writeText(flagged.join("\n"));
    toast.show({ tone: "success", title: `Copied ${flagged.length} flagged IPs` });
  };

  const exportCsv = () => {
    const rows = bulkRows ?? [];
    if (!rows.length) return;
    const csv = ["ip,risk_score,is_bot", ...rows.map((r) => `${r.ip},${r.risk_score},${r.is_bot}`)].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "bulk-scores.csv"; a.click();
    URL.revokeObjectURL(url);
    toast.show({ tone: "success", title: "Exported CSV" });
  };

  const addAllowlist = async () => {
    if (!result) return;
    const token = ensureAdminToken();
    if (!token) return;
    try {
      const r = await api.addAllowlist(result.ip, token);
      toast.show({ tone: r.already_present ? "info" : "success",
        title: r.already_present ? "Already allowlisted" : "Added to allowlist", body: result.ip });
    } catch (e) {
      const msg = String(e);
      if (msg.includes("403")) { setAdminToken(""); toast.show({ tone: "error", title: "Invalid admin token", body: "Cleared — try again." }); }
      else if (msg.includes("503")) toast.show({ tone: "error", title: "Admin disabled", body: "Set ADMIN_TOKEN on the API." });
      else toast.show({ tone: "error", title: "Could not add to allowlist" });
    }
  };

  const bulkColumns: Column<BulkRow>[] = useMemo(() => [
    { key: "ip", header: "IP", sortValue: (r) => r.ip, render: (r) => <span className="mono">{r.ip}</span> },
    { key: "risk", header: "Risk", align: "right", sortValue: (r) => r.risk_score,
      render: (r) => <span className="mono" style={{ color: r.is_bot ? "var(--bot)" : "var(--safe)" }}>{Math.round(r.risk_score * 100)}</span> },
    { key: "verdict", header: "Verdict", sortValue: (r) => (r.is_bot ? 1 : 0),
      render: (r) => <Badge tone={r.is_bot ? "bot" : "safe"}>{r.is_bot ? "bot" : "human"}</Badge> },
  ], []);

  const cidr = useMemo(() => {
    const parts = ip.split(".");
    return parts.length >= 3 && parts.slice(0, 3).every((p) => /^\d+$/.test(p)) ? `${parts[0]}.${parts[1]}.${parts[2]}.0/24` : "—";
  }, [ip]);

  const reqVol = result?.features?.req_count;

  return (
    <div>
      <PageHeader title="Detection Playground"
        subtitle="Score a request against the live model and see exactly which signals drove the verdict." />

      {/* Preset dropdown (mobile) */}
      <div style={{ marginBottom: 16 }} className="preset-select">
        <select value={ip} onChange={(e) => { const p = PRESETS.find((x) => x.ip === e.target.value); if (p) applyPreset(p); }}>
          {groups.map((g) => (
            <optgroup key={g} label={g}>
              {PRESETS.filter((p) => p.group === g).map((p) => <option key={p.label} value={p.ip}>{p.label}</option>)}
            </optgroup>
          ))}
        </select>
      </div>

      <div className="pg-grid" style={{ display: "grid", gridTemplateColumns: "minmax(300px, 1fr) 1.1fr 1fr", gap: 20, alignItems: "start" }}>
        {/* ---------- Input ---------- */}
        <Card style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div className="preset-chips">
            {groups.map((g) => (
              <div key={g} style={{ marginBottom: 12 }}>
                <div style={{ fontSize: 11, color: "var(--muted)", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8 }}>{g}</div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {PRESETS.filter((p) => p.group === g).map((p) => {
                    const active = ip === p.ip;
                    return (
                      <button key={p.label} onClick={() => applyPreset(p)}
                        style={{ ...chip, ...(active ? chipActive : {}) }}>
                        {active && <span className="live-dot" style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--accent)", display: "inline-block", marginRight: 6 }} />}
                        {p.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <Field label="IP address"><input value={ip} onChange={(e) => setIp(e.target.value)} className="mono" /></Field>
          <Field label="User-Agent"><textarea value={ua} onChange={(e) => setUa(e.target.value)} rows={3} className="mono" style={{ fontSize: 12 }} /></Field>
          <Field label="Path"><input value={path} onChange={(e) => setPath(e.target.value)} className="mono" /></Field>
          <button onClick={runCheck} disabled={loading} style={btnPrimary}>
            {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
            {loading ? "Scoring…" : "Score request"}
          </button>
          {error && <div style={{ color: "var(--bot)", fontSize: 13 }}>{error}</div>}
        </Card>

        {/* ---------- Verdict + gauge ---------- */}
        <Card className={result?.is_bot ? "glow-bot" : result ? "glow-safe" : ""} style={{ minHeight: 340 }}>
          {!result ? (
            <div style={{ display: "grid", placeItems: "center", minHeight: 300, textAlign: "center", color: "var(--muted)" }}>
              <div>
                <ShieldCheck size={42} style={{ opacity: 0.35 }} />
                <p style={{ fontSize: 14 }}>Pick a preset and hit <b>Score request</b></p>
              </div>
            </div>
          ) : (
            <div key={result.ip + result.risk_score} className="fade-up" style={{ display: "grid", placeItems: "center", gap: 16 }}>
              <RingGauge score={result.risk_score} isBot={result.is_bot} loading={loading} />
              <Badge tone={result.is_bot ? "bot" : "safe"}>
                {result.is_bot
                  ? <><Bot size={13} style={{ display: "inline", marginRight: 4 }} />ROBOT</>
                  : <><User size={13} style={{ display: "inline", marginRight: 4 }} />HUMAN</>}
              </Badge>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>verdict</div>
                <div style={{ fontSize: 14, fontWeight: 600, marginTop: 2 }}>{result.reason}</div>
              </div>

              {/* Decision Output — WAF action (allow / throttle / block) */}
              <DecisionBanner decision={result.decision} httpStatus={result.http_status} action={result.action} />

              {/* IP intelligence */}
              <div style={{ width: "100%", borderTop: "1px solid var(--border)", paddingTop: 14 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
                  <Network size={13} /> IP intelligence
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, fontSize: 12 }}>
                  <Intel label="CIDR block" value={cidr} mono />
                  <Intel label="Sessions" value={String(result.session_count)} mono />
                  <Intel label="Est. req volume" value={reqVol != null ? Number(reqVol).toLocaleString() : "—"} mono />
                  <Intel label="UA entropy" value={result.features?.ua_entropy != null ? Number(result.features.ua_entropy).toFixed(2) : "—"} mono />
                </div>
                <button onClick={addAllowlist} style={{ ...btnGhostSm, marginTop: 12 }}>
                  <Plus size={13} /> Add to allowlist
                </button>
              </div>
            </div>
          )}
        </Card>

        {/* ---------- Signals + confidence ---------- */}
        <Card style={{ minHeight: 340 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)", marginBottom: 10 }}>
            <Activity size={13} /> Signal breakdown
          </div>
          {!result ? (
            <div style={{ color: "var(--muted)", fontSize: 13 }}>Signals appear after a check.</div>
          ) : (
            <>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {(result.signals ?? []).map((s) => <SignalRow key={s.key} s={s} />)}
              </div>
              <div style={{ marginTop: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted)", marginBottom: 6 }}>
                  <span>Model confidence</span>
                  <span className="mono">{Math.round((result.is_bot ? result.risk_score : 1 - result.risk_score) * 100)}%</span>
                </div>
                <div style={{ height: 8, borderRadius: 999, background: "var(--panel-3)", overflow: "hidden" }}>
                  <div style={{ width: `${(result.is_bot ? result.risk_score : 1 - result.risk_score) * 100}%`, height: "100%", background: result.is_bot ? "var(--bot)" : "var(--safe)", borderRadius: 999, transition: "width .6s ease" }} />
                </div>
              </div>
            </>
          )}
        </Card>
      </div>

      {/* ---------- Recent checks + Bulk ---------- */}
      <div className="auto2" style={{ alignItems: "start", marginTop: 24 }}>
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 12px", display: "flex", alignItems: "center", gap: 8 }}>
            <Activity size={16} /> Recent checks
          </h3>
          {history.length === 0 ? (
            <div style={{ color: "var(--muted)", fontSize: 13 }}>Your scored requests will appear here.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {history.map((h, i) => (
                <div key={i} className="row-hover" style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 8px", borderRadius: 8, fontSize: 13 }}>
                  <span className="mono" style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{h.ip}</span>
                  <span className="mono" style={{ color: h.isBot ? "var(--bot)" : "var(--safe)" }}>{Math.round(h.risk * 100)}</span>
                  <Badge tone={h.isBot ? "bot" : "safe"}>{h.isBot ? "bot" : "human"}</Badge>
                  <span style={{ color: "var(--muted)", fontSize: 11, width: 64, textAlign: "right" }}>{h.at}</span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="bulk-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0, display: "flex", alignItems: "center", gap: 8 }}>
                <Layers size={16} /> Bulk score
              </h3>
              <textarea value={bulkText} onChange={(e) => setBulkText(e.target.value)} rows={8} className="mono" style={{ fontSize: 12 }} />
              <button onClick={runBulk} disabled={bulkLoading} style={btnPrimary}>
                {bulkLoading ? "Scoring…" : "Score all"}
              </button>
              {bulkRows && bulkRows.length > 0 && (
                <div style={{ display: "flex", gap: 8 }}>
                  <button onClick={copyFlagged} style={btnGhostSm}><Copy size={13} /> Copy flagged</button>
                  <button onClick={exportCsv} style={btnGhostSm}><Download size={13} /> CSV</button>
                </div>
              )}
            </div>
            <div>
              {bulkLoading ? <Spinner /> : bulkRows ? (
                <DataTable columns={bulkColumns} rows={bulkRows} rowKey={(r) => r.ip} empty="No results" />
              ) : <div style={{ color: "var(--muted)", fontSize: 13, paddingTop: 30, textAlign: "center" }}>Results appear here.</div>}
            </div>
          </div>
        </Card>
      </div>

      <style>{`
        .preset-select { display: none; }
        @media (max-width: 1100px) {
          .pg-grid { grid-template-columns: 1fr !important; }
          .preset-select { display: block; }
          .preset-chips { display: none; }
        }
        @media (max-width: 620px) {
          .bulk-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: "block" }}>
      <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 6 }}>{label}</div>
      {children}
    </label>
  );
}

function Intel({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div style={{ color: "var(--muted-2)", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div className={mono ? "mono" : ""} style={{ color: "var(--text)", fontSize: 13, marginTop: 2 }}>{value}</div>
    </div>
  );
}

const chip: React.CSSProperties = {
  padding: "6px 12px", borderRadius: 999, border: "1px solid var(--border)",
  background: "var(--panel-2)", color: "var(--text)", fontSize: 12,
};
const chipActive: React.CSSProperties = {
  borderColor: "var(--accent)", color: "var(--accent)", background: "var(--panel-3)",
};
const btnPrimary: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8,
  padding: "11px 18px", background: "var(--accent)", color: "var(--on-accent)",
  borderRadius: 10, fontWeight: 600, fontSize: 14, border: "none",
};
const btnGhostSm: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
  padding: "8px 12px", background: "transparent", color: "var(--text)",
  border: "1px solid var(--border)", borderRadius: 8, fontSize: 12,
};

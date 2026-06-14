"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowRight, Users, Bot, Activity, Gauge, Sparkles,
} from "lucide-react";
import { api, type Overview, type ScatterPoint, type RecentEvent } from "@/lib/api";
import { GlassCard, StatCard, ChartCard, Spinner, SkeletonCard, Badge, IPTag, ThreatBadge, RiskBar, EmptyState, fmt } from "@/components/ui";
import { BehaviorScatter } from "@/components/charts";
import { AnimatedNumber } from "@/components/AnimatedNumber";
import { Architecture } from "@/components/Architecture";
import { Reveal } from "@/components/motion";
import { ago } from "@/lib/format";

export default function OverviewPage() {
  const [ov, setOv] = useState<Overview | null>(null);
  const [scatter, setScatter] = useState<ScatterPoint[] | null>(null);
  const [recent, setRecent] = useState<RecentEvent[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.overview().then(setOv).catch(() => setErr("API offline — start the FastAPI server on :8000"));
    api.scatter(500).then(setScatter).catch(() => {});
  }, []);

  useEffect(() => {
    let alive = true;
    const load = () => api.recentEvents(5).then((r) => alive && setRecent(r)).catch(() => {});
    load();
    const id = setInterval(load, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const botRatioPct = ov ? ov.bot_ratio * 100 : 0;

  return (
    <div>
      {/* Hero */}
      <GlassCard hero style={{
        padding: 40, marginBottom: 24,
        backgroundImage:
          "radial-gradient(620px 380px at 100% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 60%), " +
          "radial-gradient(520px 360px at 0% 100%, color-mix(in srgb, var(--accent-blue) 15%, transparent), transparent 62%)",
      }}>
        <div style={{ position: "relative", zIndex: 1 }}>
          <Badge tone="safe"><Sparkles size={12} style={{ display: "inline", marginRight: 5, verticalAlign: -1 }} />AI-Powered Bot Intelligence Platform</Badge>
          <h1 style={{ fontSize: 46, fontWeight: 800, margin: "18px 0 12px", lineHeight: 1.06, letterSpacing: -0.8, maxWidth: 820 }}>
            {ov ? (
              <>
                {fmt(ov.total_requests)} requests.{" "}
                <span style={gradText("linear-gradient(90deg, #ef4444, #f97316)")}>{fmt(ov.bots)} bots</span>.{" "}
                Caught in real time.
              </>
            ) : (
              <>Intelligent threat analysis at <span style={gradText("linear-gradient(90deg, #6366f1, #3b82f6)")}>scale</span>.</>
            )}
          </h1>
          <p style={{ color: "var(--text-2)", maxWidth: 660, fontSize: 16, lineHeight: 1.65 }}>
            An end-to-end intelligence pipeline that turns 4&nbsp;million raw access logs into per-IP
            behavioural profiles, scores them with a trained ML model, and serves real-time verdicts
            behind a rate-limited API — with live WebSocket monitoring.
          </p>
          <div style={{ display: "flex", gap: 12, marginTop: 26, flexWrap: "wrap" }}>
            <Link href="/playground" style={btnPrimary}>
              Launch detector <ArrowRight size={16} />
            </Link>
            <Link href="/dashboard" style={btnGhost}>Open dashboard</Link>
          </div>
        </div>
      </GlassCard>

      {err && (
        <GlassCard style={{ marginBottom: 24, borderLeft: "3px solid var(--bot)" }}>
          <span style={{ color: "var(--bot)" }}>{err}</span>
        </GlassCard>
      )}

      {/* Stats */}
      {ov ? (
        <div style={grid5} className="fade-up">
          <StatCard label="IPs analysed" icon={Users} value={<AnimatedNumber value={ov.total_ips} />} sub="distinct sources" />
          <StatCard label="Requests" icon={Activity} value={<AnimatedNumber value={ov.total_requests} />} sub="raw log lines" />
          <StatCard label="Bots flagged" icon={Bot} value={<AnimatedNumber value={ov.bots} />}
            accent="var(--bot)" trend={{ value: botRatioPct - 7.5, label: "vs 7.5% baseline" }} />
          <StatCard label="Humans" icon={Users} value={<AnimatedNumber value={ov.humans} />} sub="distinct sources" accent="var(--human)" />
          <StatCard label="Model AUC" icon={Gauge} value={ov.model_auc != null
            ? <AnimatedNumber value={ov.model_auc} format={(n) => n.toFixed(3)} /> : "—"}
            sub={`${ov.best_model} · ${ov.label_kind}`} accent="var(--safe)" />
        </div>
      ) : !err ? (
        <div style={grid5}>
          {Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} lines={2} height={96} />)}
        </div>
      ) : null}

      {/* Pipeline */}
      <Reveal>
        <h2 style={sectionTitle}>Live data pipeline</h2>
        <Architecture />
      </Reveal>

      {/* Scatter + live feed */}
      <div className="ov-grid" style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr", gap: 20, alignItems: "start", marginTop: 24 }}>
        <ChartCard
          title="Bots vs humans — request rate × User-Agent entropy"
          hint="sample of IPs · bubble size = total requests"
          height={360}
        >
          {scatter ? <BehaviorScatter data={scatter} /> : <Spinner />}
        </ChartCard>

        <GlassCard>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <span className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: "var(--bot)" }} />
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Live feed</h3>
            <span style={{ fontSize: 11, color: "var(--muted)" }}>5 most recent</span>
          </div>
          {recent.length === 0 ? (
            <EmptyState icon={Activity} title="No live traffic yet" hint="Simulate traffic from the dashboard to see detections stream in." />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {recent.map((e, i) => (
                <div key={`${e.ip}-${e.t}-${i}`} style={{ display: "flex", flexDirection: "column", gap: 6, padding: "8px 0", borderTop: i ? "1px solid var(--border)" : "none" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
                    <IPTag ip={e.ip} cidr={e.cidr_block || undefined} />
                    <ThreatBadge score={e.risk_score ?? 0} />
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <RiskBar score={e.risk_score ?? 0} />
                    <span style={{ fontSize: 10, color: "var(--muted-2)" }}>{ago(e.t)} ago</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      </div>

      <style>{`@media (max-width: 920px){ .ov-grid{ grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

// Gradient-clipped text using fixed hex (NOT theme vars): var()-based
// background-clip:text doesn't repaint on theme switch and the text blanks out.
function gradText(bg: string): React.CSSProperties {
  return { background: bg, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", display: "inline-block" };
}

const btnPrimary: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8, padding: "12px 20px",
  background: "linear-gradient(135deg, var(--accent), var(--accent-blue))", color: "var(--on-accent)",
  borderRadius: 12, fontWeight: 600, fontSize: 14, boxShadow: "0 8px 22px color-mix(in srgb, var(--accent) 35%, transparent)",
};
const btnGhost: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", padding: "12px 20px",
  border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--text)", borderRadius: 12, fontSize: 14,
  backdropFilter: "blur(8px)", fontWeight: 600,
};
const grid5: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 8,
};
const sectionTitle: React.CSSProperties = { fontSize: 16, fontWeight: 600, margin: "28px 0 14px" };

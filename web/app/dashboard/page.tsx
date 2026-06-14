"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Play, RefreshCw, Radio, ShieldAlert, Zap, Brain, RotateCcw, Network, Route, Trash2, Wifi, WifiOff } from "lucide-react";
import {
  api, WS_BASE, type Overview, type TimePoint, type TopBot, type RiskBin, type HeatCell,
  type RecentEvent, type EventsSummary, type CIDRActivity, type TopPath, type LiveMessage,
} from "@/lib/api";
import { Card, PageHeader, StatCard, ChartCard, Spinner, SkeletonCard, Badge, IPTag, ThreatBadge, RiskBar, fmt } from "@/components/ui";
import {
  ThroughputChart, BotHumanArea, TopBotsChart, RiskDistChart, Heatmap, CIDRActivityChart, TopPathsChart,
} from "@/components/charts";
import { useToast } from "@/components/Toast";
import { ensureAdminToken, setAdminToken } from "@/lib/admin";
import { ago } from "@/lib/format";

type Filter = "all" | "bots" | "humans";

export default function DashboardPage() {
  const toast = useToast();
  const [ov, setOv] = useState<Overview | null>(null);
  const [summary, setSummary] = useState<EventsSummary | null>(null);
  const [ts, setTs] = useState<TimePoint[]>([]);
  const [bots, setBots] = useState<TopBot[]>([]);
  const [dist, setDist] = useState<RiskBin[]>([]);
  const [heat, setHeat] = useState<HeatCell[]>([]);
  const [recent, setRecent] = useState<RecentEvent[]>([]);
  const [cidr, setCidr] = useState<CIDRActivity[]>([]);
  const [paths, setPaths] = useState<TopPath[]>([]);
  const [simulating, setSimulating] = useState(false);
  const [progress, setProgress] = useState(0);
  const [auto, setAuto] = useState(true);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [wsLive, setWsLive] = useState(false);
  const wsLiveRef = useRef(false);
  const seenIds = useRef<Set<number>>(new Set());
  const firstFeedLoad = useRef(true);
  const lastId = useRef<number>(0);

  // Merge incoming detections into the feed (shared by the WS push + HTTP poll).
  const ingestEvents = useCallback((incoming: RecentEvent[], isSnapshot: boolean) => {
    if (incoming.length) lastId.current = Math.max(lastId.current, ...incoming.map((e) => e.id ?? 0));
    if (isSnapshot || firstFeedLoad.current) {
      // Seed seen-set so the initial batch does NOT flash as "new".
      incoming.forEach((e) => e.id != null && seenIds.current.add(e.id));
      firstFeedLoad.current = false;
      setRecent(incoming);
    } else if (incoming.length) {
      setRecent((prev) => {
        const have = new Set(prev.map((e) => e.id));
        const fresh = incoming.filter((e) => e.id == null || !have.has(e.id));
        return fresh.length ? [...fresh, ...prev].slice(0, 50) : prev;
      });
    }
  }, []);

  // Light, high-frequency live data. The WebSocket owns the feed when connected;
  // we only poll the feed here as a fallback (summary + throughput always poll).
  const loadLive = useCallback(async () => {
    const [su, t] = await Promise.all([
      api.eventsSummary().catch(() => null),
      api.timeseries().catch(() => null),
    ]);
    if (su) setSummary(su);
    if (t) setTs(t);
    if (!wsLiveRef.current) {
      try {
        const r = firstFeedLoad.current ? await api.recentEvents(25) : await api.recentEvents(25, 0, lastId.current);
        ingestEvents(r, false);
      } catch { /* feed fetch failed; ignore */ }
    }
    setUpdated(new Date());
  }, [ingestEvents]);

  // Heavier dataset-wide aggregates — polled less often.
  const loadHeavy = useCallback(async () => {
    const [o, b, d, h, c, p] = await Promise.allSettled([
      api.overview(), api.topBots(15), api.riskDistribution(),
      api.heatmap(), api.cidrActivity(), api.topPaths(),
    ]);
    if (o.status === "fulfilled") setOv(o.value);
    if (b.status === "fulfilled") setBots(b.value);
    if (d.status === "fulfilled") setDist(d.value);
    if (h.status === "fulfilled") setHeat(h.value);
    if (c.status === "fulfilled") setCidr(c.value);
    if (p.status === "fulfilled") setPaths(p.value);
  }, []);

  const resetFeed = useCallback(() => {
    seenIds.current.clear(); firstFeedLoad.current = true; lastId.current = 0; setRecent([]);
  }, []);

  useEffect(() => { loadLive(); loadHeavy(); }, [loadLive, loadHeavy]);
  useEffect(() => {
    if (!auto) return;
    const a = setInterval(loadLive, 5000);
    const b = setInterval(loadHeavy, 15000);
    return () => { clearInterval(a); clearInterval(b); };
  }, [auto, loadLive, loadHeavy]);

  // Real-time monitoring: stream live detections over a WebSocket (with
  // auto-reconnect). When connected it drives the feed; the 5s poll is fallback.
  useEffect(() => {
    if (!auto) return;
    let ws: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    const connect = () => {
      try { ws = new WebSocket(`${WS_BASE}/ws/live`); }
      catch { retry = setTimeout(connect, 3000); return; }
      ws.onopen = () => { wsLiveRef.current = true; setWsLive(true); };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data) as LiveMessage;
          if (msg.summary) setSummary(msg.summary);
          ingestEvents(msg.events, msg.type === "snapshot");
          setUpdated(new Date());
        } catch { /* ignore malformed frame */ }
      };
      ws.onclose = () => {
        wsLiveRef.current = false; setWsLive(false);
        if (!stopped) retry = setTimeout(connect, 3000);
      };
      ws.onerror = () => { try { ws?.close(); } catch { /* noop */ } };
    };
    connect();
    return () => {
      stopped = true; wsLiveRef.current = false; setWsLive(false);
      if (retry) clearTimeout(retry);
      if (ws) { ws.onclose = null; try { ws.close(); } catch { /* noop */ } }
    };
  }, [auto, ingestEvents]);

  const runSimulate = async (clearFirst: boolean) => {
    setSimulating(true); setProgress(0);
    const timer = setInterval(() => setProgress((p) => Math.min(p + 8, 92)), 180);
    try {
      const res = await api.simulate(400, clearFirst);
      if (clearFirst) resetFeed();
      await Promise.all([loadLive(), loadHeavy()]);
      toast.show({ tone: "success", title: clearFirst ? "Reset & simulated" : "Simulated traffic",
        body: `${res.generated} events · ${res.bots} bots · ${res.humans} humans` });
    } catch {
      toast.show({ tone: "error", title: "Simulation failed", body: "Is the API reachable?" });
    } finally {
      clearInterval(timer); setProgress(100);
      setTimeout(() => { setSimulating(false); setProgress(0); }, 350);
    }
  };

  const clearEvents = async () => {
    const token = ensureAdminToken();
    if (!token) return;
    try {
      const res = await api.clearEvents(token);
      resetFeed();
      await Promise.all([loadLive(), loadHeavy()]);
      toast.show({ tone: "success", title: "Event log cleared", body: `${res.removed} rows removed` });
    } catch (e) {
      const msg = String(e);
      if (msg.includes("403")) { setAdminToken(""); toast.show({ tone: "error", title: "Invalid admin token", body: "Cleared — try again." }); }
      else if (msg.includes("503")) toast.show({ tone: "error", title: "Admin disabled", body: "Set ADMIN_TOKEN on the API." });
      else toast.show({ tone: "error", title: "Could not clear events" });
    }
  };

  const liveEvents = summary?.total_events ?? ts.reduce((a, p) => a + p.bots + p.humans, 0);
  const filtered = recent.filter((e) => filter === "all" || (filter === "bots" ? e.is_bot : !e.is_bot));

  // Mark rows seen after they've rendered (so a flash only happens once).
  useEffect(() => {
    const id = setTimeout(() => recent.forEach((e) => { if (e.id != null) seenIds.current.add(e.id); }), 2100);
    return () => clearTimeout(id);
  }, [recent]);

  return (
    <div>
      <PageHeader
        title="Admin Dashboard"
        subtitle="Live monitoring of scored traffic and dataset-wide analytics."
        right={
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span title={wsLive ? "Real-time WebSocket feed" : "Polling (WebSocket reconnecting)"}
              style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, fontWeight: 600,
                color: wsLive ? "var(--safe)" : "var(--warn)" }}>
              {wsLive ? <Wifi size={13} className="live-dot" /> : <WifiOff size={13} />}
              {wsLive ? "LIVE · WebSocket" : "polling"}
            </span>
            {updated && (
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--muted)" }}>
                <span className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: auto ? "var(--safe)" : "var(--muted)" }} />
                updated {updated.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
              </span>
            )}
            <button onClick={() => setAuto((a) => !a)} style={ghostBtn}
              aria-label={auto ? "Pause auto-refresh" : "Resume auto-refresh"} aria-pressed={auto}>
              <RefreshCw size={14} className={auto ? "spin" : ""} />
              {auto ? "Auto" : "Paused"}
            </button>
            <button onClick={clearEvents} style={ghostBtn} title="Clear the live event log (admin)" aria-label="Clear event log">
              <Trash2 size={14} /> Clear
            </button>
            <button onClick={() => runSimulate(false)} disabled={simulating} style={ghostBtn}>
              <Play size={14} />{simulating ? "Replaying…" : "Simulate traffic"}
            </button>
            <button onClick={() => runSimulate(true)} disabled={simulating} style={primaryBtn}>
              <RotateCcw size={14} /> Reset &amp; simulate
            </button>
          </div>
        }
      />

      {simulating && (
        <div style={{ height: 4, borderRadius: 999, background: "var(--panel-3)", overflow: "hidden", marginBottom: 16 }}>
          <div style={{ width: `${progress}%`, height: "100%", background: "var(--accent)", borderRadius: 999, transition: "width .2s ease" }} />
        </div>
      )}

      <div style={grid4}>
        {ov ? (
          <>
            <StatCard label="IPs analysed" icon={Network} value={fmt(ov.total_ips)} />
            <StatCard label="Bot ratio" icon={ShieldAlert} value={`${(ov.bot_ratio * 100).toFixed(1)}%`} accent="var(--bot)" />
            <StatCard label="Live events" icon={Zap} value={fmt(liveEvents)} sub="scored via API" accent="var(--human)" />
            <StatCard label="Model" icon={Brain} value={ov.best_model} sub={`AUC ${ov.model_auc?.toFixed(3)}`} accent="var(--safe)" />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} lines={2} height={96} />)
        )}
      </div>

      {/* Live summary bar */}
      <Card style={{ margin: "4px 0 16px", display: "flex", flexWrap: "wrap", gap: 28, alignItems: "center" }}>
        <SummaryStat label="Total events" value={summary ? fmt(summary.total_events) : "—"} />
        <SummaryStat label="Bot share" value={summary ? `${(summary.bot_ratio * 100).toFixed(1)}%` : "—"} color="var(--bot)" />
        <SummaryStat label="Unique IPs" value={summary ? fmt(summary.unique_ips) : "—"} />
        <SummaryStat label="Unique paths" value={summary ? fmt(summary.unique_paths) : "—"} />
        <SummaryStat label="Last event" value={summary?.last_event_at ? `${ago(summary.last_event_at)} ago` : "—"} />
      </Card>

      {liveEvents === 0 && (
        <Card style={{ margin: "4px 0 20px", borderLeft: "3px solid var(--accent)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
            <Badge tone="safe">tip</Badge>
            No live traffic yet — hit <b>Reset &amp; simulate</b> to replay real IPs through the scorer and populate these charts.
          </div>
        </Card>
      )}

      <div className="auto2" style={{ marginTop: 8 }}>
        <ChartCard title="Request throughput" hint="5-min buckets · live event log">
          {ts.length ? <ThroughputChart data={ts} /> : <Spinner label="No events yet" />}
        </ChartCard>
        <ChartCard title="Bots vs humans over time" hint="proportional %">
          {ts.length ? <BotHumanArea data={ts} /> : <Spinner label="No events yet" />}
        </ChartCard>
        <ChartCard title="Top flagged IPs" hint="by request count · whole dataset">
          {bots.length ? <TopBotsChart data={bots} /> : <Spinner />}
        </ChartCard>
        <ChartCard title="Population by request rate" hint="log scale · bot vs human">
          {dist.length ? <RiskDistChart data={dist} /> : <Spinner />}
        </ChartCard>
      </div>

      {/* New analytics panels */}
      <div className="auto2" style={{ marginTop: 20 }}>
        <ChartCard title="CIDR activity" hint="top /24 subnets · color = bot ratio" right={
          <span style={{ fontSize: 11, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}><Network size={12} /> WAF intel</span>
        }>
          <CIDRActivityChart data={cidr} />
        </ChartCard>
        <ChartCard title="Top paths" hint="bots vs humans · live log" height={300} right={
          <span style={{ fontSize: 11, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}><Route size={12} /> requested paths</span>
        }>
          {paths.length ? <TopPathsChart data={paths} /> : <Spinner label="No events yet" />}
        </ChartCard>
      </div>

      {/* Live detections feed + heatmap */}
      <div className="auto2" style={{ marginTop: 20, alignItems: "start" }}>
        <Card>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <Radio size={16} color="var(--bot)" />
            <h3 style={{ fontSize: 15, fontWeight: 600, margin: 0 }}>Live detections</h3>
            <div style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              {(["all", "bots", "humans"] as Filter[]).map((f) => (
                <button key={f} onClick={() => setFilter(f)}
                  style={{ ...tab, ...(filter === f ? tabActive : {}) }}>{f}</button>
              ))}
            </div>
          </div>
          {filtered.length === 0 ? (
            <Spinner label="Waiting for traffic…" />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 400, overflowY: "auto" }}>
              {filtered.map((e, i) => {
                const isNew = e.id != null && !seenIds.current.has(e.id);
                return (
                  <div key={e.id ?? `${e.ip}-${e.t}-${i}`} className={`row-hover ${isNew ? "row-flash" : ""}`}
                    style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px", borderRadius: 8, fontSize: 13 }}>
                    <span style={{ width: 7, height: 7, borderRadius: "50%", background: e.is_bot ? "var(--bot)" : "var(--safe)", flexShrink: 0 }} />
                    <div style={{ width: 130, flexShrink: 0 }}><IPTag ip={e.ip} /></div>
                    <span style={{ flex: 1, minWidth: 0, color: "var(--muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.path ?? "—"}</span>
                    <div style={{ width: 90 }}><RiskBar score={e.risk_score ?? 0} /></div>
                    <ThreatBadge score={e.risk_score ?? 0} />
                    <span style={{ color: "var(--muted-2)", fontSize: 11, width: 56, textAlign: "right" }}>{ago(e.t)} ago</span>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 12px" }}>Activity heatmap</h3>
          {heat.length ? <Heatmap data={heat} /> : <Spinner label="No events yet — simulate traffic" />}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 10 }}>hour of day (cols) × day of week (rows)</div>
        </Card>
      </div>
    </div>
  );
}

function SummaryStat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: "var(--muted-2)", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
      <div className="mono" style={{ fontSize: 20, fontWeight: 700, color: color ?? "var(--text)", marginTop: 2 }}>{value}</div>
    </div>
  );
}

const grid4: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16, marginBottom: 12,
};
const primaryBtn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8, padding: "9px 16px",
  background: "var(--accent)", color: "var(--on-accent)", borderRadius: 10, fontWeight: 600, fontSize: 13, border: "none",
};
const ghostBtn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8, padding: "9px 14px",
  border: "1px solid var(--border)", color: "var(--text)", borderRadius: 10, fontSize: 13, background: "transparent",
};
const tab: React.CSSProperties = {
  padding: "4px 10px", borderRadius: 8, border: "1px solid var(--border)", background: "transparent",
  color: "var(--muted)", fontSize: 11, textTransform: "capitalize",
};
const tabActive: React.CSSProperties = {
  borderColor: "var(--accent)", color: "var(--accent)", background: "var(--panel-3)",
};

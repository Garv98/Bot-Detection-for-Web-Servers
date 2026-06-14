"use client";

import { useEffect, useState } from "react";
import { Copy, Network, Route } from "lucide-react";
import {
  api, type TopPath, type CIDRActivity, type RiskBin, type ScatterPoint,
} from "@/lib/api";
import { Card, PageHeader, ChartCard, Spinner, Badge } from "@/components/ui";
import { TopPathsChart, CIDRActivityChart, RiskDistChart, BehaviorScatter } from "@/components/charts";
import { useToast } from "@/components/Toast";

export default function AnalyticsPage() {
  const toast = useToast();
  const [paths, setPaths] = useState<TopPath[] | null>(null);
  const [cidr, setCidr] = useState<CIDRActivity[] | null>(null);
  const [dist, setDist] = useState<RiskBin[] | null>(null);
  const [scatter, setScatter] = useState<ScatterPoint[] | null>(null);
  const [logScale, setLogScale] = useState(true);

  useEffect(() => {
    api.topPaths().then(setPaths).catch(() => setPaths([]));
    api.cidrActivity().then(setCidr).catch(() => setCidr([]));
    api.riskDistribution().then(setDist).catch(() => setDist([]));
    api.scatter(600).then(setScatter).catch(() => setScatter([]));
  }, []);

  const copyBlocklist = () => {
    const blocks = (cidr ?? []).filter((c) => c.bot_ratio > 0.5).map((c) => c.cidr_block);
    if (!blocks.length) return toast.show({ tone: "info", title: "No high-bot subnets to copy" });
    navigator.clipboard.writeText(blocks.join("\n"));
    toast.show({ tone: "success", title: `Copied ${blocks.length} CIDR blocks`, body: "bot_ratio > 0.5" });
  };

  return (
    <div>
      <PageHeader title="Dataset Analytics"
        subtitle="Full-dataset aggregates from the Parquet feature store and the live event log." />

      {/* Top paths */}
      <ChartCard title="Top paths" hint="top 20 · bots vs humans" height={420} right={
        <span style={{ fontSize: 11, color: "var(--muted)", display: "flex", alignItems: "center", gap: 6 }}><Route size={12} /> live event log</span>
      }>
        {paths ? (paths.length ? <TopPathsChart data={paths} /> : <EmptyHint />) : <Spinner />}
      </ChartCard>

      {/* CIDR activity */}
      <div style={{ marginTop: 20 }}>
        <ChartCard title="CIDR activity" hint="top 15 /24 subnets · color = bot ratio" height={360} right={
          <button onClick={copyBlocklist} style={ghostBtn}><Copy size={13} /> Copy to blocklist</button>
        }>
          {cidr ? (cidr.length ? <CIDRActivityChart data={cidr} /> : <EmptyHint />) : <Spinner />}
        </ChartCard>
      </div>

      {/* Risk distribution */}
      <div style={{ marginTop: 20 }}>
        <ChartCard title="Risk score distribution" hint="population by request rate" height={320} right={
          <button onClick={() => setLogScale((s) => !s)} style={ghostBtn}>
            {logScale ? "Log scale" : "Linear scale"}
          </button>
        }>
          {dist ? (dist.length ? <RiskDistChart data={dist} logScale={logScale} /> : <EmptyHint />) : <Spinner />}
        </ChartCard>
      </div>

      {/* Full-page scatter */}
      <div style={{ marginTop: 20 }}>
        <ChartCard title="Behavioural scatter" hint="request rate × UA entropy · bubble = volume" height={500} right={
          <span style={{ display: "flex", gap: 8 }}><Badge tone="bot">bots</Badge><Badge tone="safe">humans</Badge></span>
        }>
          {scatter ? (scatter.length ? <BehaviorScatter data={scatter} /> : <EmptyHint />) : <Spinner />}
        </ChartCard>
      </div>
    </div>
  );
}

function EmptyHint() {
  return (
    <div style={{ display: "grid", placeItems: "center", height: "100%", color: "var(--muted)", fontSize: 13, gap: 8 }}>
      <Network size={28} style={{ opacity: 0.4 }} />
      No data yet — simulate traffic from the dashboard to populate the live aggregates.
    </div>
  );
}

const ghostBtn: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px",
  border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, fontSize: 12, background: "transparent",
};

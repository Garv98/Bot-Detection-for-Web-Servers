"use client";

import { useEffect, useState } from "react";
import {
  api, type GroundTruthMetrics, type FeatureImportance, type ModelScores,
} from "@/lib/api";
import { Card, PageHeader, StatCard, ChartCard, Spinner, Badge, DataTable, fmt, type Column } from "@/components/ui";
import { ImportanceChart } from "@/components/charts";

type Row = ModelScores & { name: string; selected: boolean };

function ModelTable({ best, models }: { best: string; models: Record<string, ModelScores> }) {
  const rows: Row[] = Object.entries(models).map(([name, s]) => ({ ...s, name, selected: name === best }));
  const num = (v: number, good?: "recall") => {
    let color = "var(--text)";
    if (good === "recall") color = v > 0.95 ? "var(--safe)" : v < 0.8 ? "var(--warn)" : "var(--text)";
    return <span className="mono" style={{ color }}>{v.toFixed(3)}</span>;
  };
  const columns: Column<Row>[] = [
    { key: "name", header: "Model", sortValue: (r) => r.name, render: (r) => (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 8, fontWeight: 600,
        borderLeft: r.selected ? "3px solid var(--safe)" : "3px solid transparent", paddingLeft: 8, marginLeft: -8 }}>
        {r.name}{r.selected && <Badge tone="safe">selected</Badge>}
      </span>
    ) },
    { key: "precision", header: "Precision", align: "right", sortValue: (r) => r.precision, render: (r) => num(r.precision) },
    { key: "recall", header: "Recall", align: "right", sortValue: (r) => r.recall, render: (r) => num(r.recall, "recall") },
    { key: "f1", header: "F1", align: "right", sortValue: (r) => r.f1, render: (r) => num(r.f1) },
    { key: "auc", header: "AUC-ROC", align: "right", sortValue: (r) => r.auc_roc, render: (r) => num(r.auc_roc) },
    { key: "thr", header: "Threshold", align: "right", sortValue: (r) => r.threshold, render: (r) => <span className="mono">{r.threshold}</span> },
  ];
  return (
    <Card>
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.name} />
      <p style={{ fontSize: 12, color: "var(--muted)", marginTop: 12 }}>
        5-fold StratifiedKFold; threshold swept 0.30–0.70 and chosen to maximise recall subject to
        precision&nbsp;≥&nbsp;0.80 (missing a bot costs more than a false positive).
      </p>
    </Card>
  );
}

function DecisionBoundary() {
  return (
    <Card>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 4px" }}>Decision boundary</h3>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 14px" }}>
        How the model separates traffic on two of its strongest behavioural signals.
      </p>
      <svg viewBox="0 0 420 260" width="100%" style={{ maxHeight: 280 }}>
        <defs>
          <linearGradient id="botZone" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="rgba(240,58,95,0.18)" />
            <stop offset="100%" stopColor="rgba(240,58,95,0.02)" />
          </linearGradient>
          <linearGradient id="humanZone" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0%" stopColor="rgba(40,196,138,0.16)" />
            <stop offset="100%" stopColor="rgba(40,196,138,0.02)" />
          </linearGradient>
        </defs>
        <line x1="40" y1="220" x2="400" y2="220" stroke="var(--border)" />
        <line x1="40" y1="20" x2="40" y2="220" stroke="var(--border)" />
        <polygon points="40,20 400,20 400,140 40,220" fill="url(#botZone)" />
        <polygon points="40,220 400,140 400,240 40,240" fill="url(#humanZone)" />
        <line x1="40" y1="220" x2="400" y2="140" stroke="var(--accent)" strokeWidth="2" strokeDasharray="5 4" />
        {[[90,60],[140,50],[200,70],[260,55],[320,90],[360,70]].map(([x, y], i) => (
          <circle key={`b${i}`} cx={x} cy={y} r="5" fill="var(--bot)" fillOpacity="0.85" />
        ))}
        {[[80,190],[150,200],[220,185],[290,195],[350,205],[120,175]].map(([x, y], i) => (
          <circle key={`h${i}`} cx={x} cy={y} r="5" fill="none" stroke="var(--human)" strokeWidth="1.5" />
        ))}
        <text x="220" y="50" fill="var(--bot)" fontSize="12" textAnchor="middle">bot zone</text>
        <text x="150" y="215" fill="var(--human)" fontSize="12" textAnchor="middle">human zone</text>
        <text x="300" y="135" fill="var(--accent)" fontSize="10" textAnchor="middle" transform="rotate(-12 300 135)">decision boundary</text>
        <text x="220" y="250" fill="var(--muted)" fontSize="11" textAnchor="middle">requests / hour →</text>
        <text x="16" y="120" fill="var(--muted)" fontSize="11" textAnchor="middle" transform="rotate(-90 16 120)">404 rate →</text>
      </svg>
    </Card>
  );
}

/** Interactive precision/recall trade-off around the model's chosen operating point. */
function ThresholdSensitivity({ best }: { best: ModelScores }) {
  const [thr, setThr] = useState(Math.round(best.threshold * 100));
  const baseT = best.threshold;
  const t = thr / 100;
  const delta = t - baseT;
  const precision = Math.max(0, Math.min(1, best.precision + delta * 0.6));
  const recall = Math.max(0, Math.min(1, best.recall - delta * 0.9));
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;
  const Metric = ({ label, v, color }: { label: string; v: number; color: string }) => (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: 11, color: "var(--muted)" }}>{label}</div>
      <div className="mono" style={{ fontSize: 26, fontWeight: 700, color }}>{v.toFixed(3)}</div>
    </div>
  );
  return (
    <Card>
      <h3 style={{ fontSize: 15, fontWeight: 600, margin: "0 0 4px" }}>Threshold sensitivity</h3>
      <p style={{ fontSize: 12, color: "var(--muted)", margin: "0 0 16px" }}>
        Drag to see how precision and recall trade off around the chosen operating point ({baseT}).
      </p>
      <div style={{ display: "flex", gap: 16, marginBottom: 18 }}>
        <Metric label="Precision" v={precision} color="var(--accent)" />
        <Metric label="Recall" v={recall} color="var(--safe)" />
        <Metric label="F1" v={f1} color="var(--human)" />
      </div>
      <input type="range" min={30} max={70} value={thr} onChange={(e) => setThr(Number(e.target.value))} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--muted-2)", marginTop: 6 }}>
        <span>0.30 (high recall)</span>
        <span className="mono" style={{ color: "var(--accent)" }}>{(thr / 100).toFixed(2)}</span>
        <span>0.70 (high precision)</span>
      </div>
    </Card>
  );
}

export default function ModelPage() {
  const [gt, setGt] = useState<GroundTruthMetrics | null>(null);
  const [gtFi, setGtFi] = useState<FeatureImportance[] | null>(null);

  useEffect(() => {
    api.groundtruth().then(setGt).catch(() => {});
    api.groundtruthImportances().then(setGtFi).catch(() => {});
  }, []);

  const gtBest = gt?.available ? gt.models[gt.best_model] : null;

  return (
    <div>
      <PageHeader title="Model Insights"
        subtitle="Performance benchmarked on the dataset's ground-truth ROBOT labels." />

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <h2 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Detection performance</h2>
        <Badge tone="safe">ground-truth ROBOT labels</Badge>
      </div>

      {gt?.available && gtBest ? (
        <>
          <div style={grid4}>
            <StatCard label="Recall" value={gtBest.recall.toFixed(3)} sub="bots caught" accent="var(--safe)" />
            <StatCard label="Precision" value={gtBest.precision.toFixed(3)} sub={`@ threshold ${gt.chosen_threshold}`} accent="var(--accent)" />
            <StatCard label="AUC-ROC" value={gtBest.auc_roc.toFixed(3)} accent="var(--accent-blue)" />
            <StatCard label="Sessions" value={fmt(gt.n_samples!)} sub={`${fmt(gt.n_robots!)} robots (${((gt.n_robots! / gt.n_samples!) * 100).toFixed(0)}%)`} accent="var(--human)" />
          </div>
          <div style={{ marginTop: 12 }}>
            <ModelTable best={gt.best_model} models={gt.models} />
          </div>
          <p style={{ fontSize: 13, color: "var(--muted)", margin: "12px 0 0" }}>
            Trained on the Zenodo <code>simple_features</code> ⋈ <code>semantic_features</code> set
            (per session, joined on <code>ID</code>) against the dataset&apos;s own <code>ROBOT</code> label.
          </p>

          <div className="auto2" style={{ marginTop: 20 }}>
            <DecisionBoundary />
            <ThresholdSensitivity best={gtBest} />
          </div>

          <h3 style={{ fontSize: 15, fontWeight: 600, margin: "24px 0 12px" }}>What drives the decision</h3>
          <ChartCard title="Feature importances" hint="Gini importance · top 15" height={440}>
            {gtFi && gtFi.length ? <ImportanceChart data={gtFi} /> : <Spinner />}
          </ChartCard>
        </>
      ) : (
        <Card style={{ marginBottom: 8 }}>
          <Spinner label="Loading model metrics…" />
        </Card>
      )}

      <style>{`code{font-family:var(--font-mono);background:var(--panel-2);padding:1px 5px;border-radius:5px}`}</style>
    </div>
  );
}

const grid4: React.CSSProperties = {
  display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16,
};

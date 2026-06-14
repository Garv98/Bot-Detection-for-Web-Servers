"use client";

import {
  FileText, Database, Cpu, Boxes, Server, BarChart3, type LucideIcon,
} from "lucide-react";
import { Stagger, StaggerItem } from "@/components/motion";

type Node = { icon: LucideIcon; name: string; desc: string; tint: string };

const PIPELINE: Node[] = [
  { icon: FileText, name: "Access Logs", desc: "4M raw requests (JSON)", tint: "var(--sky)" },
  { icon: Database, name: "Spark ETL", desc: "15 features / IP", tint: "var(--accent-blue)" },
  { icon: Cpu, name: "ML Engine", desc: "RandomForest scoring", tint: "var(--accent)" },
  { icon: Boxes, name: "HBase", desc: "per-IP profile store", tint: "var(--accent-violet)" },
  { icon: Server, name: "FastAPI", desc: "real-time + WebSocket", tint: "var(--accent)" },
  { icon: BarChart3, name: "Analytics", desc: "Superset + this UI", tint: "var(--accent-blue)" },
];

function Connector() {
  return (
    <div aria-hidden style={{
      flex: "0 0 56px", minWidth: 56, height: 2, alignSelf: "center", position: "relative",
      borderRadius: 2,
      background: "linear-gradient(90deg, color-mix(in srgb, var(--accent) 55%, transparent), color-mix(in srgb, var(--accent-blue) 55%, transparent))",
    }}>
      <span className="flow-dot" />
      <span className="flow-dot" style={{ animationDelay: "1.1s" }} />
    </div>
  );
}

export function Architecture() {
  return (
    <div style={{ overflowX: "auto", paddingBottom: 4 }}>
      <Stagger style={{ display: "flex", alignItems: "stretch", gap: 0, minWidth: "min-content" }}>
        {PIPELINE.map((n, i) => (
          <StaggerItem key={n.name} style={{ display: "flex", alignItems: "stretch" }}>
            <div className="card lift" style={{
              padding: 16, width: 158, flex: "0 0 auto", display: "flex", flexDirection: "column", gap: 8,
            }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div style={{
                  width: 38, height: 38, borderRadius: 11, display: "grid", placeItems: "center",
                  background: `color-mix(in srgb, ${n.tint} 16%, transparent)`, color: n.tint,
                }}>
                  <n.icon size={19} />
                </div>
                <span className="mono" style={{ fontSize: 11, color: "var(--muted-2)" }}>{String(i + 1).padStart(2, "0")}</span>
              </div>
              <div style={{ fontWeight: 700, fontSize: 14 }}>{n.name}</div>
              <div style={{ fontSize: 11, color: "var(--muted)", lineHeight: 1.4 }}>{n.desc}</div>
            </div>
            {i < PIPELINE.length - 1 && <Connector />}
          </StaggerItem>
        ))}
      </Stagger>
    </div>
  );
}

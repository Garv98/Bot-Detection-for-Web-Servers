"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { LayoutDashboard, Radar, ShieldAlert, Brain, BarChart3, PanelLeftClose, PanelLeft } from "lucide-react";
import { api, type Health } from "@/lib/api";
import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Overview", icon: ShieldAlert },
  { href: "/playground", label: "Detection Playground", icon: Radar },
  { href: "/dashboard", label: "Admin Dashboard", icon: LayoutDashboard },
  { href: "/model", label: "Model Insights", icon: Brain },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" aria-hidden style={{ flexShrink: 0 }}>
      <defs>
        <linearGradient id="bs-shield" x1="8" y1="4" x2="40" y2="44" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--accent-violet)" />
          <stop offset="1" stopColor="var(--accent-blue)" />
        </linearGradient>
      </defs>
      <path d="M24 3.5 8 9.2v12.3c0 9.7 6.6 16.8 16 19.9 9.4-3.1 16-10.2 16-19.9V9.2L24 3.5Z" fill="url(#bs-shield)" />
      <circle cx="24" cy="11.4" r="1.7" fill="#fff" />
      <rect x="23.4" y="12.6" width="1.2" height="3" fill="#fff" />
      <rect x="15.5" y="15.2" width="17" height="13.6" rx="4.2" fill="#fff" />
      <rect x="13.2" y="19" width="2.7" height="6" rx="1.35" fill="#fff" />
      <rect x="32.1" y="19" width="2.7" height="6" rx="1.35" fill="#fff" />
      <rect x="18" y="18.6" width="12" height="6.6" rx="3.3" fill="#1b1640" />
      <circle cx="21.2" cy="21.9" r="1.7" fill="var(--accent-blue)" />
      <circle cx="26.8" cy="21.9" r="1.7" fill="var(--accent-blue)" />
    </svg>
  );
}

function Dot({ ok }: { ok: boolean }) {
  return <span style={{ width: 7, height: 7, borderRadius: "50%", background: ok ? "var(--safe)" : "var(--bot)", flexShrink: 0 }} />;
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [health, setHealth] = useState<Health | null>(null);
  const [down, setDown] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem("sidebar-collapsed") === "1");
  }, []);

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api.health()
        .then((h) => alive && (setHealth(h), setDown(false)))
        .catch(() => alive && setDown(true));
    ping();
    const id = setInterval(ping, 10000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // Ctrl+1..5 jump to a nav item.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.metaKey || e.altKey) return;
      const idx = parseInt(e.key, 10) - 1;
      if (idx >= 0 && idx < LINKS.length) {
        e.preventDefault();
        router.push(LINKS[idx].href);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);

  const toggle = () => {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem("sidebar-collapsed", next ? "1" : "0");
      return next;
    });
  };

  const hbaseOk = (health?.hbase_status ?? "").startsWith("connected");

  return (
    <aside
      style={{
        width: collapsed ? 56 : 256, flexShrink: 0, borderRight: "1px solid var(--border)",
        background: "var(--panel)", backdropFilter: "blur(18px) saturate(150%)",
        WebkitBackdropFilter: "blur(18px) saturate(150%)",
        padding: collapsed ? "22px 8px" : "22px 16px",
        display: "flex", flexDirection: "column", gap: 6,
        position: "sticky", top: 0, height: "100vh",
        transition: "width 200ms ease, padding 200ms ease",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: collapsed ? "center" : "space-between", gap: 8, padding: "0 4px 16px" }}>
        {!collapsed ? (
          <>
            <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
              <LogoMark />
              <div style={{ minWidth: 0 }}>
                <div className="mono" style={{ fontSize: 13, fontWeight: 700, letterSpacing: 0.3 }}>BotSentry</div>
                <div style={{ fontSize: 11, color: "var(--muted)" }}>v1.0 · detection engine</div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
              <ThemeToggle compact />
              <button onClick={toggle} aria-label="Collapse sidebar"
                style={{ width: 32, height: 32, borderRadius: 9, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--muted)", display: "grid", placeItems: "center" }}>
                <PanelLeftClose size={15} />
              </button>
            </div>
          </>
        ) : <LogoMark size={24} />}
      </div>

      {collapsed && (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <ThemeToggle compact />
          <button onClick={toggle} aria-label="Expand sidebar"
            style={{ width: 32, height: 32, borderRadius: 9, border: "1px solid var(--border)", background: "var(--panel-2)", color: "var(--muted)", display: "grid", placeItems: "center" }}>
            <PanelLeft size={15} />
          </button>
        </div>
      )}

      {LINKS.map(({ href, label, icon: Icon }) => {
        const active = pathname === href;
        return (
          <Link key={href} href={href} className={`nav-link ${active ? "active" : ""}`}
            title={collapsed ? label : undefined}
            style={collapsed ? { justifyContent: "center", padding: "10px 0" } : undefined}>
            <Icon size={17} style={{ flexShrink: 0 }} />
            {!collapsed && <span style={{ flex: 1 }}>{label}</span>}
          </Link>
        );
      })}

      <div style={{ marginTop: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
        {!collapsed && (
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}>
            <div style={{ fontSize: 10, color: "var(--muted-2)", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 8 }}>System Status</div>
            <div className="mono" style={{ fontSize: 11, display: "flex", flexDirection: "column", gap: 6 }}>
              <StatusRow label="Model" value={health?.model_version ?? "—"} ok={!!health?.model_ready} />
              <StatusRow label="HBase" value={hbaseOk ? "connected" : (health ? "fake" : "—")} ok={hbaseOk} />
              <StatusRow label="Threshold" value={health ? String(health.threshold) : "—"} ok={!!health} muted />
            </div>
          </div>
        )}

        <div style={{ fontSize: 12, color: "var(--muted)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: collapsed ? "center" : "flex-start" }}>
            <span className="live-dot" style={{ width: 8, height: 8, borderRadius: "50%", background: down ? "var(--bot)" : "var(--safe)" }} />
            {!collapsed && (down ? "API offline" : "API live")}
          </div>
        </div>
      </div>
    </aside>
  );
}

function StatusRow({ label, value, ok, muted }: { label: string; value: string; ok: boolean; muted?: boolean }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
      <span style={{ color: "var(--muted-2)" }}>{label}</span>
      <span style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text)", minWidth: 0 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 110 }}>{value}</span>
        {!muted && <Dot ok={ok} />}
      </span>
    </div>
  );
}

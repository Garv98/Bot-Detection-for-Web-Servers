"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; title: string; body?: string };

type ToastApi = { show: (t: Omit<Toast, "id">) => void };

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

const TONE: Record<Tone, string> = {
  success: "var(--safe)",
  error: "var(--bot)",
  info: "var(--info)",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { ...t, id }]);
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 4500);
  }, []);

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div role="status" aria-live="polite" aria-atomic="true"
        style={{ position: "fixed", right: 20, bottom: 20, display: "flex", flexDirection: "column", gap: 10, zIndex: 1000, maxWidth: 360 }}>
        {toasts.map((t) => (
          <div key={t.id} className="card pop" style={{ padding: "12px 14px", borderLeft: `3px solid ${TONE[t.tone]}`, boxShadow: "var(--shadow)" }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: TONE[t.tone] }}>{t.title}</div>
            {t.body && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 3 }}>{t.body}</div>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// Typed client for the FastAPI bot-detection backend.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

// WebSocket base for the real-time monitoring channel (/ws/live).
export const WS_BASE = API_BASE.replace(/^http/, "ws");

const TIMEOUT_MS = 10_000;
const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 500;

class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** fetch with a 10s AbortController timeout and up to 2 retries on network/5xx. */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal: ctrl.signal, ...init });
      clearTimeout(timer);
      if (!res.ok) {
        // Don't retry client errors (4xx) — they won't succeed on retry.
        if (res.status >= 400 && res.status < 500) throw new HttpError(res.status, `${path} -> ${res.status}`);
        throw new HttpError(res.status, `${path} -> ${res.status}`);
      }
      return (await res.json()) as T;
    } catch (err) {
      clearTimeout(timer);
      lastErr = err;
      const isClientError = err instanceof HttpError && err.status >= 400 && err.status < 500;
      if (isClientError || attempt === MAX_RETRIES) break;
      await sleep(RETRY_DELAY_MS);
    }
  }
  throw lastErr;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ---- response types ----
export interface Health {
  status: string;
  model_version: string;
  model_ready: boolean;
  threshold: number;
  hbase_status: string;
  uptime_seconds: number;
}
export interface Overview {
  total_ips: number;
  bots: number;
  humans: number;
  bot_ratio: number;
  total_requests: number;
  avg_requests_per_hour: number;
  best_model: string;
  model_auc: number | null;
  label_kind: string;
  model_version: string;
}
export type Severity = "danger" | "warn" | "ok" | "info";
export interface Signal {
  key: string; label: string; value: string; severity: Severity; note: string;
}
export type Decision = "allow" | "throttle" | "block";
export interface CheckResult {
  ip: string;
  risk_score: number;
  is_bot: boolean;
  reason: string;
  session_count: number;
  features?: Record<string, number | string>;
  signals?: Signal[];
  // Decision Output stage (ALLOW / THROTTLE / BLOCK + HTTP status).
  decision?: Decision;
  http_status?: number;
  action?: string;
}
export interface RecentEvent {
  id?: number;
  ip: string; t: number; path: string | null;
  risk_score: number | null; is_bot: number; cidr_block: string;
}
export interface ScoreResult {
  ip: string;
  risk_score: number;
  flagged: boolean;
  last_seen: string | null;
  req_count: number;
}
export interface BulkRow { ip: string; risk_score: number; is_bot: boolean; }
export interface TopBot {
  ip: string; req_count: number; requests_per_hour: number;
  rate_404: number; ua_entropy: number; error_rate: number; session_count: number;
}
export interface RiskBin { requests_per_hour_bucket: number; bots: number; humans: number; }
export interface ScatterPoint {
  ip: string; requests_per_hour: number; error_rate: number;
  unique_paths_ratio: number; ua_entropy: number; req_count: number; is_robot: number;
}
export interface FeatureImportance { feature: string; importance: number; }
export interface TimePoint { t: number; bots: number; humans: number; }
export interface HeatCell { dow: number; hour: number; requests: number; }
export interface ModelScores {
  model: string; threshold: number; precision: number;
  recall: number; f1: number; auc_roc: number;
}
export interface ModelMetrics {
  best_model: string;
  chosen_threshold: number;
  n_samples: number;
  n_robots: number;
  models: Record<string, ModelScores>;
}
export interface GroundTruthMetrics extends ModelMetrics {
  available: boolean;
  label?: string;
  dataset?: string;
}
export interface TopPath { path: string; total: number; bots: number; humans: number; }
export interface CIDRActivity {
  cidr_block: string; total: number; bots: number; humans: number; bot_ratio: number;
}
export interface EventsSummary {
  total_events: number; bot_events: number; human_events: number;
  bot_ratio: number; unique_ips: number; unique_paths: number; last_event_at: number | null;
}
export interface SimulateResult {
  generated: number; bots: number; humans: number;
  cleared?: boolean; hbase_profiles_written?: number; error?: string;
}
// Pushed over the /ws/live WebSocket (real-time monitoring).
export type LiveMessage =
  | { type: "snapshot"; events: RecentEvent[]; summary: EventsSummary }
  | { type: "events"; events: RecentEvent[]; summary: EventsSummary };

export const api = {
  health: () => get<Health>("/api/health"),
  overview: () => get<Overview>("/api/analytics/overview"),
  check: (ip: string, useragent?: string, path?: string) =>
    post<CheckResult>("/api/check", { ip, useragent, path }),
  score: (ip: string) => get<ScoreResult>(`/api/score?ip=${encodeURIComponent(ip)}`),
  bulkScore: (ips: string[]) => post<BulkRow[]>("/api/bulk-score", { ips }),
  topBots: (limit = 20) => get<TopBot[]>(`/api/analytics/top-bots?limit=${limit}`),
  riskDistribution: () => get<RiskBin[]>("/api/analytics/risk-distribution"),
  scatter: (limit = 600) => get<ScatterPoint[]>(`/api/analytics/scatter?limit=${limit}`),
  featureImportances: () => get<FeatureImportance[]>("/api/model/feature-importances"),
  modelMetrics: () => get<ModelMetrics>("/api/model/metrics"),
  groundtruth: () => get<GroundTruthMetrics>("/api/model/groundtruth"),
  groundtruthImportances: () => get<FeatureImportance[]>("/api/model/groundtruth/feature-importances"),
  timeseries: () => get<TimePoint[]>("/api/events/timeseries"),
  heatmap: () => get<HeatCell[]>("/api/events/heatmap"),
  recentEvents: (limit = 12, offset = 0, sinceId?: number) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (sinceId != null) params.set("since_id", String(sinceId));
    return get<RecentEvent[]>(`/api/events/recent?${params.toString()}`);
  },
  // new analytics
  topPaths: () => get<TopPath[]>("/api/analytics/top-paths"),
  cidrActivity: () => get<CIDRActivity[]>("/api/analytics/cidr-activity"),
  eventsSummary: () => get<EventsSummary>("/api/events/summary"),
  simulate: (n = 300, clearFirst = false) =>
    post<SimulateResult>("/api/simulate", { n, clear_first: clearFirst }),
  clearEvents: (adminToken: string) =>
    request<{ cleared: boolean; removed: number }>("/api/events", {
      method: "DELETE",
      headers: { "X-Admin-Token": adminToken },
    }),
  addAllowlist: (ip: string, adminToken: string) =>
    request<{ ip: string; allowlisted: boolean; already_present: boolean }>("/api/allowlist", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Admin-Token": adminToken },
      body: JSON.stringify({ ip }),
    }),
};

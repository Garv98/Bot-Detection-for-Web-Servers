/** Compact "time since" — e.g. 5s, 2m, 3h, 4d (no suffix; caller adds "ago"). */
export function ago(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export const fmt = (n: number) => n.toLocaleString("en-US");

// Tiny client-side admin-token store. Admin actions (allowlist add, clear
// events) require the API's X-Admin-Token; we keep it in localStorage and
// prompt once when it's missing. Never logged, never sent anywhere but the API.
const KEY = "botsentry-admin-token";

export function getAdminToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(KEY);
}

export function setAdminToken(token: string): void {
  localStorage.setItem(KEY, token);
}

/** Returns a token, prompting the user once if none is stored. Null if cancelled. */
export function ensureAdminToken(): string | null {
  const existing = getAdminToken();
  if (existing) return existing;
  const entered = window.prompt("Enter admin token (set ADMIN_TOKEN on the API):");
  if (entered) { setAdminToken(entered.trim()); return entered.trim(); }
  return null;
}

// Owner session state kept in memory only (spec 003, US1): the session token lives in an
// HttpOnly cookie the page cannot read, and the CSRF token is never written to localStorage or
// sessionStorage. A reload asks /auth/me for it again.
let csrfToken: string | null = null;

// Up to spec 002 the browser kept APP_API_KEY under this key; it must not outlive the upgrade.
const LEGACY_API_KEY = "betting-ml.apiKey";

export function forgetLegacySecrets(): void {
  try {
    window.localStorage.removeItem(LEGACY_API_KEY);
  } catch {
    // storage unavailable: nothing was stored there either
  }
}
const listeners = new Set<() => void>();

export function getCsrfToken(): string | null {
  return csrfToken;
}

export function setCsrfToken(value: string | null): void {
  csrfToken = value;
}

/** Called by the API client when any request answers 401 (session missing or expired). */
export function notifyUnauthorized(): void {
  csrfToken = null;
  for (const listener of listeners) listener();
}

export function onUnauthorized(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

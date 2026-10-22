// Owner session state kept in memory only (spec 003, US1): the session token lives in an
// HttpOnly cookie the page cannot read, and the CSRF token is never written to localStorage or
// sessionStorage. A reload asks /auth/me for it again.
let csrfToken: string | null = null;
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

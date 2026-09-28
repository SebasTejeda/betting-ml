// The write key (APP_API_KEY of the backend .env) is asked once and kept in this browser only:
// this is a personal tool served on localhost (plan.md §7). It is never part of the repo.
const STORAGE_KEY = "betting-ml.apiKey";

export function getApiKey(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setApiKey(value: string | null): void {
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value);
    else window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable (private mode): the key lives only for this page load
  }
}

import createClient, { type Middleware } from "openapi-fetch";

import { getCsrfToken, notifyUnauthorized } from "../lib/session";
import type { paths } from "./schema";

/** Uniform error of the API (contracts/api.md): `{ "error": { code, message, details } }`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    /** Seconds from the `Retry-After` header of a 429, if any. */
    readonly retryAfter: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const LOGIN_PATH = "/api/v1/auth/login";

// The session cookie travels on its own (same origin); writes add the in-memory CSRF token.
// No secret is ever stored in the browser.
const auth: Middleware = {
  onRequest({ request }) {
    const csrf = getCsrfToken();
    if (csrf && WRITE_METHODS.has(request.method)) request.headers.set("X-CSRF-Token", csrf);
    return request;
  },
  onResponse({ request, response }) {
    if (response.status === 401 && new URL(request.url).pathname !== LOGIN_PATH) {
      notifyUnauthorized();
    }
    return response;
  },
};

export const api = createClient<paths>({
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "same-origin",
  // resolved on each call (tests replace the global fetch after this module loads)
  fetch: (request) => globalThis.fetch(request),
});
api.use(auth);

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Returns the data or throws an `ApiError` with the API's code and message. */
export async function unwrap<T>(call: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await call;
  if (response.ok) return data as T;
  const body = (error ?? {}) as { error?: { code?: string; message?: string; details?: unknown } };
  const detail = body.error;
  throw new ApiError(
    response.status,
    detail?.code ?? `HTTP_${response.status}`,
    detail?.message ?? response.statusText ?? "Error de la API",
    (detail?.details as Record<string, unknown> | undefined) ?? {},
    retryAfter(response),
  );
}

function retryAfter(response: Response): number | null {
  const seconds = Number(response.headers.get("Retry-After"));
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}

import createClient, { type Middleware } from "openapi-fetch";

import { getApiKey } from "../lib/apiKey";
import type { paths } from "./schema";

/** Uniform error of the API (contracts/api.md): `{ "error": { code, message, details } }`. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const WRITE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const auth: Middleware = {
  onRequest({ request }) {
    const key = getApiKey();
    if (key && WRITE_METHODS.has(request.method)) request.headers.set("X-API-Key", key);
    return request;
  },
};

export const api = createClient<paths>({ baseUrl: globalThis.location?.origin ?? "" });
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
  );
}

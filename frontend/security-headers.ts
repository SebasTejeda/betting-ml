// Response headers of the built frontend (spec 003, T011; same policy as the API, contract §4).
// `vite preview` serves them so the CSP is tried on the real build; the production web server
// (Caddy, docs/deploy.md in T020) must send the same ones.

export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  // Tailwind/Radix/Recharts set inline style attributes; scripts never run inline
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const COMMON = {
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "no-referrer",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  "Cross-Origin-Opener-Policy": "same-origin",
};

/** Built app: the full policy, enforced. */
export const PREVIEW_HEADERS: Record<string, string> = {
  ...COMMON,
  "Content-Security-Policy": CONTENT_SECURITY_POLICY,
};

/** Dev server: Vite injects an inline React-refresh preamble, so the CSP only reports there. */
export const DEV_HEADERS: Record<string, string> = {
  ...COMMON,
  "Content-Security-Policy-Report-Only": CONTENT_SECURITY_POLICY,
};

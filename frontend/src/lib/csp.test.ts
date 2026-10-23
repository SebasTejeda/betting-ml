import { readFileSync } from "node:fs";
import path from "node:path";

import { CONTENT_SECURITY_POLICY, DEV_HEADERS, PREVIEW_HEADERS } from "../../security-headers";

const root = path.resolve(import.meta.dirname, "../..");

test("index.html has no inline scripts nor inline event handlers (CSP script-src 'self')", () => {
  const html = readFileSync(path.join(root, "index.html"), "utf-8");
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
  expect(scripts.length).toBeGreaterThan(0);
  for (const [, attributes, body] of scripts) {
    expect(attributes).toMatch(/\bsrc="/);
    expect((body ?? "").trim()).toBe("");
  }
  expect(html).not.toMatch(/\son[a-z]+=/i);
  expect(readFileSync(path.join(root, "public/theme-init.js"), "utf-8")).toContain(
    "betting-ml.theme",
  );
});

test("the built app enforces the policy; the dev server only reports it", () => {
  const scriptSrc = CONTENT_SECURITY_POLICY.split("; ").find((d) => d.startsWith("script-src"));
  expect(scriptSrc).toBe("script-src 'self'");
  expect(CONTENT_SECURITY_POLICY).toContain("frame-ancestors 'none'");
  expect(CONTENT_SECURITY_POLICY).not.toContain("unsafe-eval");
  expect(PREVIEW_HEADERS["Content-Security-Policy"]).toBe(CONTENT_SECURITY_POLICY);
  expect(DEV_HEADERS["Content-Security-Policy"]).toBeUndefined();
  expect(DEV_HEADERS["Content-Security-Policy-Report-Only"]).toBe(CONTENT_SECURITY_POLICY);
  expect(PREVIEW_HEADERS["X-Frame-Options"]).toBe("DENY");
});

import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

// lazily loaded pages (charts) can take more than the default 1 s on a busy machine
configure({ asyncUtilTimeout: 5000 });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
// Warm up the lazily loaded chart pages once, so no test pays their first compile.
beforeAll(async () => {
  await Promise.all([import("../pages/MatchPage"), import("../pages/BetsPage")]);
}, 60_000);
afterEach(() => {
  cleanup();
  server.resetHandlers();
  window.localStorage.clear();
});
afterAll(() => server.close());

// jsdom has no ResizeObserver (used by Recharts' ResponsiveContainer).
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

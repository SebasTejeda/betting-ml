/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API runs on :8000 (`make serve`); the dev server proxies /api to it.
const API = process.env.VITE_API_PROXY ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": API } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    globals: true,
    coverage: {
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/**/*.test.tsx", "src/main.tsx", "src/api/schema.d.ts"],
      thresholds: { lines: 80, functions: 80 },
    },
  },
});

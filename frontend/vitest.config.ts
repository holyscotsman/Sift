import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Separate from vite.config.ts on purpose: the build config carries a dev-server
// proxy and a manual-chunks strategy that mean nothing here, and mixing them
// makes it unclear which settings the production bundle actually uses.
//
// jsdom rather than a real browser. Everything worth pinning in this app is
// component *logic* — a catch that empties a list, a selection rebuilt from a
// response, a branch on a decision type — none of which needs a rendering
// engine. Layout and visual regressions are a different problem and are not
// what these tests claim to cover.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    restoreMocks: true,
  },
});

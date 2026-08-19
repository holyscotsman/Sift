import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build emits to backend static-serving path; FastAPI serves `frontend/dist`
// at `/` (see backend/sift/main.py). The dev server proxies /api and /ws to the
// backend on :8756 so `npm run dev` works against a live scan.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8756", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8756", ws: true },
    },
  },
  build: {
    outDir: "dist",
    // The dist directory is served unauthenticated, so a source map publishes
    // the whole TypeScript source — every route name and request shape — to
    // anyone who loads the login page.
    sourcemap: false,
    rollupOptions: {
      output: {
        // Framework bytes change only on dependency bumps — a separate vendor
        // chunk stays cached across app deploys.
        //
        // Written as a function rather than the object form: the bundler now
        // takes `manualChunks` only as a callback, and the object shape fails
        // the build rather than being quietly ignored.
        manualChunks(id: string) {
          if (/node_modules[\\/](react|react-dom|react-router|react-router-dom)[\\/]/.test(id)) {
            return "vendor";
          }
          return undefined;
        },
      },
    },
  },
});

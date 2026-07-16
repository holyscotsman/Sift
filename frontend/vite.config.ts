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
    sourcemap: true,
  },
});

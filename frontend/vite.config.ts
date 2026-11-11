/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the API runs on :8000 (uvicorn app.main:app). The proxy keeps the session cookie same-origin.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } } },
  build: { outDir: "dist", chunkSizeWarningLimit: 2500 },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"], css: false },
});

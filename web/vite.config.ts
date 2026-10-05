import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// COMPARE_API points the dev server at another running app, e.g. http://127.0.0.1:8502
const API = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env.COMPARE_API ?? "http://127.0.0.1:8501";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "../tablecmp/web_dist", emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { "/api": API, "/theme.css": API },
  },
  test: { globals: true, environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});

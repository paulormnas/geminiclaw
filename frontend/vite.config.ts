import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const BACKEND = process.env["VITE_BACKEND_URL"] ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target: BACKEND, changeOrigin: false } } },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/api/schema.d.ts", "src/main.tsx"],
      thresholds: { lines: 70 },
    },
  },
});

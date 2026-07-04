import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { resolveAegisManualChunk } from "./src/chunking/manualChunks";

export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks: resolveAegisManualChunk,
      },
    },
  },
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/tests/setup.ts"],
  },
});

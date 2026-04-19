import path from "node:path";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const devHost = process.env.VITEST ? "127.0.0.1" : "localhost";

export default defineConfig({
  plugins: [react()],
  server: {
    host: devHost,
    port: 5173,
    strictPort: true,
  },
  preview: {
    host: devHost,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});

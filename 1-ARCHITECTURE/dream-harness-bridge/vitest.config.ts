import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

export default defineConfig({
  test: {
    include: ["tests/**/*.ts"],
    environment: "node",
    timeout: 30000,
  },
  resolve: {
    alias: {
      "@/": resolve(__dirname, "packages/bridge-core/src/"),
    },
  },
});

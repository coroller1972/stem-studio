import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    coverage: {
      provider: "v8",
      reporter: ["text", "html", "lcov"],
      include: ["src/domain/**/*.ts", "src/state/**/*.ts", "src/services/**/*.ts", "src/audio/**/*.ts"],
      thresholds: { lines: 55, functions: 50, statements: 55, branches: 45 },
    },
  },
});

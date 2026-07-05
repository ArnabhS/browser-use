import { defineConfig } from "vitest/config";

// Default to the node environment (dispatcher + ws-router need no DOM). The collector test opts into
// happy-dom via a `// @vitest-environment happy-dom` docblock at the top of that file.
export default defineConfig({
  test: {
    environment: "node",
  },
});

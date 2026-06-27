import { defineConfig } from "vite";
import { resolve } from "node:path";

// Plain Vite for the scaffold: build the SW entry, copy public/manifest.json to dist.
// @crxjs/vite-plugin (content scripts, HMR) arrives in M3.
export default defineConfig({
  publicDir: "public",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: { background: resolve(__dirname, "src/background/index.ts") },
      output: { entryFileNames: "[name].js", format: "es" },
    },
  },
});

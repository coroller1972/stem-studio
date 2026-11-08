import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The mobile stem player is a separate static site: it must not add pages or
// files to the Tauri bundle built from vite.config.ts.
export default defineConfig({
  plugins: [react()],
  // Relative URLs work both from a LAN preview and from a GitHub Pages subpath.
  base: "./",
  publicDir: "player-public",
  build: {
    outDir: "dist-player",
    emptyOutDir: true,
    rollupOptions: { input: "player.html" },
  },
  server: { port: 1430, strictPort: true, host: true },
  preview: { port: 4173, strictPort: true, host: true },
});

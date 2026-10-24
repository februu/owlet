import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// `bun run build` writes into the Python package, where `owlet-web` serves it.
// `bun run dev` proxies the API to an `owlet-web` running on its default port.
export default defineConfig({
  plugins: [react()],
  // The panel is served locally, so one bundle is fine.
  build: { outDir: "../owlet/web/static", emptyOutDir: true, chunkSizeWarningLimit: 1000 },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});

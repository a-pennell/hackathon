import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/v3/",
  plugins: [react()],
  server: { port: 5175, proxy: { "/api": "http://localhost:8000", "/v2/api": "http://localhost:8000", "/v3/api": "http://localhost:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/v2/",
  plugins: [react()],
  server: { port: 5174, proxy: { "/api": "http://localhost:8000", "/v2/api": "http://localhost:8000" } },
  build: { outDir: "dist", emptyOutDir: true },
});

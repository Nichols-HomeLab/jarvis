import { defineConfig } from "vite";
import { resolve } from "path";

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/ws": {
        target: process.env.VITE_BACKEND_PROXY || "http://localhost:8000",
        ws: true,
      },
      "/api": {
        target: process.env.VITE_BACKEND_PROXY || "http://localhost:8000",
      },
      "/media": {
        target: process.env.VITE_BACKEND_PROXY || "http://localhost:8000",
      },
    },
  },
  build: {
    outDir: "dist",
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        projector: resolve(__dirname, "projector.html"),
        dashboard: resolve(__dirname, "dashboard.html"),
      },
    },
  },
});

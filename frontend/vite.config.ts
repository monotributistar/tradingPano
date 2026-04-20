import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind to all interfaces so the Vite dev server is reachable from outside
    // the container when running via docker-compose.dev.yml.
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        // In Docker the backend service name is "api"; locally it's localhost.
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

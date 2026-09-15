import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react-swc";

const blockInternalApi: Plugin = {
  name: "omniflow-block-internal-api",
  configureServer(server) {
    server.middlewares.use((request, response, next) => {
      const path = (request.url ?? "").split("?", 1)[0];
      if (path === "/api/internal" || path.startsWith("/api/internal/")) {
        response.statusCode = 404;
        response.end();
        return;
      }
      next();
    });
  },
  configurePreviewServer(server) {
    server.middlewares.use((request, response, next) => {
      const path = (request.url ?? "").split("?", 1)[0];
      if (path === "/api/internal" || path.startsWith("/api/internal/")) {
        response.statusCode = 404;
        response.end();
        return;
      }
      next();
    });
  },
};

// https://vite.dev/config/
export default defineConfig({
  plugins: [blockInternalApi, react()],
  server: {
    host: "0.0.0.0",
    port: 3001,
    watch: {
      usePolling: process.env.VITE_USE_POLLING === "true",
    },
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
  preview: {
    port: 3001,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});

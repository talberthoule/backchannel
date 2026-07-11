import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const apiTarget = env.BACKCHANNEL_API_TARGET || "http://localhost:8000";
  const websocketTarget = apiTarget.replace(/^http/, "ws");

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        "/api": apiTarget,
        "/ws": {
          target: websocketTarget,
          ws: true,
        },
      },
    },
  };
});

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The Python REST API that serves /health, /signup and /login.
const restTarget = process.env.CHAT_REST_URI || "http://127.0.0.1:8000";

// During `npm run dev` the page is served by Vite, so REST calls are proxied to
// the Python server and stay same-origin. `npm run build` emits web/dist, which
// the Python server itself serves on port 8000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/health": restTarget,
      "/signup": restTarget,
      "/login": restTarget,
    },
  },
  preview: { port: 4173, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true },
});

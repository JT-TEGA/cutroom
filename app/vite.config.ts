/// <reference types="vitest/config" />
import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The app talks to the Cutroom API through /api (REST, media streams and the job WebSocket), so it works the same
// whichever port the API runs on (./cutroom sets CUTROOM_API_PORT).
const api = `http://127.0.0.1:${process.env.CUTROOM_API_PORT ?? "8000"}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    rollupOptions: {
      output: {
        // vendor code in its own chunks: cached across app changes, and no single 1 MB bundle
        manualChunks: {
          react: ["react", "react-dom", "react-router"],
          data: ["@tanstack/react-query", "openapi-fetch"],
          ui: ["radix-ui", "framer-motion", "@dnd-kit/core", "@dnd-kit/sortable", "sonner", "lucide-react"],
          markdown: ["react-markdown"],
        },
      },
    },
  },
  // component tests (npm test): jsdom, with the API answered by a fake server (src/test/setup.ts)
  test: { environment: "jsdom", setupFiles: ["src/test/setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
  server: {
    port: Number(process.env.CUTROOM_APP_PORT ?? 5173),
    proxy: {
      "/api": { target: api, changeOrigin: true, ws: true, rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
})

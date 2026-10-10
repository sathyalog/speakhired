import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  optimizeDeps: { exclude: ["harper.js"] },  // keep its WebAssembly files resolvable
  worker: { format: "es" },
  server: { port: 5173, proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8100" } },
});

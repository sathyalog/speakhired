// Copies Excalidraw's fonts into public/ so the whiteboard loads them from this app, not from a CDN (works offline).
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const from = join(root, "node_modules/@excalidraw/excalidraw/dist/prod/fonts");
const to = join(root, "public/excalidraw-assets/fonts");

if (!existsSync(from)) {
  console.warn("Excalidraw fonts not found; skipping copy.");
  process.exit(0);
}
rmSync(to, { recursive: true, force: true });
mkdirSync(dirname(to), { recursive: true });
cpSync(from, to, { recursive: true });
console.log("Copied Excalidraw fonts to public/excalidraw-assets/fonts");

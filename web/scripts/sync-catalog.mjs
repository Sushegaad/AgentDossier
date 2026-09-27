// Copy the built catalog into public/ so the browser can fetch it at <base>/catalog/.
// CATALOG_DIR defaults to ../data/catalog (the committed weekly snapshot).
import { cpSync, existsSync, mkdirSync, rmSync, copyFileSync } from "node:fs";
import { resolve } from "node:path";

const src = resolve(process.env.CATALOG_DIR ?? "../data/catalog");
const dst = resolve("public/catalog");
rmSync(dst, { recursive: true, force: true });
if (!existsSync(resolve(src, "index.json"))) {
  console.warn(`[sync-catalog] no catalog at ${src}; the site builds with an empty catalog`);
  mkdirSync(dst, { recursive: true });
} else {
  cpSync(src, dst, { recursive: true });
  mkdirSync(resolve("public/.well-known"), { recursive: true });
  copyFileSync(resolve(src, "ard.json"), resolve("public/.well-known/ard.json"));
  console.log(`[sync-catalog] copied ${src} -> ${dst}`);
}

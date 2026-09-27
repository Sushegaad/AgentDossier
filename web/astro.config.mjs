// @ts-check
import { defineConfig } from "astro/config";
import react from "@astrojs/react";

// The public demo is served from GitHub Pages under /AgentDossier.
// Enterprises serving their own instance at a root domain set SITE_BASE=/ .
const base = process.env.SITE_BASE ?? "/AgentDossier";
const site = process.env.SITE_URL ?? "https://sushegaad.github.io";

export default defineConfig({
  site,
  base,
  trailingSlash: "ignore",
  integrations: [react()],
  build: { format: "directory" },
  vite: { server: { fs: { allow: [".."] } } },
});

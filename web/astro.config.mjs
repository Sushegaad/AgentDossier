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
  // Inline the stylesheet into every page. The site is served from a CDN that caches HTML for
  // ten minutes: with an external, content-hashed CSS file, every deploy that changes the CSS leaves
  // cached pages pointing at a hash that no longer exists, and they render unstyled until the cache
  // expires. One 15 KB sheet inlined per page costs little and removes that failure entirely.
  build: { format: "directory", inlineStylesheets: "always" },
  vite: { server: { fs: { allow: [".."] } } },
});

// Launch gates for the public site (P1d): axe accessibility and Lighthouse scores.
// Usage: npm run build && node scripts/audit.mjs   (starts `astro preview` itself)
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { chromium } from "playwright";
import lighthouse from "lighthouse";

const require = createRequire(import.meta.url);
const AXE = require.resolve("axe-core/axe.min.js");
const BASE = process.env.SITE_BASE ?? "/AgentDossier";
const PORT = 4399;
const ORIGIN = `http://127.0.0.1:${PORT}`;
const MIN = { performance: 0.85, accessibility: 0.95, "best-practices": 0.9, seo: 0.9 };
const CHROME =
  process.env.CHROME_PATH ??
  [chromium.executablePath(), "/opt/pw-browsers/chromium"].find((p) => existsSync(p)) ??
  chromium.executablePath();

const preview = spawn("npx", ["astro", "preview", "--host", "127.0.0.1", "--port", String(PORT)], { stdio: "ignore" });
const kill = () => preview.kill();
process.on("exit", kill);
process.on("SIGINT", () => process.exit(130));

async function waitFor(url, tries = 40) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`preview did not start at ${url}`);
}

async function firstAgentPath(page) {
  await page.goto(`${ORIGIN}${BASE}/search/?q=agent`);
  await page.waitForSelector("article.result h3 a, .notice", { timeout: 20000 });
  const href = await page.$eval("article.result h3 a", (a) => a.getAttribute("href")).catch(() => null);
  return href;
}

let failed = false;
const main = async () => {
  await waitFor(`${ORIGIN}${BASE}/`);
  const browser = await chromium.launch({ executablePath: CHROME });
  const page = await browser.newPage();
  const agent = await firstAgentPath(page);
  const pages = [`${BASE}/`, `${BASE}/search/?q=insurance%20claims%20agent`, `${BASE}/domains/`, `${BASE}/compare/`, `${BASE}/private/`, `${BASE}/methodology/`, `${BASE}/enterprise/`];
  if (agent) pages.push(agent);

  // --- axe ---------------------------------------------------------------------
  for (const p of pages) {
    await page.goto(`${ORIGIN}${p}`);
    await page.waitForLoadState("networkidle");
    await page.addScriptTag({ path: AXE });
    const res = await page.evaluate(async () => await window.axe.run(document, { runOnly: ["wcag2a", "wcag2aa", "wcag21aa"] }));
    const bad = res.violations.filter((v) => ["serious", "critical"].includes(v.impact));
    console.log(`axe ${p}: ${res.violations.length} violation(s), ${bad.length} serious/critical`);
    for (const v of bad) {
      failed = true;
      console.log(`  ✗ ${v.id} (${v.impact}): ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    }
  }
  await browser.close();

  // --- lighthouse ----------------------------------------------------------------
  const { launch } = await import("chrome-launcher");
  const chrome = await launch({ chromePath: CHROME, chromeFlags: ["--headless=new", "--no-sandbox", "--disable-gpu"] });
  try {
    for (const p of [`${BASE}/`, agent ?? `${BASE}/domains/`]) {
      const result = await lighthouse(`${ORIGIN}${p}`, {
        port: chrome.port,
        output: "json",
        logLevel: "error",
        onlyCategories: Object.keys(MIN),
        formFactor: "desktop",
        screenEmulation: { mobile: false, width: 1350, height: 940, deviceScaleFactor: 1, disabled: false },
        throttlingMethod: "simulate",
      });
      const scores = Object.fromEntries(Object.entries(result.lhr.categories).map(([k, v]) => [k, v.score]));
      const line = Object.entries(scores)
        .map(([k, v]) => `${k}=${(v * 100).toFixed(0)}${v < MIN[k] ? "✗" : ""}`)
        .join(" ");
      console.log(`lighthouse ${p}: ${line}`);
      for (const [k, v] of Object.entries(scores)) if (v < MIN[k]) failed = true;
    }
  } finally {
    await chrome.kill();
  }
};

main()
  .catch((e) => {
    console.error(e);
    failed = true;
  })
  .finally(() => {
    kill();
    process.exit(failed ? 1 : 0);
  });

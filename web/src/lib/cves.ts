// The CVE registry (data/cves/index.json): every official CVE related to an AI agent product,
// framework, protocol implementation or the infrastructure agents call through, as the weekly
// refresh builds it. Loaded at build time for the /cves/ tab, the per-CVE pages, the dossier and
// incident cross-links (PR 3) and the exports. Never a score of ours, never an exploit.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { type AgentCveSummary } from "./cve-summary";
import { type CveCategory, type CveRow, type CveStatus, type CveSurface, type FixStatus, type Severity, cveSlug } from "./cve-filter";

export interface CveProduct {
  vendor: string;
  product: string;
  versions_affected?: string | null;
  fixed_in?: string | null;
  product_id?: string | null;
}
export interface CveReference {
  url: string;
  source?: string | null;
  tags?: string[];
}
export interface CveRecord {
  id: string;
  description: string;
  published: string;
  last_modified: string;
  vuln_status?: string | null;
  cna?: string | null;
  cvss?: { version: string; score: number; severity: Severity; vector?: string | null; source?: string | null } | null;
  cwe?: string[];
  products: CveProduct[];
  category: CveCategory;
  surface: CveSurface[];
  kev?: { added: string; due?: string | null; ransomware?: string | null } | null;
  fix?: { status: FixStatus; version?: string | null; url?: string | null } | null;
  references: CveReference[];
  related_agents?: string[];
  related_incidents?: string[];
  match: { tests: string[]; terms: string[] };
  status: CveStatus | "excluded";
  note?: string | null;
  reviewer?: string | null;
  checked_on?: string | null;
  retrieved_on: string;
}
export interface CveIndex {
  version: string;
  built_at: string;
  config_version?: string;
  counts: { total: number; included: number; candidate: number; excluded: number; kev: number; unscored: number };
  products_matched: string[];
  records: CveRecord[];
}

let cached: CveIndex | null | undefined;

export function loadCves(): CveIndex | null {
  if (cached !== undefined) return cached;
  const path = resolve(process.env.CVES ?? "../data/cves/index.json");
  try {
    const doc = JSON.parse(readFileSync(path, "utf8")) as CveIndex;
    doc.records = (doc.records ?? []).filter((r) => r.status !== "excluded");
    cached = doc;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") cached = null;
    else throw e;
  }
  return cached;
}

export { cveSlug };

export function cveById(slug: string): CveRecord | null {
  return loadCves()?.records.find((r) => cveSlug(r.id) === slug.toLowerCase()) ?? null;
}

/** CVEs that name a catalog agent (by slug), for the dossier cross-link. */
export function cvesForAgent(agentSlug: string): CveRecord[] {
  return (loadCves()?.records ?? []).filter((r) => (r.related_agents ?? []).includes(agentSlug));
}

/** CVEs that an incident record names, for the Traces cross-link. */
export function cvesForIncident(incidentId: string): CveRecord[] {
  return (loadCves()?.records ?? []).filter((r) => (r.related_incidents ?? []).includes(incidentId));
}

/** A product as the page shows it: the listed name, else "vendor: product". */
export function productLabel(p: CveProduct, names: Record<string, string>): string {
  if (p.product_id && names[p.product_id]) return names[p.product_id];
  // An unlisted product, as its CPE spells it: "roocode:roo_code" → "roo code", "acme:widget" → "acme: widget".
  const tidy = (s: string) => s.replace(/_/g, " ");
  const key = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  return p.vendor && key(p.vendor) !== key(p.product) ? `${tidy(p.vendor)}: ${tidy(p.product)}` : tidy(p.product);
}

interface ProductConfig {
  products: Array<{ id: string; name: string }>;
}
let cachedNames: Record<string, string> | undefined;

/** Listed-product id → display name, from config/cve_products.json. */
export function productNames(): Record<string, string> {
  if (cachedNames) return cachedNames;
  const path = resolve(process.env.CVE_PRODUCTS ?? "../config/cve_products.json");
  try {
    const cfg = JSON.parse(readFileSync(path, "utf8")) as ProductConfig;
    cachedNames = Object.fromEntries(cfg.products.map((p) => [p.id, p.name]));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") cachedNames = {};
    else throw e;
  }
  return cachedNames;
}

const SUMMARY_CHARS = 180;

/** The slim row the list fetches (one line per CVE; the full record is on the detail page). */
export function toRow(r: CveRecord, names: Record<string, string> = productNames()): CveRow {
  const seen = new Set<string>();
  const products: string[] = [];
  for (const p of r.products) {
    const label = productLabel(p, names);
    if (!seen.has(label)) {
      seen.add(label);
      products.push(label);
    }
  }
  const d = r.description.replace(/\s+/g, " ").trim();
  return {
    id: r.id,
    published: r.published,
    modified: r.last_modified,
    severity: r.cvss?.severity ?? null,
    score: r.cvss?.score ?? null,
    category: r.category,
    surface: r.surface,
    products,
    product_ids: [...new Set(r.products.map((p) => p.product_id).filter((x): x is string => !!x))],
    kev: !!r.kev,
    status: r.status === "included" ? "included" : "candidate",
    reviewed: !!r.reviewer,
    fix: r.fix?.status ?? "unknown",
    cwe: r.cwe ?? [],
    summary: d.length > SUMMARY_CHARS ? `${d.slice(0, SUMMARY_CHARS - 1).trimEnd()}…` : d,
    agents: (r.related_agents ?? []).length,
    incidents: (r.related_incidents ?? []).length,
  };
}

export function allRows(): CveRow[] {
  const names = productNames();
  return (loadCves()?.records ?? []).map((r) => toRow(r, names));
}

/** Short words for the match tests, for the detail page's "why it is listed" line. */
export const MATCH_TEST_WORD: Record<string, string> = {
  "A:cpe": "a listed product's CPE",
  "A:name": "a listed product's name",
  "B:cwe": "CWE-1427 (improper neutralization of generative-AI prompts)",
  "B:vocabulary": "agent vocabulary in the official description",
};

/** What a dossier shows about one linked CVE: enough for the Security row and the CVE band. */
export interface CveLink {
  id: string;
  published: string;
  severity: Severity | null;
  score: number | null;
  surface: CveSurface[];
  kev: boolean;
  fix: FixStatus;
  reviewed: boolean;
  summary: string;
}

/** The CVEs linked to a catalog agent, newest first (the dossier's Security row and CVE band). */
export function cveLinksForAgent(agentSlug: string): CveLink[] {
  const names = productNames();
  return cvesForAgent(agentSlug)
    .map((r) => {
      const row = toRow(r, names);
      return { id: r.id, published: r.published, severity: row.severity, score: row.score, surface: r.surface, kev: row.kev, fix: row.fix, reviewed: row.reviewed, summary: row.summary };
    })
    .sort((a, b) => b.published.localeCompare(a.published) || a.id.localeCompare(b.id));
}

interface ProductAgents {
  products: Array<{ id: string; agents?: string[] }>;
}
let cachedAgentProducts: Record<string, string[]> | undefined;

/** Catalog slug → listed-product ids (config/cve_products.json), for the "all CVEs" link on a dossier. */
export function productIdsForAgent(agentSlug: string): string[] {
  if (!cachedAgentProducts) {
    const path = resolve(process.env.CVE_PRODUCTS ?? "../config/cve_products.json");
    cachedAgentProducts = {};
    try {
      const cfg = JSON.parse(readFileSync(path, "utf8")) as ProductAgents;
      for (const p of cfg.products) for (const a of p.agents ?? []) (cachedAgentProducts[a] ??= []).push(p.id);
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
    }
  }
  return cachedAgentProducts[agentSlug] ?? [];
}

/** Per catalog slug: how many CVEs link to it, how many are in KEV or critical/high, and the newest
 *  date — the search result's mark (/cves/agents.json), small enough to fetch once. */
export type { AgentCveSummary };

export function agentCveSummary(): Record<string, AgentCveSummary> {
  const out: Record<string, AgentCveSummary> = {};
  for (const r of loadCves()?.records ?? []) {
    for (const slug of r.related_agents ?? []) {
      const s = (out[slug] ??= { n: 0, kev: 0, severe: 0, newest: "" });
      s.n += 1;
      if (r.kev) s.kev += 1;
      if (r.cvss?.severity === "CRITICAL" || r.cvss?.severity === "HIGH") s.severe += 1;
      if (r.published > s.newest) s.newest = r.published;
    }
  }
  return out;
}

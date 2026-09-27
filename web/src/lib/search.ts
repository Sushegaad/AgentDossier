// Client-side search: MiniSearch full text + intent-derived boosts and requirement filters,
// with a template explanation per result (FR-27..FR-31). Everything is deterministic.
import MiniSearch from "minisearch";
import rules from "../../../config/intent_rules.json";
import synonymsFile from "../../../config/search_synonyms.json";
import { domainLabel, frameworkName, variantLabel } from "./labels";
import { intentIsEmpty, parseIntent, type Intent, type RequirementChip } from "./intent";
import type { IndexRecord, SearchDoc } from "./types";

export interface Filters {
  domain?: string;
  resource_type?: string;
  max_compliance_tier?: number; // show only records whose best active evidence is at least this good
  protocol?: string; // "mcp" | "a2a" | "ard"
  open_source?: boolean;
  strict?: boolean; // enforce must_have chips (default true)
}

export interface Hit {
  record: IndexRecord;
  score: number;
  explanation: string[];
  missing: RequirementChip[];
}

export interface SearchResult {
  intent: Intent;
  hits: Hit[];
  excluded: number; // records dropped by must_have chips
  total: number;
  /** true when every record failed a must-have, so the closest matches are shown with the gap flagged */
  relaxed: boolean;
}

const CAPABILITY_PHRASES = (rules.dimensions as { capability: { phrases: Record<string, string[]> } }).capability.phrases;
const SYNONYMS: Record<string, string[]> = synonymsFile.synonyms;

function expand(terms: string[]): string[] {
  const out = new Set(terms);
  for (const t of terms) for (const s of SYNONYMS[t] ?? []) out.add(s);
  return [...out];
}

const ECOSYSTEM_PHRASES = (rules.dimensions as { ecosystem: { phrases: Record<string, string[]> } }).ecosystem.phrases;

export class Catalog {
  readonly records: IndexRecord[];
  readonly byId: Map<string, IndexRecord>;
  readonly bySlug: Map<string, IndexRecord>;
  private readonly text: Map<string, string>;
  private readonly index: MiniSearch<SearchDoc>;

  constructor(records: IndexRecord[], docs: SearchDoc[] = []) {
    this.records = records;
    this.byId = new Map(records.map((r) => [r.id, r]));
    this.bySlug = new Map(records.map((r) => [r.slug, r]));
    const docById = new Map(docs.map((d) => [d.id, d]));
    this.text = new Map(
      records.map((r) => {
        const d = docById.get(r.id);
        const parts = [r.name, r.vendor, r.category, r.description, r.deployment, r.license, ...(r.tags ?? [])];
        if (d) parts.push(d.tags, d.capabilities, d.queries);
        return [r.id, parts.filter(Boolean).join(" ").toLowerCase()];
      }),
    );
    this.index = new MiniSearch<SearchDoc>({
      fields: ["name", "vendor", "category", "description", "tags", "capabilities", "queries"],
      storeFields: ["id"],
      searchOptions: {
        boost: { name: 4, vendor: 2, category: 2, capabilities: 1.5, queries: 1.5 },
        prefix: true,
        fuzzy: 0.15,
        combineWith: "OR",
      },
    });
    this.index.addAll(
      records.map((r) => {
        const d = docById.get(r.id);
        return {
          id: r.id,
          slug: r.slug,
          name: r.name,
          vendor: r.vendor ?? "",
          description: r.description ?? "",
          tags: d?.tags ?? (r.tags ?? []).join(" "),
          capabilities: d?.capabilities ?? "",
          queries: d?.queries ?? "",
          category: r.category ?? "",
          domains: Object.keys(r.domains).join(" "),
        };
      }),
    );
  }

  textOf(id: string): string {
    return this.text.get(id) ?? "";
  }

  search(query: string, filters: Filters = {}, limit = 50): SearchResult {
    const intent = parseIntent(query);
    const strict = filters.strict ?? true;
    const baseTerms = [...intent.terms, ...intent.capability.map((c) => c.replace(/_/g, " "))];
    const textQuery = expand(baseTerms).join(" ");
    const textScores = new Map<string, number>();
    if (textQuery.trim()) {
      let max = 0;
      const nTerms = new Set(baseTerms.join(" ").toLowerCase().split(/\s+/).filter(Boolean)).size || 1;
      for (const hit of this.index.search(textQuery)) {
        // reward covering more of the query, not just one common word many times
        const coverage = Math.min(1, new Set(hit.terms).size / nTerms);
        const s = hit.score * (0.4 + 0.6 * coverage);
        textScores.set(hit.id as string, s);
        max = Math.max(max, s);
      }
      for (const [id, s] of textScores) textScores.set(id, s / (max || 1));
    }
    const candidates =
      textQuery.trim() && !intent.domain.length && !intent.compliance.length && !intent.protocol.length
        ? this.records.filter((r) => textScores.has(r.id))
        : this.records;

    const run = (strictNow: boolean) => this.collect(candidates, intent, filters, textScores, strictNow);
    let { hits, excluded } = run(strict);
    let relaxed = false;
    if (strict && hits.length === 0 && excluded > 0) {
      ({ hits, excluded } = run(false));
      relaxed = true;
    }
    hits.sort((a, b) => b.score - a.score || a.record.name.localeCompare(b.record.name));
    return { intent, hits: hits.slice(0, limit), excluded, total: hits.length, relaxed };
  }

  private collect(candidates: IndexRecord[], intent: Intent, filters: Filters, textScores: Map<string, number>, strict: boolean) {
    let excluded = 0;
    const hits: Hit[] = [];
    for (const r of candidates) {
      if (filters.domain && !(filters.domain in r.domains)) continue;
      if (filters.resource_type && r.resource_type !== filters.resource_type) continue;
      if (filters.protocol && !["verified", "claimed"].includes(r.protocols[filters.protocol] ?? "")) continue;
      if (filters.open_source && !isOpenSource(r)) continue;
      if (filters.max_compliance_tier && bestActiveTier(r) > filters.max_compliance_tier) continue;
      if (intent.trust.includes("open_source") && !isOpenSource(r)) continue;

      const missing = intent.must_have.filter((c) => !satisfies(r, c));
      if (strict && missing.length) {
        excluded += 1;
        continue;
      }
      const { score, explanation } = this.scoreRecord(r, intent, textScores.get(r.id) ?? 0);
      if (score <= 0) continue;
      hits.push({ record: r, score, explanation, missing });
    }
    return { hits, excluded };
  }

  private scoreRecord(r: IndexRecord, intent: Intent, text: number): { score: number; explanation: string[] } {
    const why: string[] = [];
    let score = 0;
    const body = this.textOf(r.id);
    const empty = intentIsEmpty(intent);

    // domain rank / score
    const domains = intent.domain.length ? intent.domain.filter((d) => d in r.domains) : Object.keys(r.domains);
    let bestDomain: { id: string; score: number; rank: number | null } | null = null;
    for (const d of domains) {
      const e = r.domains[d];
      if (e?.score != null && (!bestDomain || e.score > bestDomain.score)) bestDomain = { id: d, score: e.score, rank: e.rank };
    }
    if (intent.domain.length) {
      if (bestDomain) {
        score += 40 * (bestDomain.score / 100);
        why.push(
          bestDomain.rank
            ? `#${bestDomain.rank} in ${domainLabel(bestDomain.id)} (score ${bestDomain.score.toFixed(1)})`
            : `listed in ${domainLabel(bestDomain.id)} (unranked)`,
        );
      } else {
        score -= 5; // domain words are hints, not filters: a strong text match still surfaces
        why.push(`not listed in ${intent.domain.map(domainLabel).join(" / ")}`);
      }
    } else if (bestDomain) {
      score += (empty ? 40 : 20) * (bestDomain.score / 100);
      if (empty || text === 0) why.push(`#${bestDomain.rank ?? "–"} in ${domainLabel(bestDomain.id)} (score ${bestDomain.score.toFixed(1)})`);
    }

    // text relevance
    if (text > 0) {
      score += 40 * text;
      const terms = intent.terms.filter((t) => body.includes(t));
      if (terms.length) why.push(`matches "${terms.slice(0, 4).join('", "')}"`);
    }

    // capability
    for (const cap of intent.capability) {
      const phrases = CAPABILITY_PHRASES[cap] ?? [cap];
      const hit = phrases.find((p) => body.includes(p.toLowerCase()));
      if (hit) {
        score += 8;
        why.push(`capability: ${hit}`);
      }
    }

    // requirement chips
    for (const c of intent.must_have) {
      const ev = evidenceFor(r, c);
      if (ev) {
        score += 10 + (5 - ev.tier) * 2;
        why.push(`${chipLabel(c)}: ${tierPhrase(ev.tier)}`);
      } else {
        const partial = partialEvidenceFor(r, c);
        if (partial) {
          score += 3;
          why.push(`${frameworkName(c.framework)} mentioned (${tierPhrase(partial.tier)}) but no ${variantLabel(c.variant)} evidence`);
        }
      }
    }
    for (const c of intent.prefer) {
      const ev = evidenceFor(r, c);
      if (ev) {
        score += 6;
        why.push(`preferred ${chipLabel(c)}: ${tierPhrase(ev.tier)}`);
      }
    }

    // protocols
    for (const p of intent.protocol) {
      const st = r.protocols[p];
      if (st === "verified") {
        score += 12;
        why.push(`${p.toUpperCase()} verified`);
      } else if (st === "claimed") {
        score += 6;
        why.push(`${p.toUpperCase()} claimed`);
      } else {
        score -= 10;
        why.push(`${p.toUpperCase()} not observed`);
      }
    }

    // deployment
    if (intent.deployment.includes("private")) {
      if (isSelfHostable(r)) {
        score += 10;
        why.push("self-hostable (open source or private deployment)");
      } else {
        score -= 8;
        why.push("no private deployment option observed");
      }
    }
    if (intent.deployment.includes("saas") && /saas|cloud|hosted|platform/.test(body)) score += 4;

    // ecosystem
    for (const eco of intent.ecosystem) {
      const phrases = [eco, ...(ECOSYSTEM_PHRASES[eco] ?? [])];
      if (phrases.some((p) => body.includes(p.toLowerCase()))) {
        score += 8;
        why.push(`${eco} ecosystem`);
      }
    }

    // evidence and issues nudges (small: never outrank fit)
    const best = bestActiveTier(r);
    if (best <= 2) score += 4;
    if (r.trust.issues === 3) {
      score -= 4;
      why.push("has open issues (see profile)");
    }
    return { score: Math.round(score * 10) / 10, explanation: why };
  }
}

export function isOpenSource(r: IndexRecord): boolean {
  const lic = (r.license ?? "").toLowerCase();
  return !!lic && !/commercial|proprietary|enterprise|saas|paid/.test(lic) && lic !== "unknown";
}

export function isSelfHostable(r: IndexRecord): boolean {
  return isOpenSource(r) || /self-host|self host|on-prem|vpc|private|docker|kubernetes|air-gap/i.test(`${r.deployment ?? ""} ${r.description ?? ""}`);
}

export function bestActiveTier(r: IndexRecord): number {
  const active = r.compliance_summary.filter((c) => c.status === "active").map((c) => c.tier);
  return active.length ? Math.min(...active) : 5;
}

export function evidenceFor(r: IndexRecord, chip: RequirementChip) {
  const matches = r.compliance_summary.filter(
    (c) => c.framework === chip.framework && c.status === "active" && (!chip.variant || c.variant === chip.variant) && c.tier <= chip.min_tier,
  );
  if (!matches.length) return null;
  return matches.reduce((a, b) => (a.tier <= b.tier ? a : b));
}

/** Same framework mentioned, but not the specific variant asked for (e.g. "HIPAA" without a BAA). */
export function partialEvidenceFor(r: IndexRecord, chip: RequirementChip) {
  if (!chip.variant) return null;
  const matches = r.compliance_summary.filter((c) => c.framework === chip.framework && c.status === "active" && c.variant !== chip.variant);
  if (!matches.length) return null;
  return matches.reduce((a, b) => (a.tier <= b.tier ? a : b));
}

export function satisfies(r: IndexRecord, chip: RequirementChip): boolean {
  return evidenceFor(r, chip) !== null;
}

export function chipLabel(c: RequirementChip): string {
  const v = c.variant ? ` ${variantLabel(c.variant)}` : "";
  return `${frameworkName(c.framework)}${v}`;
}

export function tierPhrase(tier: number): string {
  return { 1: "registry-matched (T1)", 2: "marketplace-listed (T2)", 3: "document-evidenced (T3)", 4: "vendor-claimed (T4)", 5: "no evidence" }[tier] ?? `tier ${tier}`;
}

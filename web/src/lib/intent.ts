// Rule-based intent parser (FR-27). Phrases come from config/intent_rules.json and
// config/taxonomy.json; nothing here is learned. Matching is case-insensitive on
// word boundaries, longer phrases win, and a phrase claimed by one dimension is
// still available to the others (e.g. "claims" is both the insurance domain and
// the claims capability).
import rules from "../../../config/intent_rules.json";
import taxonomy from "../../../config/taxonomy.json";

export interface RequirementChip {
  framework: string;
  variant?: string | null;
  min_tier: number;
}

export interface Intent {
  text: string;
  domain: string[];
  capability: string[];
  data_class: string[];
  deployment: string[];
  compliance: string[];
  protocol: string[];
  ecosystem: string[];
  jurisdiction: string[];
  trust: string[];
  must_have: RequirementChip[];
  prefer: RequirementChip[];
  /** free-text terms left after removing matched phrases and stopwords */
  terms: string[];
  /** matched phrase spans, for highlighting */
  matches: { dimension: string; value: string; phrase: string }[];
}

type PhraseMap = Record<string, string[]>;
type Dimension = { phrases?: PhraseMap; implies?: Record<string, Array<RequirementChip & { chip: "must_have" | "prefer" }>> };

const DIMENSIONS = rules.dimensions as unknown as Record<string, Dimension>;
const STOPWORDS = new Set<string>(rules.stopwords as string[]);
const COMPLIANCE_DEFAULT_TIER: number = (DIMENSIONS.compliance as { default_min_tier?: number }).default_min_tier ?? 4;
const PHRASE_TIERS: Record<string, number> =
  (DIMENSIONS.compliance as { phrase_tiers?: Record<string, number> }).phrase_tiers ?? {};

const ORDER = ["domain", "capability", "data_class", "deployment", "compliance", "protocol", "ecosystem", "jurisdiction", "trust"] as const;

function normalize(text: string): string {
  return text
    .toLowerCase()
    .replace(/[‘’]/g, "'")
    .replace(/[^a-z0-9$+./' -]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function phraseRe(phrase: string): RegExp {
  // word boundaries that also work for phrases ending in a digit or symbol
  return new RegExp(`(^|[^a-z0-9])${escapeRe(phrase.toLowerCase()).replace(/[\s-]+/g, "[\\s-]+")}(?=$|[^a-z0-9])`, "i");
}

function phrasesFor(dimension: string): PhraseMap {
  if (dimension === "domain") {
    const out: PhraseMap = {};
    for (const [id, d] of Object.entries(taxonomy.domains as Record<string, { keywords?: string[] }>)) {
      out[id] = d.keywords ?? [];
    }
    return out;
  }
  return DIMENSIONS[dimension]?.phrases ?? {};
}

export function parseIntent(text: string): Intent {
  const norm = normalize(text);
  let residue = ` ${norm} `;
  const intent: Intent = {
    text,
    domain: [],
    capability: [],
    data_class: [],
    deployment: [],
    compliance: [],
    protocol: [],
    ecosystem: [],
    jurisdiction: [],
    trust: [],
    must_have: [],
    prefer: [],
    terms: [],
    matches: [],
  };
  const consumed: string[] = [];
  for (const dim of ORDER) {
    const map = phrasesFor(dim);
    // longest phrase first so "soc 2 type ii" beats "soc 2"
    const candidates = Object.entries(map)
      .flatMap(([value, phrases]) => phrases.map((p) => ({ value, phrase: p })))
      .sort((a, b) => b.phrase.length - a.phrase.length);
    const hits = new Map<string, string>();
    for (const c of candidates) {
      if (hits.has(c.value)) continue;
      if (phraseRe(c.phrase).test(norm)) {
        hits.set(c.value, c.phrase);
        // domain and capability words stay searchable as free text ("claims" should still find claims agents)
        if (dim !== "domain" && dim !== "capability") consumed.push(c.phrase);
      }
    }
    for (const [value, phrase] of hits) {
      (intent[dim] as string[]).push(value);
      intent.matches.push({ dimension: dim, value, phrase });
    }
  }
  // requirement chips implied by data classes
  const implies = DIMENSIONS.data_class?.implies ?? {};
  for (const dc of intent.data_class) {
    for (const chip of implies[dc] ?? []) {
      const { chip: kind, ...req } = chip;
      (kind === "must_have" ? intent.must_have : intent.prefer).push(req);
    }
  }
  // explicit compliance mentions: "verified"/"certified" tighten the tier
  let tier = COMPLIANCE_DEFAULT_TIER;
  for (const [word, t] of Object.entries(PHRASE_TIERS)) {
    if (phraseRe(word).test(norm)) tier = Math.min(tier, t);
  }
  for (const fw of intent.compliance) {
    if (!intent.must_have.some((c) => c.framework === fw)) {
      intent.must_have.push({ framework: fw, min_tier: tier });
    }
  }
  if (intent.trust.includes("verified_only")) {
    for (const c of intent.must_have) c.min_tier = Math.min(c.min_tier, 2);
  }
  // leftover free-text terms
  for (const phrase of consumed.sort((a, b) => b.length - a.length)) {
    residue = residue.replace(phraseRe(phrase), "$1 ");
  }
  intent.terms = residue
    .split(/\s+/)
    .map((w) => w.replace(/^[^a-z0-9]+|[^a-z0-9]+$/g, ""))
    .filter((w) => w.length > 1 && !STOPWORDS.has(w) && !/^\d+$/.test(w));
  return intent;
}

export function intentIsEmpty(i: Intent): boolean {
  return (
    i.domain.length + i.capability.length + i.data_class.length + i.deployment.length + i.compliance.length +
      i.protocol.length + i.ecosystem.length + i.jurisdiction.length + i.trust.length + i.terms.length ===
    0
  );
}

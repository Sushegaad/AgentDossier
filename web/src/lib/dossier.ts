// Rule-driven blocks of the agent dossier (mockup 1g): evidence rows including
// "not found" for the domain's preset frameworks, the GDPR assembled-from-checks
// panel, the buyer checklist and the provenance list. No hand-written per-agent text.
import scoring from "../../../config/scoring.json";
import { frameworkName, sourceLabel, variantLabel } from "./labels";
import type { ComplianceRecord, Resource, Tier } from "./types";

// mirrors agentdossier/compliance/engine.py DOMAIN_PRESETS
export const DOMAIN_PRESETS: Record<string, string[]> = {
  healthcare: ["hipaa", "hitrust", "soc2"],
  government: ["fedramp", "csa_star", "iso27001"],
  finance: ["soc2", "iso27001", "pci_dss"],
  insurance: ["soc2", "iso27001", "pci_dss", "hipaa"],
  regulatory: ["soc2", "iso27001", "iso27701"],
  legal: ["soc2", "iso27001", "iso27701"],
  cybersecurity: ["soc2", "iso27001", "csa_star"],
  data: ["soc2", "iso27001", "iso27701"],
  business: ["soc2", "iso27001"],
  technology: ["soc2", "iso27001", "iso42001"],
  sales: ["soc2", "gdpr", "iso27701"],
  supply_chain: ["soc2", "iso27001"],
};
export const ALL_DOMAINS_EXTRA = ["iso42001", "csa_star"];
export const PROFILES = (scoring as { profiles: Record<string, Record<string, number>> }).profiles;
export const DOMAIN_PROFILES = (scoring as { domain_profiles: Record<string, string> }).domain_profiles;
export const COMPONENT_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries((scoring as { components: Record<string, { label: string; seed_max: number }> }).components).map(([k, v]) => [k, v.label]),
);
export const COMPONENT_MAX: Record<string, number> = Object.fromEntries(
  Object.entries((scoring as { components: Record<string, { label: string; seed_max: number }> }).components).map(([k, v]) => [k, v.seed_max]),
);

export type Mark = "found" | "claimed" | "missing" | "issue";

/**
 * Evidence about *this agent* versus evidence about its vendor. A registry row matched at entity
 * level (CSA STAR for "Microsoft") is real evidence, but it says nothing about one product; it is
 * shown separately and never counted in the agent's own evidence tier (reviewer feedback: a vendor
 * certification must not visually become a blanket endorsement of every agent it offers).
 */
export function agentScoped(c: Pick<ComplianceRecord, "scope" | "covers_resource">): boolean {
  if (c.covers_resource === "yes") return true;
  if (c.covers_resource === "inherited") return false;
  return c.scope !== "entity";
}

export interface EvidenceRow {
  mark: Mark;
  /** true: about this agent · false: inherited from the vendor */
  aboutAgent: boolean;
  framework: string;
  variant: string | null;
  tierLabel: string;
  status: string; // the sentence
  scope: string;
  source: string;
  sourceUrl: string | null;
  asOf: string;
  right: string; // valid-to / next check
  credited: boolean | null;
  record: ComplianceRecord | null;
}

const TIER_WORD: Record<number, string> = { 1: "Registry-matched", 2: "Marketplace-listed", 3: "Document-evidenced", 4: "Vendor-claimed", 5: "Unknown" };

export function bestDomain(res: Resource): [string, Resource["domains"][string]] | null {
  const entries = Object.entries(res.domains ?? {}).filter(([, e]) => e.rank || e.score != null);
  if (!entries.length) return null;
  entries.sort((a, b) => (a[1].rank ?? 999) - (b[1].rank ?? 999) || (b[1].score ?? 0) - (a[1].score ?? 0));
  return entries[0];
}

/** Frameworks a buyer in the agent's best domain would ask about first (the domain preset plus the two all-domain extras). */
export function presetFrameworks(res: Resource): string[] {
  const best = bestDomain(res);
  const set = new Set<string>(best ? (DOMAIN_PRESETS[best[0]] ?? ["soc2", "iso27001"]) : ["soc2", "iso27001"]);
  for (const f of ALL_DOMAINS_EXTRA) set.add(f);
  return [...set];
}

/**
 * The wording templates say "FedRAMP High: FedRAMP Authorized (FedRAMP Marketplace, 2026-10-10)". The ledger row
 * already shows the framework, the variant, the source and the date on its own lines, so the sentence keeps only
 * what is new: "FedRAMP Authorized".
 */
export function tidyDisplay(display: string | null | undefined, framework: string, variant: string | null): string {
  let s = (display ?? "").trim();
  if (!s) return s;
  const heads = [frameworkName(framework), variant ? variantLabel(variant) : "", variant ? `${frameworkName(framework)} ${variantLabel(variant)}` : ""].filter(Boolean);
  for (const h of heads) if (s.toLowerCase().startsWith(h.toLowerCase() + ":")) s = s.slice(h.length + 1).trim();
  s = s.replace(/\s*\([^()]*\d{4}-\d{2}-\d{2}\)\s*$/, "").trim();
  return s;
}

export function evidenceRows(res: Resource): EvidenceRow[] {
  const rows: EvidenceRow[] = [];
  const recs = [...(res.compliance ?? [])].sort((a, b) => a.tier - b.tier || a.framework.localeCompare(b.framework));
  for (const c of recs) {
    const active = c.status === "active";
    const mark: Mark = !active ? "issue" : c.tier === 4 ? "claimed" : "found";
    rows.push({
      mark,
      aboutAgent: agentScoped(c),
      framework: c.framework,
      variant: c.variant,
      tierLabel: `T${c.tier} ${TIER_WORD[c.tier]}`,
      status: tidyDisplay(c.display, c.framework, c.variant) || `${frameworkName(c.framework)}: ${c.status}`,
      scope: `${c.scope}${c.covers_resource && c.covers_resource !== "unknown" ? ` · covers this resource: ${c.covers_resource}` : ""}`,
      source: sourceLabel(c.source),
      sourceUrl: c.evidence_url,
      asOf: (c.retrieved_at || "").slice(0, 10),
      right: c.status === "expired" ? `expired ${c.valid_until ?? ""}` : c.status === "stale" ? `stale since ${c.stale_since ?? ""}` : c.valid_until ? `valid to ${c.valid_until}` : c.period_end ? `period ended ${c.period_end}` : c.next_check ? `re-check ${c.next_check}` : "",
      credited: c.credited ?? null,
      record: c,
    });
  }
  const have = new Set(recs.map((c) => c.framework));
  for (const f of presetFrameworks(res)) {
    if (have.has(f)) continue;
    rows.push({
      mark: "missing",
      aboutAgent: true,
      framework: f,
      variant: null,
      tierLabel: "T5 Unknown",
      status: `Nothing found in the sources checked.`,
      scope: "—",
      source: f === "fedramp" ? "FedRAMP Marketplace" : f === "csa_star" ? "CSA STAR Registry" : "registries, marketplaces, vendor pages",
      sourceUrl: null,
      asOf: "",
      right: "ask the vendor",
      credited: null,
      record: null,
    });
  }
  return rows;
}

export interface GdprRow {
  mark: Mark | "you";
  label: string;
  text: string;
}

export function gdprPanel(res: Resource): { rows: GdprRow[]; found: number; claimed: number } {
  const related = (res.compliance ?? []).filter((c) => ["gdpr", "uk_gdpr", "iso27701", "uk_us_data_bridge"].includes(c.framework) && c.status === "active");
  const rows: GdprRow[] = [];
  let found = 0;
  let claimed = 0;
  for (const c of related.sort((a, b) => a.tier - b.tier)) {
    const isFound = c.tier <= 3;
    if (isFound) found += 1;
    else claimed += 1;
    let note = "";
    if (c.variant === "DPF_ACTIVE") note = " Proves a transfer mechanism for EU-to-US transfers only.";
    if (c.framework === "iso27701") note = ` Privacy management system${c.scope === "entity" ? "; covers the organization, not this agent specifically" : ""}.`;
    if (c.variant === "DPA_AVAILABLE") note = " A DPA is a contract you still have to sign and review.";
    rows.push({ mark: isFound ? "found" : "claimed", label: isFound ? "Found" : "Claimed", text: `${c.display}.${note}` });
  }
  const seal = related.some((c) => c.variant === "ART42_SEAL");
  if (!seal) rows.push({ mark: "missing", label: "Not found", text: 'No Article 42 GDPR seal. "GDPR certified" is never shown without one.' });
  rows.push({ mark: "you", label: "You check", text: "Your lawful basis, DPIA, and whether this agent is inside the certificate scope." });
  return { rows, found, claimed };
}

export function checklist(res: Resource): string[] {
  const out: string[] = [];
  const active = (res.compliance ?? []).filter((c) => c.status === "active");
  const has = (f: string) => active.some((c) => c.framework === f);
  const doms = new Set(Object.keys(res.domains ?? {}));
  if (doms.has("healthcare") || doms.has("insurance") || has("hipaa")) out.push("Your lawful basis and DPIA for PHI and personal data the agent will touch");
  else if (doms.has("sales") || doms.has("legal") || doms.has("finance")) out.push("Your lawful basis and DPIA for the personal data the agent will process");
  if (has("soc2")) out.push("That the SOC 2 report period covers the components you will use; request the report under NDA");
  if (has("hipaa")) out.push("That the HIPAA BAA is offered for this product tier and region");
  if (has("iso27001")) out.push("Whether the ISO 27001 certificate scope names this service, or only the platform");
  if (has("fedramp")) out.push("Current FedRAMP status with the agency, if government use is intended");
  if (has("csa_star")) out.push("Whether the CSA STAR entry covers this product; Level 1 is a self-assessment, Level 2 a third-party attestation");
  if (has("gdpr") || has("uk_gdpr")) out.push("The transfer mechanism you will rely on; DPF covers EU-to-US transfers only");
  if (res.identity.tier > 3) out.push(`That ${res.vendor ?? "the vendor"} actually publishes this agent: nothing beyond the name ties the two together`);
  const missing = presetFrameworks(res).filter((f) => !has(f));
  if (missing.length) out.push(`Ask the vendor for ${missing.map((f) => frameworkName(f)).join(", ")} evidence; none was found in the sources checked`);
  const protos = Object.values(res.protocols ?? {});
  if (!protos.some((p) => p.status === "verified" || p.status === "claimed")) out.push("Whether the agent exposes MCP or A2A endpoints; none were observed");
  return out.slice(0, 6);
}

export function provenance(res: Resource): { source: string; what: string }[] {
  const out: { source: string; what: string }[] = [];
  const seen = new Set<string>();
  for (const s of res.sources ?? []) {
    if (seen.has(s.system)) continue;
    seen.add(s.system);
    const what =
      s.system === "seed_xlsx"
        ? "scores, rank, category"
        : s.system === "aws_marketplace"
          ? "identity, listing compliance fields"
          : s.system === "enterprise_scan"
            ? "discovery on the internal network"
            : s.system === "ard"
              ? "ARD entry, identity"
              : s.system === "github"
                ? "repository signals, license"
                : s.system === "huggingface"
                  ? "Hub signals"
                  : s.system === "mcp_registry"
                    ? "MCP server listing"
                    : "record";
    out.push({ source: sourceLabel(s.system), what });
  }
  const srcs = new Set((res.compliance ?? []).map((c) => c.source));
  for (const s of srcs) {
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push({ source: sourceLabel(s), what: s === "vendor_trust_centers" ? "claims" : s === "curated" ? "maintainer-reviewed evidence" : "compliance evidence" });
  }
  if (res.security) out.push({ source: "NVD", what: "security (CVE keyword search)" });
  if (res.news_checked) out.push({ source: "Hacker News, GDELT, vendor feeds", what: "news and chatter" });
  return out;
}

/** The ledger split the way a buyer should read it. */
export function evidenceGroups(res: Resource): { agent: EvidenceRow[]; vendor: EvidenceRow[] } {
  const rows = evidenceRows(res);
  return { agent: rows.filter((r) => r.aboutAgent), vendor: rows.filter((r) => !r.aboutAgent) };
}

/** Counts of active evidence *about this agent*; vendor-inherited rows are reported apart. */
export function tierCounts(res: Resource): string {
  const active = (res.compliance ?? []).filter((c) => c.status === "active");
  const own = active.filter(agentScoped);
  const inherited = active.length - own.length;
  if (!own.length) return inherited ? `no evidence about this agent · ${inherited} vendor-level record${inherited === 1 ? "" : "s"} (inherited)` : "no evidence found";
  const by: Record<number, number> = {};
  for (const c of own) by[c.tier] = (by[c.tier] ?? 0) + 1;
  const parts = Object.entries(by)
    .sort()
    .map(([t, n]) => `${n} ${TIER_WORD[Number(t) as Tier].toLowerCase()}`);
  return `${own.length} record${own.length === 1 ? "" : "s"} about this agent · ${parts.join(" · ")}${inherited ? ` · +${inherited} vendor-level (inherited)` : ""}`;
}

/** Best–worst tier among active evidence about this agent only. */
export function tierRange(res: Resource): string {
  const tiers = (res.compliance ?? []).filter((c) => c.status === "active" && agentScoped(c)).map((c) => c.tier);
  if (!tiers.length) return "T5";
  const lo = Math.min(...tiers);
  const hi = Math.max(...tiers);
  return lo === hi ? `T${lo}` : `T${lo}–T${hi}`;
}

export interface ProtocolLine {
  key: string;
  name: string;
  status: string;
  word: string;
  /** where a claim comes from: vendor documentation (curated) or the resource's own description */
  why?: string;
  evidenceUrl?: string;
}

const PROTO_NAMES: Record<string, string> = { mcp: "Model Context Protocol (MCP)", a2a: "Agent2Agent (A2A)", ard: "Agentic Resource Discovery (ARD)" };
const NOT_CHECKED: Record<string, string> = { code_host: "not probed: URL is on a code host, which never carries a publisher's well-known files", no_publisher_domain: "not probed: no publisher domain on record" };

export function protocolLines(res: Resource): ProtocolLine[] {
  const p = res.protocols ?? {};
  return ["mcp", "a2a", "ard"].map((key) => {
    const b = p[key] ?? { status: "unknown" };
    const s = b.status as string;
    const word = s === "verified" ? "verified at the publisher's endpoint" : s === "claimed" ? "claimed" : s === "invalid" ? "found but invalid" : s === "not_found" ? "probed, not found" : "not checked";
    let why: string | undefined;
    let evidenceUrl: string | undefined;
    if (s === "claimed") {
      const src = b.source as string | undefined;
      why = src === "curated_claim" ? `vendor documentation${b.note ? ` — ${b.note}` : ""}${b.checked_on ? ` (checked ${b.checked_on})` : ""}` : (b.note as string | undefined) ?? "named by the resource itself";
      evidenceUrl = (b.evidence_url as string | undefined) ?? undefined;
      const probe = b.probe as { status?: string } | undefined;
      if (probe?.status === "not_found") why += "; no endpoint at the publisher's well-known paths";
    } else if (s === "unknown" && typeof b.not_checked === "string") why = NOT_CHECKED[b.not_checked] ?? b.not_checked;
    return { key, name: PROTO_NAMES[key], status: s, word, why, evidenceUrl };
  });
}

export function protocolSentence(res: Resource): { text: string; count: string } {
  const lines = protocolLines(res);
  const n = lines.filter((l) => ["verified", "claimed"].includes(l.status)).length;
  return { text: lines.map((l) => `${l.name} ${l.word}`).join(" · "), count: `${n} / 3` };
}

export { variantLabel };

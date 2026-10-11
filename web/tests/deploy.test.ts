import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { beforeYouDeploy, RULES, verdictSentence } from "../src/lib/deploy";
import { agentScoped, evidenceGroups, tierCounts, tierRange } from "../src/lib/dossier";
import { parseReferenceSet, referenceFor } from "../src/lib/reference";
import type { ComplianceRecord, Resource } from "../src/lib/types";

const rec = (over: Partial<ComplianceRecord>): ComplianceRecord =>
  ({ framework: "soc2", variant: "SOC2_TYPE_II", tier: 4, status: "active", credited: false, source: "vendor_trust_centers", scope: "product", covers_resource: "unknown", issuer: null, certificate_id: null, issued: null, valid_until: null, period_end: null, evidence_url: "https://v.example/trust", retrieved_at: "2026-10-01T00:00:00Z", payload_hash: null, match_confidence: null, reviewer: null, review_reason: null, next_check: null, display: "SOC 2 Type II: vendor-claimed", ...over }) as ComplianceRecord;

const res = (over: Partial<Resource>): Resource =>
  ({ id: "r", slug: "r", name: "Agent", vendor: "Vendor", url: "https://v.example", resource_type: "agent", category: null, description: null, scope: "public", tenant: null, deployment: null, license: null, tags: [], external_ids: {}, protocols: { mcp: { status: "unknown" }, a2a: { status: "unknown" }, ard: { status: "unknown" } }, identity: { tier: 4, evidence: [], rules_version: "identity-1.0" }, compliance: [], domains: { technology: { score: 50, rank: null } }, sources: [], first_seen: "2026-10-01T00:00:00Z", last_seen: "2026-10-01T00:00:00Z", ...over }) as unknown as Resource;

describe("agent-level versus vendor-level evidence", () => {
  it("separates entity-scoped rows and keeps them out of the agent's tier", () => {
    const r = res({ compliance: [rec({ framework: "csa_star", variant: "STAR_LEVEL_2", tier: 1, scope: "entity", covers_resource: "unknown", display: "Found in CSA STAR" }), rec({ framework: "fedramp", variant: "FEDRAMP_MODERATE", tier: 1, scope: "product", covers_resource: "yes", display: "Found in FedRAMP" })] });
    const g = evidenceGroups(r);
    expect(g.vendor.map((x) => x.framework)).toEqual(["csa_star"]);
    expect(g.agent.filter((x) => x.mark === "found").map((x) => x.framework)).toEqual(["fedramp"]);
    expect(tierRange(r)).toBe("T1");
    expect(tierCounts(r)).toContain("+1 vendor-level (inherited)");
    const onlyVendor = res({ compliance: [rec({ framework: "csa_star", tier: 1, scope: "entity" })] });
    expect(tierRange(onlyVendor)).toBe("T5");
    expect(tierCounts(onlyVendor)).toBe("no evidence about this agent · 1 vendor-level record (inherited)");
    expect(agentScoped({ scope: "entity", covers_resource: "yes" })).toBe(true);
    expect(agentScoped({ scope: "product", covers_resource: "inherited" })).toBe(false);
  });
});

describe("before you deploy", () => {
  it("fires evidence, identity and protocol rules without the reference set", () => {
    const r = res({ identity: { tier: 4, evidence: ["vendor_name_only"], rules_version: "identity-1.1" }, protocols: { mcp: { status: "invalid" }, a2a: { status: "unknown" }, ard: { status: "unknown" } } });
    const b = beforeYouDeploy(r, null);
    expect(b.inReferenceSet).toBe(false);
    const keys = b.restrictions.map((x) => x.key);
    expect(keys).toContain("rule:publisher-unconfirmed");
    // a repository-owned agent (tier 3) is "publisher likely": no procurement restriction
    const likely = beforeYouDeploy(res({ identity: { tier: 3, evidence: ["repository_ownership"], rules_version: "identity-1.1" } }), null);
    expect(likely.restrictions.map((x) => x.key)).not.toContain("rule:publisher-unconfirmed");
    // supporting items are one short line each, never the full ledger sentence
    const withEvidence = beforeYouDeploy(res({ compliance: [rec({ framework: "fedramp", variant: "FEDRAMP_HIGH", tier: 1, scope: "entity", covers_resource: "inherited", display: "FedRAMP High: FedRAMP Authorized (FedRAMP Marketplace, 2026-10-10)" })] }), null);
    expect(withEvidence.supporting[0].text).toBe("FedRAMP High — registry-matched, vendor-level");
    expect(keys).toContain("rule:mcp-invalid");
    expect(keys).toContain("rule:soc2-missing"); // technology preset asks for SOC 2
    expect(keys).not.toContain("rule:hipaa-missing");
    expect(keys.some((k) => k.startsWith("rule:approval"))).toBe(false); // answer rules need the reference set
    expect(b.unknowns.length).toBeGreaterThan(0);
  });
  it("uses reference-set answers: unknowns become questions, no/unknown answers fire restrictions", () => {
    const set = parseReferenceSet(readFileSync(new URL("../../data/curated/reference_set.yaml", import.meta.url), "utf8"));
    const aider = referenceFor("aider-ai-aider", set)!;
    const b = beforeYouDeploy(res({ slug: "aider-ai-aider", name: "Aider" }), aider);
    expect(b.inReferenceSet).toBe(true);
    expect(b.answers).toHaveLength(5);
    expect(b.restrictions.map((x) => x.key)).toEqual(expect.arrayContaining(["rule:approval-gate", "rule:single-repo"]));
    expect(b.restrictions.map((x) => x.key)).not.toContain("rule:hosted-processor");
    expect(b.supporting.some((x) => x.key === "answer:private_repo" && x.source)).toBe(true);
    expect(b.unknowns.some((x) => x.key === "answer:approval")).toBe(true);
    const copilot = referenceFor("github-microsoft-github-copilot-coding-agent", set)!;
    const c = beforeYouDeploy(res({ slug: copilot.entry.slug }), copilot);
    expect(c.restrictions.map((x) => x.key)).toEqual(expect.arrayContaining(["rule:hosted-processor", "rule:scoped-credentials"]));
    expect(c.restrictions.map((x) => x.key)).not.toContain("rule:approval-gate");
    expect(verdictSentence(c, "Copilot")).toMatch(/4 of 5 questions documented, 1 of them answered no, 1 to ask the vendor; a bounded pilot is possible/);
    const tractable = referenceFor("tractable-tractable", set)!;
    const t = beforeYouDeploy(res({ slug: tractable.entry.slug }), tractable);
    expect(verdictSentence(t, "Tractable")).toMatch(/not sufficient to scope a pilot/);
  });
  it("every rule has an id, a condition and a restriction sentence", () => {
    for (const r of RULES) {
      expect(r.id).toBeTruthy();
      expect(Object.keys(r.when).length).toBeGreaterThan(0);
      expect(r.restriction.length).toBeGreaterThan(20);
    }
  });
});

describe("reference set file", () => {
  it("validates, and rejects placeholder reviewers and sourceless answers", () => {
    const text = readFileSync(new URL("../../data/curated/reference_set.yaml", import.meta.url), "utf8");
    const set = parseReferenceSet(text);
    expect(set.use_cases.length).toBe(2);
    expect(set.agents.length).toBeGreaterThanOrEqual(10);
    expect(() => parseReferenceSet(text.replace("reviewed_by: null", "reviewed_by: maintainer"))).toThrow(/reviewed_by/);
    expect(() => parseReferenceSet(text.replace("source: https://aider.chat/docs/usage.html", "source: see docs"))).toThrow(/source/);
  });
});

describe("ledger sentences say each thing once", () => {
  it("strips the framework prefix and the (source, date) suffix the row already shows", async () => {
    const { tidyDisplay } = await import("../src/lib/dossier");
    expect(tidyDisplay("FedRAMP High: FedRAMP Authorized (FedRAMP Marketplace, 2026-10-10)", "fedramp", "FEDRAMP_HIGH")).toBe("FedRAMP Authorized");
    expect(tidyDisplay("DPA available: Vendor-claimed (vendor page, 2026-10-10)", "gdpr", "DPA_AVAILABLE")).toBe("Vendor-claimed");
    expect(tidyDisplay("Expired 2025-01-01", "soc2", null)).toBe("Expired 2025-01-01");
    expect(tidyDisplay("", "soc2", null)).toBe("");
  });
});

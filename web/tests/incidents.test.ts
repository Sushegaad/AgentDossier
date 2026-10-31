import { describe, expect, it } from "vitest";
import { loadIncidents, incidentsForAgent, incidentById, toStix, TACTIC_LABEL } from "../src/lib/incidents";

describe("incident registry", () => {
  it("loads published incidents with sources and known tactics", () => {
    const set = loadIncidents();
    expect(set && set.incidents.length).toBeGreaterThan(0);
    for (const inc of set!.incidents) {
      expect(inc.status).toBe("published");
      expect(inc.sources.length).toBeGreaterThan(0);
      expect(inc.sources.every((s) => s.url.startsWith("https://"))).toBe(true);
      for (const t of inc.tactics ?? []) expect(TACTIC_LABEL[t]).toBeTruthy();
      expect(["attacker", "defender", "target"]).toContain(inc.ai_role);
    }
  });

  it("lists newest first", () => {
    const incs = loadIncidents()!.incidents;
    for (let i = 1; i < incs.length; i++) expect(String(incs[i - 1].date) >= String(incs[i].date)).toBe(true);
  });

  it("cross-links to agents and resolves by slug", () => {
    const forAgentforce = incidentsForAgent("salesforce-salesforce-agentforce");
    expect(forAgentforce.map((i) => i.id)).toContain("TR-2026-001");
    expect(incidentById("tr-2026-001")?.title).toMatch(/ForcedLeak/);
    expect(incidentById("nope")).toBeNull();
  });

  it("exports a STIX 2.1 bundle with an incident, identities and a pattern per tactic", () => {
    const inc = incidentById("tr-2026-007")!; // the Claude Code espionage incident
    const bundle = toStix(inc) as { type: string; objects: Array<{ type: string; id: string }> };
    expect(bundle.type).toBe("bundle");
    const types = bundle.objects.map((o) => o.type);
    expect(types).toContain("incident");
    expect(types.filter((t) => t === "identity").length).toBe(2);
    expect(types.filter((t) => t === "attack-pattern").length).toBe((inc.tactics ?? []).length);
    // deterministic ids: a second call yields the same bundle id
    expect((toStix(inc) as { id: string }).id).toBe(bundle.id);
    expect(bundle.objects.every((o) => /^[a-z-]+--[0-9a-f-]{36}$/.test(o.id))).toBe(true);
  });
});

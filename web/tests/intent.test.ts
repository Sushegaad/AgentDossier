import { describe, expect, it } from "vitest";
import { parseIntent } from "../src/lib/intent";

import { loadYaml, type IntentCase } from "./eval";

const loadCases = () => loadYaml<{ cases: IntentCase[] }>("../../eval/intent_cases.yaml").cases;

describe("intent parser", () => {
  it("BRD example: insurance claims with PHI", () => {
    const i = parseIntent("I need an agent for insurance claims that can handle PHI");
    expect(i.domain).toContain("insurance");
    expect(i.capability).toContain("claims");
    expect(i.data_class).toEqual(["phi"]);
    expect(i.must_have).toEqual([{ framework: "hipaa", variant: "BAA_AVAILABLE", min_tier: 4 }]);
  });
  it("verified tightens the tier", () => {
    const i = parseIntent("verified SOC 2 coding agent");
    expect(i.must_have).toEqual([{ framework: "soc2", min_tier: 1 }]);
    expect(i.capability).toContain("coding");
  });
  it("framework names are a topic, not a requirement, when the query is about compliance work", () => {
    const i = parseIntent("continuous compliance automation for SOC 2 and ISO 27001 programs");
    expect(i.must_have).toEqual([]);
    expect(i.prefer.map((c) => c.framework).sort()).toEqual(["iso27001", "soc2"]);
    expect(i.capability).not.toContain("security_operations");
  });
  it("leaves free-text terms", () => {
    const i = parseIntent("find agents for invoice reconciliation");
    expect(i.domain).toEqual(["finance"]);
    expect(i.terms).toEqual(["invoice", "reconciliation"]);
    expect(parseIntent("HIPAA agents inside our VPC").terms).toEqual([]);
  });
  it("eval/intent_cases.yaml: >= 95% of cases have every expected chip", () => {
    const cases = loadCases();
    const failures: string[] = [];
    for (const c of cases) {
      const i = parseIntent(c.text) as unknown as Record<string, unknown[]>;
      const missing: string[] = [];
      for (const [k, v] of Object.entries(c.expected)) {
        for (const item of v as unknown[]) {
          const ok =
            typeof item === "string"
              ? (i[k] ?? []).includes(item)
              : (i[k] ?? []).some((x) => JSON.stringify(x) === JSON.stringify(item));
          if (!ok) missing.push(`${k}:${JSON.stringify(item)}`);
        }
      }
      if (missing.length) failures.push(`${c.id} "${c.text}" missing ${missing.join(", ")}`);
    }
    const accuracy = 1 - failures.length / cases.length;
    console.log(`intent chip accuracy = ${(accuracy * 100).toFixed(1)}% over ${cases.length} cases${failures.length ? "\n  " + failures.join("\n  ") : ""}`);
    expect(accuracy).toBeGreaterThanOrEqual(0.95);
  });
});

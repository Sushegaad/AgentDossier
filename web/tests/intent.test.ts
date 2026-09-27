import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { parseIntent } from "../src/lib/intent";

// eval/intent_cases.yaml is simple enough to parse without a YAML dependency
function loadCases(): { id: string; text: string; expected: Record<string, unknown> }[] {
  const src = readFileSync(new URL("../../eval/intent_cases.yaml", import.meta.url), "utf8");
  const cases: { id: string; text: string; expected: Record<string, unknown> }[] = [];
  let cur: (typeof cases)[number] | null = null;
  let key = "";
  let chip: Record<string, unknown> | null = null;
  for (const line of src.split("\n")) {
    const m = line.match(/^- id: (\S+)/);
    if (m) {
      cur = { id: m[1], text: "", expected: {} };
      cases.push(cur);
      continue;
    }
    if (!cur) continue;
    const t = line.match(/^\s+text: (.+)$/);
    if (t) cur.text = t[1].replace(/^['"]|['"]$/g, "");
    const k = line.match(/^    (\w+):\s*$/);
    if (k) {
      key = k[1];
      cur.expected[key] = [];
      chip = null;
      continue;
    }
    const v = line.match(/^    - (\S+)$/);
    if (v && key) (cur.expected[key] as string[]).push(v[1]);
    const c = line.match(/^    - (\w+): (.+)$/);
    if (c && key) {
      chip = { [c[1]]: parse(c[2]) };
      (cur.expected[key] as unknown[]).push(chip);
      continue;
    }
    const c2 = line.match(/^      (\w+): (.+)$/);
    if (c2 && chip) chip[c2[1]] = parse(c2[2]);
  }
  return cases;
}
const parse = (s: string) => (/^\d+$/.test(s) ? Number(s) : s);

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
  it("leaves free-text terms", () => {
    const i = parseIntent("find agents for invoice reconciliation");
    expect(i.domain).toEqual(["finance"]);
    expect(i.terms).toEqual(["invoice", "reconciliation"]);
    expect(parseIntent("HIPAA agents inside our VPC").terms).toEqual([]);
  });
  for (const c of loadCases()) {
    it(`eval ${c.id}: ${c.text}`, () => {
      const i = parseIntent(c.text) as unknown as Record<string, unknown[]>;
      for (const [k, v] of Object.entries(c.expected)) {
        for (const item of v as unknown[]) {
          if (typeof item === "string") expect(i[k], k).toContain(item);
          else expect(i[k], k).toContainEqual(item);
        }
      }
    });
  }
});

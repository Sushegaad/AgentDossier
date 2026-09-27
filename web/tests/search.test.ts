import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { Catalog } from "../src/lib/search";
import { loadYaml, type EvalSet } from "./eval";
import type { CatalogIndex, SearchDoc } from "../src/lib/types";

const dir = process.env.CATALOG_DIR ?? new URL("../../data/catalog", import.meta.url).pathname;
const have = existsSync(`${dir}/index.json`);
const load = () => {
  const index = JSON.parse(readFileSync(`${dir}/index.json`, "utf8")) as CatalogIndex;
  const docs = JSON.parse(readFileSync(`${dir}/search-docs.json`, "utf8")) as SearchDoc[];
  return new Catalog(index.records, docs);
};

describe.skipIf(!have)("search over the built catalog", () => {
  it("insurance claims query ranks insurance-domain agents first", () => {
    const res = load().search("agent for insurance claims");
    expect(res.intent.domain).toContain("insurance");
    expect(res.hits.length).toBeGreaterThan(5);
    expect(res.hits.slice(0, 5).every((h) => "insurance" in h.record.domains)).toBe(true);
    expect(res.hits[0].explanation.join(" ")).toMatch(/in Insurance/);
  });
  it("must-have chips exclude records without evidence, and relax when not strict", () => {
    const cat = load();
    const strict = cat.search("coding agent with SOC 2");
    const relaxed = cat.search("coding agent with SOC 2", { strict: false });
    expect(strict.intent.must_have).toEqual([{ framework: "soc2", min_tier: 4 }]);
    if (strict.relaxed) {
      // no SOC 2 evidence anywhere (offline seed-only catalog): closest matches with the gap flagged
      expect(strict.hits.length).toBeGreaterThan(0);
      for (const h of strict.hits) expect(h.missing.map((m) => m.framework)).toEqual(["soc2"]);
    } else {
      expect(strict.excluded).toBeGreaterThan(0);
      expect(relaxed.total).toBeGreaterThan(strict.total);
      for (const h of strict.hits) expect(h.missing).toEqual([]);
    }
  });
  it("name search finds the agent", () => {
    const res = load().search("LangGraph");
    expect(res.hits[0].record.name).toBe("LangGraph");
  });
  it("empty query lists the catalog by best domain score", () => {
    const res = load().search("");
    expect(res.total).toBe(load().records.length);
  });
});

describe.skipIf(!have)("precision@10 gate on eval/queries.yaml", () => {
  it("meets the threshold", () => {
    const set = loadYaml<EvalSet>("../../eval/queries.yaml");
    const cat = load();
    const rows: { id: string; p: number; hits: string[]; missed: string[] }[] = [];
    for (const q of set.queries) {
      const top = cat.search(q.query).hits.slice(0, 10).map((h) => h.record.name);
      const hit = top.filter((n) => q.relevant.includes(n));
      rows.push({ id: q.id, p: hit.length / Math.min(10, q.relevant.length || 1), hits: hit, missed: q.relevant.filter((n) => !top.includes(n)) });
    }
    const p = rows.reduce((a, r) => a + r.p, 0) / rows.length;
    const weak = rows.filter((r) => r.p < 0.6);
    console.log(`precision@10 = ${p.toFixed(3)} over ${rows.length} queries (${set.version}); below 0.6: ${weak.map((r) => `${r.id}=${r.p.toFixed(2)} missed[${r.missed.join("; ")}]`).join(" | ") || "none"}`);
    expect(p).toBeGreaterThanOrEqual(set.threshold);
  });
});

import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { Catalog, HERO_QUERIES, heroPick } from "../src/lib/search";
import type { CatalogIndex, SearchDoc } from "../src/lib/types";

const dir = process.env.CATALOG_DIR ?? new URL("../../data/catalog", import.meta.url).pathname;
const have = existsSync(`${dir}/index.json`);
const load = () => {
  const index = JSON.parse(readFileSync(`${dir}/index.json`, "utf8")) as CatalogIndex;
  const docs = JSON.parse(readFileSync(`${dir}/search-docs.json`, "utf8")) as SearchDoc[];
  return { index, cat: new Catalog(index.records, docs) };
};

describe.skipIf(!have)("homepage specimen (heroPick)", () => {
  it("always returns a real top hit for one of the example queries", () => {
    const { cat } = load();
    const pick = heroPick(cat);
    expect(pick).not.toBeNull();
    expect(HERO_QUERIES).toContain(pick!.query);
    expect(cat.search(pick!.query, { strict: false }, 1).hits[0].record.id).toBe(pick!.hit.record.id);
    expect(pick!.hit.explanation.length).toBeGreaterThan(0);
  });
  it("prefers a hit with registry or marketplace evidence whenever the catalog has any", () => {
    const { index, cat } = load();
    const anyStrong = index.records.some((r) => r.compliance_summary.some((c) => c.status === "active" && c.tier <= 2));
    const pick = heroPick(cat)!;
    if (anyStrong) {
      // the live catalog: the specimen must never show "no evidence" above the fold
      expect(pick.hit.record.compliance_summary.some((c) => c.status === "active" && c.tier <= 2)).toBe(true);
    } else {
      // offline seed-only build: falls through to the first query, flagged as such
      expect(pick.withEvidence).toBe(false);
      expect(pick.index).toBe(0);
    }
  });
});

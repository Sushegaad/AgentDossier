import { describe, expect, it } from "vitest";
import { DEFAULT_FILTERS, EMPTY_FILTERS, applyFilters, facetCounts, filtersFromParams, filtersToParams, rowsToCsv, sortRows, type CveRow } from "../src/lib/cve-filter";
import { allRows, cveById, cvesForAgent, cvesForIncident, loadCves, toRow } from "../src/lib/cves";

const row = (over: Partial<CveRow>): CveRow => ({
  id: "CVE-2026-0001",
  published: "2026-01-02",
  modified: "2026-01-03",
  severity: "HIGH",
  score: 8.1,
  category: "framework",
  surface: ["prompt_injection"],
  products: ["LangChain"],
  product_ids: ["langchain"],
  kev: false,
  status: "candidate",
  reviewed: false,
  fix: "fixed",
  cwe: ["CWE-1427"],
  summary: "An agent can be made to call a tool.",
  agents: 1,
  incidents: 0,
  ...over,
});

const ROWS: CveRow[] = [
  row({}),
  row({ id: "CVE-2025-0002", published: "2025-06-01", modified: "2026-02-01", severity: "CRITICAL", score: 9.8, category: "protocol", surface: ["code_execution"], products: ["mcp-remote"], product_ids: ["mcp-remote"], kev: true, cwe: ["CWE-78"], summary: "Command injection in an MCP client.", fix: "unknown" }),
  row({ id: "CVE-2024-0003", published: "2024-03-01", modified: "2024-03-02", severity: null, score: null, category: "unclassified", surface: [], products: [], product_ids: [], reviewed: true, summary: "Something about an autonomous agent.", cwe: [] }),
];

describe("CVE filters", () => {
  it("sorts newest first by default, ties by id, and by score with unscored last", () => {
    expect(sortRows(ROWS, "published").map((r) => r.id)).toEqual(["CVE-2026-0001", "CVE-2025-0002", "CVE-2024-0003"]);
    expect(sortRows(ROWS, "score").map((r) => r.id)).toEqual(["CVE-2025-0002", "CVE-2026-0001", "CVE-2024-0003"]);
    expect(sortRows(ROWS, "modified")[0].id).toBe("CVE-2025-0002");
  });

  it("applies each facet and a word search over id, products, CWE and summary", () => {
    const f = (over: Partial<typeof EMPTY_FILTERS>) => applyFilters(ROWS, { ...EMPTY_FILTERS, ...over }).map((r) => r.id);
    expect(f({ kev: true })).toEqual(["CVE-2025-0002"]);
    expect(f({ reviewed: true })).toEqual(["CVE-2024-0003"]);
    expect(f({ severity: ["CRITICAL", "HIGH"] })).toEqual(["CVE-2026-0001", "CVE-2025-0002"]);
    expect(f({ surface: ["prompt_injection"] })).toEqual(["CVE-2026-0001"]);
    expect(f({ category: ["protocol"] })).toEqual(["CVE-2025-0002"]);
    expect(f({ product: ["langchain"] })).toEqual(["CVE-2026-0001"]);
    expect(f({ year: "2024" })).toEqual(["CVE-2024-0003"]);
    expect(f({ fix: "fixed" })).toEqual(["CVE-2026-0001", "CVE-2024-0003"]);
    expect(f({ q: "cwe-1427" })).toEqual(["CVE-2026-0001"]);
    expect(f({ q: "mcp injection" })).toEqual(["CVE-2025-0002"]);
    expect(f({ q: "autonomous" })).toEqual(["CVE-2024-0003"]);
    expect(f({ q: "nothing-here" })).toEqual([]);
  });

  it("counts facets against the other filters, so a count says what choosing it would give", () => {
    const c = facetCounts(ROWS, { ...EMPTY_FILTERS, kev: true });
    expect(c.kev).toBe(1);
    expect(c.severity.CRITICAL).toBe(1);
    expect(c.severity.HIGH).toBe(0);
    expect(c.years).toEqual(["2026", "2025", "2024"]);
    expect(c.productIds).toEqual(["langchain", "mcp-remote"]);
  });

  it("round-trips filters through the query string and ignores unknown values", () => {
    const f = { ...EMPTY_FILTERS, q: "mcp", surface: ["prompt_injection" as const, "ssrf" as const], kev: true, year: "2025", sort: "score" as const, product: ["mcp-remote"] };
    const back = filtersFromParams(new URLSearchParams(filtersToParams(f).toString()));
    expect(back).toEqual(f);
    expect(filtersToParams(EMPTY_FILTERS).toString()).toBe("all=1");
    expect(filtersFromParams(new URLSearchParams(""))).toEqual(DEFAULT_FILTERS);
    expect(filtersFromParams(new URLSearchParams("all=1")).severity).toEqual([]);
    expect(filtersFromParams(new URLSearchParams("kev=1")).severity).toEqual(["CRITICAL"]);
    expect(filtersFromParams(new URLSearchParams("severity=HIGH")).severity).toEqual(["HIGH"]);
    const junk = filtersFromParams(new URLSearchParams("surface=bogus,dos&sort=evil&year=20x&product=../x,aider"));
    expect(junk.surface).toEqual(["dos"]);
    expect(junk.sort).toBe("published");
    expect(junk.year).toBeNull();
    expect(junk.product).toEqual(["aider"]);
  });

  it("exports CSV with quoted fields and one line per row", () => {
    const csv = rowsToCsv(ROWS);
    expect(csv.split("\n")).toHaveLength(4);
    expect(csv.split("\n")[1]).toContain('"CVE-2026-0001","2026-01-02"');
    expect(csv).toContain('"yes"');
  });
});

describe("CVE registry (data/cves/index.json)", () => {
  it("loads, drops excluded rows, and makes rows the list can use", () => {
    const idx = loadCves();
    expect(idx && idx.records.length).toBeGreaterThan(100);
    expect(idx!.records.every((r) => r.status !== "excluded")).toBe(true);
    const rows = allRows();
    expect(rows.length).toBe(idx!.records.length);
    for (const r of rows.slice(0, 200)) {
      expect(r.id).toMatch(/^CVE-\d{4}-\d{4,}$/);
      expect(r.summary.length).toBeLessThanOrEqual(180);
      expect(r.published >= "2023-01-01").toBe(true);
    }
    expect(rows.some((r) => r.kev)).toBe(true);
  });

  it("labels products by the listed name and cuts long descriptions", () => {
    const rec = { ...loadCves()!.records[0], description: "x".repeat(400), products: [{ vendor: "Acme", product: "Widget", product_id: "aider" }] };
    const r = toRow(rec, { aider: "Aider" });
    expect(r.products).toEqual(["Aider"]);
    expect(r.summary.endsWith("…")).toBe(true);
    expect(toRow({ ...rec, products: [{ vendor: "Acme", product: "Widget" }] }, {}).products).toEqual(["Acme: Widget"]);
    expect(toRow({ ...rec, products: [{ vendor: "roocode", product: "roo_code" }] }, {}).products).toEqual(["roo code"]);
  });

  it("cross-links to the catalog and the incident registry", () => {
    expect(cveById("cve-2025-32711")?.id).toBe("CVE-2025-32711");
    expect(cvesForIncident("TR-2026-002").map((r) => r.id)).toContain("CVE-2025-32711");
    expect(cvesForAgent("langflow-langflow").length).toBeGreaterThan(0);
  });
});

describe("CVE cross-links on dossiers, search results and incidents", () => {
  it("lists an agent's CVEs newest first with the product ids behind them", async () => {
    const { cveLinksForAgent, productIdsForAgent, agentCveSummary } = await import("../src/lib/cves");
    const links = cveLinksForAgent("langflow-langflow");
    expect(links.length).toBeGreaterThan(10);
    for (let i = 1; i < links.length; i++) expect(links[i - 1].published >= links[i].published).toBe(true);
    expect(productIdsForAgent("langflow-langflow")).toEqual(["langflow"]);
    expect(productIdsForAgent("no-such-agent")).toEqual([]);
    const summary = agentCveSummary();
    expect(summary["langflow-langflow"].n).toBe(links.length);
    expect(summary["langflow-langflow"].newest).toBe(links[0].published);
  });

  it("words the summary line for none, one and several", async () => {
    const { cveSummaryLine } = await import("../src/lib/cve-summary");
    expect(cveSummaryLine(undefined)).toBe("No CVE linked in the registry");
    expect(cveSummaryLine({ n: 1, kev: 0, severe: 0, newest: "2026-01-01" })).toBe("1 CVE linked · newest 2026-01-01");
    expect(cveSummaryLine({ n: 3, kev: 1, severe: 2, newest: "2026-10-05" })).toBe("3 CVEs linked · 1 in KEV · 2 critical/high · newest 2026-10-05");
  });

  it("an incident's cves: field resolves to registry records", async () => {
    const { incidentById } = await import("../src/lib/incidents");
    expect(incidentById("tr-2026-002")?.cves).toEqual(["CVE-2025-32711"]);
    expect(incidentById("tr-2026-011")?.cves).toEqual(["CVE-2025-54135", "CVE-2025-54136"]);
  });
});

import { useEffect, useMemo, useState } from "react";
import { BASE } from "../lib/data";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  EMPTY_FILTERS,
  SEVERITY_ORDER,
  SEVERITY_WORD,
  SURFACE_LABEL,
  SURFACE_ORDER,
  applyFilters,
  cveSlug,
  facetCounts,
  filtersFromParams,
  filtersToParams,
  rowsToCsv,
  type CveFilters,
  type CveRow,
  type SortKey,
} from "../lib/cve-filter";

export interface CveAppProps {
  /** Rows, when the page inlines them; otherwise fetched from <base>/cves/list.json. */
  rows?: CveRow[];
  /** Listed-product id → display name (config/cve_products.json). */
  productNames: Record<string, string>;
  syncUrl?: boolean;
  pageSize?: number;
}

const SORTS: { key: SortKey; label: string }[] = [
  { key: "published", label: "Newest" },
  { key: "modified", label: "Last modified" },
  { key: "score", label: "CVSS score" },
  { key: "id", label: "ID" },
];

function severityClass(s: CveRow["severity"]): string {
  if (s === "CRITICAL") return "badge danger";
  if (s === "HIGH") return "badge warn";
  if (s === "MEDIUM" || s === "LOW") return "badge";
  return "badge";
}

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

export default function CveApp(props: CveAppProps) {
  const [rows, setRows] = useState<CveRow[] | null | undefined>(props.rows);
  const [filters, setFilters] = useState<CveFilters>(EMPTY_FILTERS);
  const [limit, setLimit] = useState(props.pageSize ?? 50);
  const [showAllProducts, setShowAllProducts] = useState(false);
  const syncUrl = props.syncUrl ?? true;
  const pageSize = props.pageSize ?? 50;

  useEffect(() => {
    if (syncUrl) setFilters(filtersFromParams(new URL(window.location.href).searchParams));
    if (props.rows !== undefined) return;
    fetch(`${BASE}/cves/list.json`)
      .then((r) => (r.ok ? (r.json() as Promise<CveRow[]>) : null))
      .then(setRows)
      .catch(() => setRows(null));
  }, [props.rows, syncUrl]);

  useEffect(() => {
    if (!syncUrl || rows === undefined) return;
    const p = filtersToParams(filters).toString();
    const next = `${window.location.pathname}${p ? `?${p}` : ""}`;
    if (next !== `${window.location.pathname}${window.location.search}`) window.history.replaceState(null, "", next);
  }, [filters, rows, syncUrl]);

  useEffect(() => setLimit(pageSize), [filters, pageSize]);

  const visible = useMemo(() => (rows ? applyFilters(rows, filters) : []), [rows, filters]);
  const counts = useMemo(() => (rows ? facetCounts(rows, filters) : null), [rows, filters]);
  const active = useMemo(() => filtersToParams({ ...filters, sort: "published" }).toString().length > 0, [filters]);

  const toggle = <K extends "category" | "surface" | "severity" | "product">(key: K, value: CveFilters[K][number]) =>
    setFilters((f) => {
      const list = f[key] as string[];
      const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
      return { ...f, [key]: next };
    });

  if (rows === undefined) return <p className="muted">Loading the registry…</p>;
  if (rows === null)
    return (
      <div className="notice warn">
        The CVE list could not be loaded. The registry is also published as <a href={`${BASE}/cves/export.json`}>export.json</a>.
      </div>
    );

  const productIds = counts ? (showAllProducts ? counts.productIds : counts.productIds.filter((p) => counts.product[p] > 0).slice(0, 14)) : [];
  const name = (id: string) => props.productNames[id] ?? id;

  return (
    <div>
      <form
        className="searchbox"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
        }}
      >
        <label className="sr-only" htmlFor="cve-q">
          Search CVEs
        </label>
        <input id="cve-q" type="search" value={filters.q} placeholder="Search by CVE id, product, CWE or words in the description" onChange={(e) => setFilters({ ...filters, q: e.target.value })} autoComplete="off" />
        <button type="button" className="btn" onClick={() => setFilters({ ...EMPTY_FILTERS, sort: filters.sort })} disabled={!active}>
          Clear filters
        </button>
      </form>

      <div className="row" style={{ marginTop: "12px", gap: "10px", flexWrap: "wrap", alignItems: "center" }}>
        <span className="small" aria-live="polite">
          <strong>{visible.length.toLocaleString()}</strong> of {rows.length.toLocaleString()} CVEs
        </span>
        <span className="seg" role="group" aria-label="Sort" style={{ fontSize: "0.8rem", whiteSpace: "nowrap" }}>
          {SORTS.map((s) => (
            <button key={s.key} type="button" aria-pressed={filters.sort === s.key} onClick={() => setFilters({ ...filters, sort: s.key })} style={{ padding: "4px 10px" }}>
              {s.label}
            </button>
          ))}
        </span>
        <span className="row" style={{ marginLeft: "auto", gap: "14px" }}>
          <button type="button" className="btn link small" onClick={() => download("agentdossier-cves.csv", rowsToCsv(visible), "text/csv")}>
            Export CSV ({visible.length})
          </button>
          <a className="btn link small" href={`${BASE}/cves/export.json`}>
            Full registry (JSON)
          </a>
        </span>
      </div>

      <div className="search-layout">
        <aside className="facets" aria-label="Filters">
          <div className="facet">
            <span className="label">Flags</span>
            <label>
              <span>
                <input type="checkbox" checked={filters.kev} onChange={(e) => setFilters({ ...filters, kev: e.target.checked })} />
                In CISA KEV (exploited in the wild)
              </span>
              <span className="count">{counts?.kev}</span>
            </label>
            <label>
              <span>
                <input type="checkbox" checked={filters.reviewed} onChange={(e) => setFilters({ ...filters, reviewed: e.target.checked })} />
                Reviewed by the maintainer
              </span>
              <span className="count">{counts?.reviewed}</span>
            </label>
          </div>
          <div className="facet">
            <span className="label">Severity (CVSS, official)</span>
            {SEVERITY_ORDER.filter((s) => s !== "NONE").map((s) => (
              <label key={s}>
                <span>
                  <input type="checkbox" checked={filters.severity.includes(s)} onChange={() => toggle("severity", s)} />
                  {SEVERITY_WORD[s]}
                </span>
                <span className="count">{counts?.severity[s]}</span>
              </label>
            ))}
          </div>
          <div className="facet">
            <span className="label">Attack surface</span>
            {SURFACE_ORDER.map((s) => (
              <label key={s}>
                <span>
                  <input type="checkbox" checked={filters.surface.includes(s)} onChange={() => toggle("surface", s)} />
                  {SURFACE_LABEL[s]}
                </span>
                <span className="count">{counts?.surface[s]}</span>
              </label>
            ))}
            <div className="tiny muted" style={{ marginTop: "6px" }}>From the CWE and the official description; a CVE can have several, or none.</div>
          </div>
          <div className="facet">
            <span className="label">Category</span>
            {CATEGORY_ORDER.map((c) => (
              <label key={c}>
                <span>
                  <input type="checkbox" checked={filters.category.includes(c)} onChange={() => toggle("category", c)} />
                  {CATEGORY_LABEL[c]}
                </span>
                <span className="count">{counts?.category[c]}</span>
              </label>
            ))}
          </div>
          <div className="facet">
            <span className="label">Product</span>
            {productIds.map((p) => (
              <label key={p}>
                <span>
                  <input type="checkbox" checked={filters.product.includes(p)} onChange={() => toggle("product", p)} />
                  {name(p)}
                </span>
                <span className="count">{counts?.product[p]}</span>
              </label>
            ))}
            {counts && counts.productIds.length > productIds.length && (
              <button type="button" className="btn link small" onClick={() => setShowAllProducts(true)} style={{ padding: 0, marginTop: "4px" }}>
                All {counts.productIds.length} products
              </button>
            )}
          </div>
          <div className="facet">
            <span className="label">Year published</span>
            <div className="seg" role="group" aria-label="Year">
              <button type="button" aria-pressed={filters.year === null} onClick={() => setFilters({ ...filters, year: null })}>
                All
              </button>
              {counts?.years.map((y) => (
                <button key={y} type="button" aria-pressed={filters.year === y} onClick={() => setFilters({ ...filters, year: filters.year === y ? null : y })}>
                  {y}
                </button>
              ))}
            </div>
          </div>
          <div className="facet">
            <span className="label">Fix</span>
            <div className="seg" role="group" aria-label="Fix status">
              {(["fixed", "unknown"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={filters.fix === v} onClick={() => setFilters({ ...filters, fix: filters.fix === v ? null : v })}>
                  {v === "fixed" ? "Fixed version known" : "Not stated"}
                </button>
              ))}
            </div>
          </div>
        </aside>

        <div>
          {visible.length === 0 ? (
            <p className="muted">No CVE matches these filters.</p>
          ) : (
            <div className="scroll-x" tabIndex={0}>
              <table>
                <thead>
                  <tr>
                    <th>CVE</th>
                    <th>Severity</th>
                    <th>Products</th>
                    <th>What it is</th>
                    <th>Surface</th>
                    <th>Links</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.slice(0, limit).map((r) => (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: "nowrap", fontWeight: 800 }}>
                        <a href={`${BASE}/cves/${cveSlug(r.id)}/`} style={{ color: "var(--ink)" }}>
                          {r.id}
                        </a>
                        <div className="tiny muted">{r.published}</div>
                        {r.kev && (
                          <div className="tiny" style={{ color: "var(--danger)", fontWeight: 700 }}>
                            KEV
                          </div>
                        )}
                      </td>
                      <td style={{ whiteSpace: "nowrap" }}>
                        {r.severity ? (
                          <span className={severityClass(r.severity)}>
                            {SEVERITY_WORD[r.severity]}
                            {r.score !== null ? ` ${r.score.toFixed(1)}` : ""}
                          </span>
                        ) : (
                          <span className="tiny muted">unscored</span>
                        )}
                        {r.fix === "fixed" && <div className="tiny muted">fix known</div>}
                      </td>
                      <td className="small">{r.products.length ? r.products.slice(0, 3).join(", ") + (r.products.length > 3 ? ` +${r.products.length - 3}` : "") : <span className="muted">—</span>}</td>
                      <td className="small">
                        {r.summary}
                        {!r.reviewed && <div className="tiny muted">unreviewed</div>}
                      </td>
                      <td className="tiny" style={{ minWidth: "9rem" }}>
                        {r.surface.map((s) => SURFACE_LABEL[s]).join(" · ") || "—"}
                      </td>
                      <td className="tiny" style={{ whiteSpace: "nowrap" }}>
                        {r.agents > 0 && <div>{r.agents} agent{r.agents === 1 ? "" : "s"}</div>}
                        {r.incidents > 0 && <div>{r.incidents} trace{r.incidents === 1 ? "" : "s"}</div>}
                        {r.agents === 0 && r.incidents === 0 && "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {visible.length > limit && (
            <div className="row" style={{ marginTop: "12px", gap: "10px", alignItems: "center" }}>
              <button type="button" className="btn" onClick={() => setLimit(limit + pageSize)}>
                Show {Math.min(pageSize, visible.length - limit)} more
              </button>
              <span className="tiny muted">
                {limit} of {visible.length} shown
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

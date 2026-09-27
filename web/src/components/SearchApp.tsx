import { useEffect, useMemo, useRef, useState } from "react";
import { BASE, agentHref, fetchIndex, fetchSearchDocs } from "../lib/data";
import { chipLabel } from "../lib/search";
import { Catalog, type Filters, type Hit } from "../lib/search";
import { badgeLabel, domainLabel, frameworkName } from "../lib/labels";
import type { CatalogIndex, SearchDoc } from "../lib/types";
import ShortlistButton from "./ShortlistButton";
import TrustStrip from "./TrustStrip";

export interface SearchAppProps {
  /** Pre-loaded data (private catalog viewer); otherwise fetched from <base>/catalog/. */
  index?: CatalogIndex | null;
  docs?: SearchDoc[];
  initialQuery?: string;
  syncUrl?: boolean;
  examples?: string[];
  /** Where agent links go; the private viewer keeps details inline instead. */
  linkAgents?: boolean;
}

const EXAMPLES = [
  "I need an agent for insurance claims that can handle PHI",
  "Find coding agents we can deploy inside our VPC",
  "customer-service agent for our Microsoft stack",
  "FedRAMP authorized agents for government",
  "contract review agent with SOC 2",
  "which agents support MCP",
];

export default function SearchApp(props: SearchAppProps) {
  const [index, setIndex] = useState<CatalogIndex | null | undefined>(props.index);
  const [docs, setDocs] = useState<SearchDoc[]>(props.docs ?? []);
  const [q, setQ] = useState(props.initialQuery ?? "");
  const [filters, setFilters] = useState<Filters>({ strict: true });
  const [limit, setLimit] = useState(10);
  const [expanded, setExpanded] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const syncUrl = props.syncUrl ?? true;
  const linkAgents = props.linkAgents ?? true;

  useEffect(() => {
    if (props.index !== undefined) return;
    if (syncUrl) {
      const u = new URL(window.location.href);
      const initial = u.searchParams.get("q");
      if (initial) setQ(initial);
      const d = u.searchParams.get("domain");
      if (d) setFilters((f) => ({ ...f, domain: d }));
    }
    Promise.all([fetchIndex(), fetchSearchDocs()]).then(([i, d]) => {
      setIndex(i);
      setDocs(d);
    });
  }, [props.index, syncUrl]);

  useEffect(() => {
    if (!syncUrl || typeof window === "undefined") return;
    const u = new URL(window.location.href);
    if (q) u.searchParams.set("q", q);
    else u.searchParams.delete("q");
    if (filters.domain) u.searchParams.set("domain", filters.domain);
    else u.searchParams.delete("domain");
    window.history.replaceState(null, "", u.toString());
  }, [q, filters.domain, syncUrl]);

  const catalog = useMemo(() => (index ? new Catalog(index.records, docs) : null), [index, docs]);
  const result = useMemo(() => (catalog ? catalog.search(q, filters, 500) : null), [catalog, q, filters]);
  const domains = useMemo(() => {
    const s = new Set<string>();
    for (const r of index?.records ?? []) for (const d of Object.keys(r.domains)) s.add(d);
    return [...s].sort((a, b) => domainLabel(a).localeCompare(domainLabel(b)));
  }, [index]);
  const types = useMemo(() => [...new Set((index?.records ?? []).map((r) => r.resource_type))].sort(), [index]);

  if (index === null) {
    return (
      <div className="notice warn">
        No catalog is available in this build. Run <code>agentdossier build</code> and rebuild the site, or open a private catalog
        under <a href={`${BASE}/private/`}>Private catalog</a>.
      </div>
    );
  }
  // the wrapper reserves space so content below does not jump when results arrive (CLS)
  if (!index) return <div style={{ minHeight: "70vh" }}><p className="muted">Loading catalog…</p></div>;

  const intent = result?.intent;
  const chips: { label: string; kind: string }[] = [];
  if (intent) {
    for (const d of intent.domain) chips.push({ label: domainLabel(d), kind: "domain" });
    for (const c of intent.capability) chips.push({ label: c.replace(/_/g, " "), kind: "capability" });
    for (const d of intent.data_class) chips.push({ label: d.toUpperCase(), kind: "data" });
    for (const d of intent.deployment) chips.push({ label: d === "private" ? "private deployment" : d, kind: "deployment" });
    for (const p of intent.protocol) chips.push({ label: p.toUpperCase(), kind: "protocol" });
    for (const e of intent.ecosystem) chips.push({ label: `${e} ecosystem`, kind: "ecosystem" });
    for (const j of intent.jurisdiction) chips.push({ label: j, kind: "jurisdiction" });
    for (const t of intent.trust) chips.push({ label: t.replace(/_/g, " "), kind: "trust" });
  }

  return (
    <div style={{ minHeight: "70vh" }}>
      <form
        className="searchbox"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setLimit(10);
        }}
      >
        <label className="sr-only" htmlFor="q">
          Describe what you need
        </label>
        <input
          id="q"
          ref={inputRef}
          type="search"
          value={q}
          placeholder="Describe what you need, e.g. “insurance claims agent that can handle PHI”"
          onChange={(e) => {
            setQ(e.target.value);
            setLimit(10);
          }}
          autoComplete="off"
        />
        <button className="btn primary" type="submit">
          Search
        </button>
      </form>
      {!q && (
        <p className="examples muted small" style={{ marginTop: "0.5rem" }}>
          Try:{" "}
          {(props.examples ?? EXAMPLES).map((ex, i) => (
            <span key={ex}>
              {i > 0 && " · "}
              <a
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setQ(ex);
                  inputRef.current?.focus();
                }}
              >
                {ex}
              </a>
            </span>
          ))}
        </p>
      )}

      {intent && (chips.length > 0 || intent.must_have.length > 0 || intent.prefer.length > 0) && (
        <div className="row" style={{ marginTop: "0.6rem" }} aria-label="What we understood">
          <span className="muted small">Understood:</span>
          {chips.map((c) => (
            <span key={c.kind + c.label} className="chip" title={c.kind}>
              {c.label}
            </span>
          ))}
          {intent.must_have.map((c) => (
            <span key={"m" + chipLabel(c)} className="chip must" title="must-have requirement">
              must: {chipLabel(c)} ≤T{c.min_tier}
            </span>
          ))}
          {intent.prefer.map((c) => (
            <span key={"p" + chipLabel(c)} className="chip prefer" title="preferred">
              prefer: {chipLabel(c)}
            </span>
          ))}
        </div>
      )}

      <div className="filters">
        <select
          aria-label="Domain"
          value={filters.domain ?? ""}
          onChange={(e) => setFilters({ ...filters, domain: e.target.value || undefined })}
        >
          <option value="">All domains</option>
          {domains.map((d) => (
            <option key={d} value={d}>
              {domainLabel(d)}
            </option>
          ))}
        </select>
        <select
          aria-label="Resource type"
          value={filters.resource_type ?? ""}
          onChange={(e) => setFilters({ ...filters, resource_type: e.target.value || undefined })}
        >
          <option value="">All types</option>
          {types.map((t) => (
            <option key={t} value={t}>
              {t.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <select
          aria-label="Minimum evidence"
          value={filters.max_compliance_tier ?? ""}
          onChange={(e) => setFilters({ ...filters, max_compliance_tier: e.target.value ? Number(e.target.value) : undefined })}
        >
          <option value="">Any evidence level</option>
          <option value="1">Registry-matched (T1)</option>
          <option value="2">Marketplace-listed or better (T2)</option>
          <option value="3">Document-evidenced or better (T3)</option>
          <option value="4">At least vendor-claimed (T4)</option>
        </select>
        <select
          aria-label="Protocol"
          value={filters.protocol ?? ""}
          onChange={(e) => setFilters({ ...filters, protocol: e.target.value || undefined })}
        >
          <option value="">Any protocol</option>
          <option value="mcp">MCP observed</option>
          <option value="a2a">A2A observed</option>
          <option value="ard">ARD observed</option>
        </select>
        <label className="chip" style={{ cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={!!filters.open_source}
            onChange={(e) => setFilters({ ...filters, open_source: e.target.checked || undefined })}
          />{" "}
          open source
        </label>
        {intent && intent.must_have.length > 0 && (
          <label className="chip" style={{ cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={filters.strict !== false}
              onChange={(e) => setFilters({ ...filters, strict: e.target.checked })}
            />{" "}
            enforce must-haves
          </label>
        )}
      </div>

      {result && result.relaxed && (
        <p className="notice warn small">
          No agent in this catalog has evidence for {result.intent.must_have.map(chipLabel).join(" and ")} in the sources checked. Showing
          the closest matches with the gap flagged in red; ask the vendor for the document before relying on it.
        </p>
      )}
      {result && (
        <p className="muted small" aria-live="polite">
          {result.total} result{result.total === 1 ? "" : "s"}
          {result.excluded > 0 && !result.relaxed && ` · ${result.excluded} excluded by must-have requirements`}
          {q && " · ranked by fit, then evidence; every result explains itself"}
        </p>
      )}

      <div>
        {result?.hits.slice(0, limit).map((h) => (
          <Result
            key={h.record.id}
            hit={h}
            linkAgents={linkAgents}
            expanded={expanded === h.record.id}
            onToggle={() => setExpanded(expanded === h.record.id ? null : h.record.id)}
          />
        ))}
      </div>
      {result && result.hits.length > limit && (
        <p style={{ marginTop: "1rem" }}>
          <button className="btn" type="button" onClick={() => setLimit(limit + 25)}>
            Show more ({result.hits.length - limit} left)
          </button>
        </p>
      )}
    </div>
  );
}

function Result({ hit, linkAgents, expanded, onToggle }: { hit: Hit; linkAgents: boolean; expanded: boolean; onToggle: () => void }) {
  const r = hit.record;
  const bestDomains = Object.entries(r.domains)
    .filter(([, e]) => e.rank)
    .sort((a, b) => (a[1].rank ?? 999) - (b[1].rank ?? 999))
    .slice(0, 3);
  const active = r.compliance_summary.filter((c) => c.status === "active");
  return (
    <article className="result">
      <div>
        <h3>
          {linkAgents ? <a href={agentHref(r.slug)}>{r.name}</a> : <button type="button" className="btn small" onClick={onToggle}>{r.name}</button>}{" "}
          <span className="muted small">
            {r.vendor} · {r.resource_type.replace(/_/g, " ")}
            {r.license ? ` · ${r.license}` : ""}
          </span>
        </h3>
        {r.description && <p className="small" style={{ margin: "0.25rem 0" }}>{r.description}</p>}
        <div className="row">
          <TrustStrip trust={r.trust} compact />
          {active.slice(0, 4).map((c) => (
            <span key={c.framework + c.variant} className={`badge${c.credited === false ? "" : " ok"}`} title={c.credited === false ? "pending publisher verification" : `tier ${c.tier}`}>
              {badgeLabel(c.framework, c.variant)} T{c.tier}
            </span>
          ))}
          {active.length > 4 && <span className="muted small">+{active.length - 4} more</span>}
        </div>
        <ul className="why">
          {hit.explanation.map((w) => (
            <li key={w}>{w}</li>
          ))}
          {hit.missing.map((m) => (
            <li key={"miss" + chipLabel(m)} style={{ color: "var(--danger)" }}>
              missing {chipLabel(m)}
            </li>
          ))}
        </ul>
        {expanded && !linkAgents && (
          <dl className="facts" style={{ marginTop: "0.5rem" }}>
            <dt>Domains</dt>
            <dd>
              {Object.entries(r.domains)
                .map(([d, e]) => `${domainLabel(d)}${e.rank ? ` #${e.rank}` : ""}`)
                .join(", ") || "—"}
            </dd>
            <dt>Evidence</dt>
            <dd>{active.length ? active.map((c) => `${frameworkName(c.framework)} T${c.tier}`).join(", ") : "none found"}</dd>
            <dt>Sources</dt>
            <dd>{r.sources.join(", ")}</dd>
          </dl>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", alignItems: "flex-end" }}>
        <div className="small muted" style={{ textAlign: "right" }}>
          {bestDomains.map(([d, e]) => (
            <div key={d}>
              #{e.rank} {domainLabel(d)}
            </div>
          ))}
        </div>
        <ShortlistButton id={r.id} slug={r.slug} name={r.name} vendor={r.vendor} small />
      </div>
    </article>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { BASE, agentHref, fetchIndex, fetchSearchDocs } from "../lib/data";
import { IDENTITY_WORD, badgeLabel, domainLabel, frameworkName, securityWord } from "../lib/labels";
import type { RequirementChip } from "../lib/intent";
import { Catalog, chipKey, isOpenSource, isSelfHostable, satisfies, type Filters, type Hit } from "../lib/search";
import type { CatalogIndex, IndexRecord, SearchDoc } from "../lib/types";
import ShortlistButton from "./ShortlistButton";

export interface SearchAppProps {
  index?: CatalogIndex | null;
  docs?: SearchDoc[];
  initialQuery?: string;
  syncUrl?: boolean;
  examples?: string[];
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

/** Facet presets, as in the mockup: the frameworks buyers ask for first and the tier that counts. */
const MUST_PRESETS: { label: string; chip: RequirementChip }[] = [
  { label: "HIPAA BAA", chip: { framework: "hipaa", variant: "BAA_AVAILABLE", min_tier: 4 } },
  { label: "SOC 2 Type II", chip: { framework: "soc2", variant: "SOC2_TYPE_II", min_tier: 2 } },
  { label: "ISO 27001", chip: { framework: "iso27001", variant: "ISO27001", min_tier: 2 } },
  { label: "FedRAMP", chip: { framework: "fedramp", min_tier: 1 } },
  { label: "GDPR / DPF", chip: { framework: "gdpr", min_tier: 1 } },
  { label: "CSA STAR", chip: { framework: "csa_star", min_tier: 1 } },
];
const PROTO_NAMES: Record<string, string> = { mcp: "Model Context Protocol (MCP)", a2a: "Agent2Agent (A2A)", ard: "Agentic Resource Discovery (ARD)" };
const SOURCE_NAMES: Record<string, string> = { aws_marketplace: "AWS Marketplace", github: "GitHub", huggingface: "Hugging Face", mcp_registry: "MCP Registry", ard: "ARD publisher", seed_xlsx: "Seed workbook", enterprise_scan: "Internal scan" };

export default function SearchApp(props: SearchAppProps) {
  const [index, setIndex] = useState<CatalogIndex | null | undefined>(props.index);
  const [docs, setDocs] = useState<SearchDoc[]>(props.docs ?? []);
  const [q, setQ] = useState(props.initialQuery ?? "");
  const [submitted, setSubmitted] = useState(props.initialQuery ?? "");
  const [filters, setFilters] = useState<Filters>({ strict: true });
  const [musts, setMusts] = useState<Set<string>>(new Set());
  const [drop, setDrop] = useState<Set<string>>(new Set());
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
      if (initial) {
        setQ(initial);
        setSubmitted(initial);
      }
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
    if (submitted) u.searchParams.set("q", submitted);
    else u.searchParams.delete("q");
    if (filters.domain) u.searchParams.set("domain", filters.domain);
    else u.searchParams.delete("domain");
    window.history.replaceState(null, "", u.toString());
  }, [submitted, filters.domain, syncUrl]);

  const catalog = useMemo(() => (index ? new Catalog(index.records, docs) : null), [index, docs]);
  const effective: Filters = useMemo(
    () => ({ ...filters, extra_must: MUST_PRESETS.filter((m) => musts.has(m.label)).map((m) => m.chip), drop: [...drop] }),
    [filters, musts, drop],
  );
  const result = useMemo(() => (catalog ? catalog.search(submitted, effective, 500) : null), [catalog, submitted, effective]);
  // facet counts over the current result set (before the rail's own hard filters would hide them)
  const pool = useMemo(() => (result ? result.hits.map((h) => h.record) : []), [result]);
  const counts = useMemo(() => {
    const c = {
      proto: { mcp: 0, a2a: 0, ard: 0, none: 0 },
      commercial: 0,
      open: 0,
      self: 0,
      sources: {} as Record<string, number>,
      must: {} as Record<string, number>,
      identity: { 1: 0, 2: 0, 3: 0, 4: 0 } as Record<number, number>,
    };
    for (const r of pool) {
      let any = false;
      for (const p of ["mcp", "a2a", "ard"] as const) {
        if (["verified", "claimed"].includes(r.protocols[p] ?? "")) {
          c.proto[p] += 1;
          any = true;
        }
      }
      if (!any) c.proto.none += 1;
      if (isOpenSource(r)) c.open += 1;
      else c.commercial += 1;
      if (isSelfHostable(r)) c.self += 1;
      for (const s of r.sources) c.sources[s] = (c.sources[s] ?? 0) + 1;
      for (const m of MUST_PRESETS) if (satisfies(r, m.chip)) c.must[m.label] = (c.must[m.label] ?? 0) + 1;
      for (let t = 1; t <= 4; t++) if (r.trust.identity <= t) c.identity[t] += 1;
    }
    return c;
  }, [pool]);
  const domains = useMemo(() => {
    const s = new Set<string>();
    for (const r of index?.records ?? []) for (const d of Object.keys(r.domains)) s.add(d);
    return [...s].sort((a, b) => domainLabel(a).localeCompare(domainLabel(b)));
  }, [index]);
  const types = useMemo(() => [...new Set((index?.records ?? []).map((r) => r.resource_type))].sort(), [index]);

  if (index === null) {
    return (
      <div className="notice warn">
        No catalog is available in this build. Run <code>agentdossier build</code> and rebuild the site, or open a private catalog under{" "}
        <a href={`${BASE}/private/`}>Private catalog</a>.
      </div>
    );
  }
  if (!index) {
    return (
      <div style={{ minHeight: "70vh" }}>
        <p className="muted">Loading catalog…</p>
      </div>
    );
  }

  const intent = result?.intent;
  const chips: { key: string; label: string; must?: boolean; prefer?: boolean }[] = [];
  if (intent) {
    for (const d of intent.domain) chips.push({ key: `domain:${d}`, label: `Domain: ${domainLabel(d)}` });
    for (const c of intent.capability) chips.push({ key: `capability:${c}`, label: `Capability: ${c.replace(/_/g, " ")}` });
    for (const d of intent.data_class) chips.push({ key: `data_class:${d}`, label: `Data class: ${d.toUpperCase()}` });
    for (const d of intent.deployment) chips.push({ key: `deployment:${d}`, label: d === "private" ? "Private deployment" : "SaaS" });
    for (const p of intent.protocol) chips.push({ key: `protocol:${p}`, label: `Protocol: ${p.toUpperCase()}` });
    for (const e of intent.ecosystem) chips.push({ key: `ecosystem:${e}`, label: `Ecosystem: ${e}` });
    for (const j of intent.jurisdiction) chips.push({ key: `jurisdiction:${j}`, label: `Jurisdiction: ${j}` });
    for (const t of intent.trust) chips.push({ key: `trust:${t}`, label: t.replace(/_/g, " ") });
    for (const c of intent.must_have) chips.push({ key: chipKey("must", c), label: `Must have: ${badgeLabel(c.framework, c.variant)}, tier ${c.min_tier}+`, must: true });
    for (const c of intent.prefer) chips.push({ key: chipKey("prefer", c), label: `Prefer: ${badgeLabel(c.framework, c.variant)}`, prefer: true });
  }
  const domainForScore = intent?.domain[0] ?? filters.domain ?? null;

  const exportRows = () =>
    (result?.hits ?? []).map((h) => ({
      id: h.record.id,
      name: h.record.name,
      vendor: h.record.vendor,
      type: h.record.resource_type,
      license: h.record.license,
      fit: h.score,
      explanation: h.explanation.join("; "),
      identity_tier: h.record.trust.identity,
      compliance_tier: h.record.trust.compliance,
      protocols: Object.entries(h.record.protocols).map(([p, s]) => `${p}:${s}`).join(" "),
      evidence: h.record.compliance_summary.filter((c) => c.status === "active").map((c) => `${badgeLabel(c.framework, c.variant)} T${c.tier}`).join("; "),
      domains: Object.entries(h.record.domains).map(([d, e]) => `${d}:${e.rank ?? "-"}:${e.score ?? "-"}`).join(" "),
      url: `${location.origin}${agentHref(h.record.slug)}`,
    }));
  const download = (name: string, body: string, type: string) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type }));
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const exportJson = () => download("agentdossier-results.json", JSON.stringify({ query: submitted, exported: new Date().toISOString(), catalog: { snapshot: index.snapshot_date, built: index.built_at }, results: exportRows() }, null, 2), "application/json");
  const exportCsv = () => {
    const rows = exportRows();
    const head = Object.keys(rows[0] ?? { id: "" });
    const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
    download("agentdossier-results.csv", [head.join(","), ...rows.map((r) => head.map((k) => esc((r as Record<string, unknown>)[k])).join(","))].join("\n"), "text/csv");
  };

  return (
    <div style={{ minHeight: "70vh" }}>
      <form
        className="searchbox"
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(q);
          setDrop(new Set());
          setLimit(10);
        }}
      >
        <label className="sr-only" htmlFor="q">
          Describe the agent you need
        </label>
        <input id="q" ref={inputRef} type="search" value={q} placeholder="Describe the agent you need, e.g. “insurance claims agent, handles PHI”" onChange={(e) => setQ(e.target.value)} autoComplete="off" />
        <button className="btn primary" type="submit">
          Search
        </button>
      </form>
      {!submitted && (
        <p className="muted small" style={{ marginTop: "0.6rem" }}>
          Parsed in your browser with rules, not a model. Nothing you type is sent anywhere. Try:{" "}
          {(props.examples ?? EXAMPLES).map((ex, i) => (
            <span key={ex}>
              {i > 0 && " · "}
              <a
                href="#"
                onClick={(e) => {
                  e.preventDefault();
                  setQ(ex);
                  setSubmitted(ex);
                  setDrop(new Set());
                }}
              >
                {ex}
              </a>
            </span>
          ))}
        </p>
      )}

      <div className="row" style={{ marginTop: "12px", fontSize: "0.85rem" }} aria-label="Derived requirements, editable">
        {chips.length > 0 && <span className="label">Derived requirements</span>}
        {chips.map((c) => (
          <button key={c.key} type="button" className={`chip${c.must ? " must" : c.prefer ? " prefer" : ""}`} title="remove this requirement" onClick={() => setDrop(new Set([...drop, c.key]))}>
            {c.label} <span aria-hidden="true">×</span>
            <span className="sr-only">remove</span>
          </button>
        ))}
        {result && (
          <span className="muted" style={{ marginLeft: chips.length ? "8px" : 0 }} aria-live="polite">
            {result.total} result{result.total === 1 ? "" : "s"}
            {domainForScore ? ` · showing ${domainLabel(domainForScore)} score · fit shown separately` : " · sorted by fit"}
            {result.excluded > 0 && !result.relaxed && ` · ${result.excluded} excluded by must-haves`}
          </span>
        )}
        {result && result.hits.length > 0 && (
          <span style={{ marginLeft: "auto" }} className="row">
            <button type="button" className="btn link small" onClick={exportCsv}>
              Export CSV
            </button>
            <button type="button" className="btn link small" onClick={exportJson}>
              JSON
            </button>
          </span>
        )}
      </div>
      {result && result.relaxed && (
        <p className="notice warn small" style={{ marginTop: "12px" }}>
          No agent in this catalog has evidence for {result.intent.must_have.map((c) => badgeLabel(c.framework, c.variant)).join(" and ")} in the sources checked. Showing the closest
          matches with the gap flagged; ask the vendor for the document before relying on it.
        </p>
      )}

      <div className="search-layout">
        <aside className="facets" aria-label="Filters">
          <div className="facet">
            <span className="label">Must have compliance</span>
            {MUST_PRESETS.map((m) => (
              <label key={m.label}>
                <span>
                  <input type="checkbox" checked={musts.has(m.label)} onChange={(e) => {
                    const next = new Set(musts);
                    if (e.target.checked) next.add(m.label);
                    else next.delete(m.label);
                    setMusts(next);
                  }} />
                  {m.label}
                </span>
                <span className="count">
                  min T{m.chip.min_tier} · {counts.must[m.label] ?? 0}
                </span>
              </label>
            ))}
            {intent && intent.must_have.length > 0 && (
              <label style={{ marginTop: "6px" }}>
                <span>
                  <input type="checkbox" checked={filters.strict !== false} onChange={(e) => setFilters({ ...filters, strict: e.target.checked })} />
                  enforce must-haves
                </span>
              </label>
            )}
          </div>
          <div className="facet">
            <span className="label">Publisher</span>
            <div className="seg" role="group" aria-label="Minimum publisher confidence">
              {[2, 3, 4].map((t) => (
                <button key={t} type="button" aria-pressed={(filters.identity_max_tier ?? 4) === t} onClick={() => setFilters({ ...filters, identity_max_tier: t === 4 ? undefined : t })} title={`${counts.identity[t]} publisher ${IDENTITY_WORD[t as 2 | 3 | 4]} or better`}>
                  {t === 4 ? "any" : IDENTITY_WORD[t as 2 | 3]}
                </button>
              ))}
            </div>
            <div className="tiny muted" style={{ marginTop: "6px" }}>Hard filter on how firmly the publisher is identified</div>
          </div>
          <div className="facet">
            <span className="label">Protocol status</span>
            {(["mcp", "a2a", "ard"] as const).map((p) => (
              <label key={p}>
                <span>
                  <input type="checkbox" checked={filters.protocol === p} onChange={(e) => setFilters({ ...filters, protocol: e.target.checked ? p : undefined })} />
                  {PROTO_NAMES[p]} observed
                </span>
                <span className="count">{counts.proto[p]}</span>
              </label>
            ))}
            <div className="line">
              <span>None found</span>
              <span className="count">{counts.proto.none}</span>
            </div>
          </div>
          <div className="facet">
            <span className="label">Type · License · Deployment</span>
            <label>
              <span>
                <input type="checkbox" checked={filters.license === "commercial"} onChange={(e) => setFilters({ ...filters, license: e.target.checked ? "commercial" : undefined })} />
                Commercial
              </span>
              <span className="count">{counts.commercial}</span>
            </label>
            <label>
              <span>
                <input type="checkbox" checked={filters.license === "open_source"} onChange={(e) => setFilters({ ...filters, license: e.target.checked ? "open_source" : undefined })} />
                Open source
              </span>
              <span className="count">{counts.open}</span>
            </label>
            <label>
              <span>
                <input type="checkbox" checked={!!filters.self_hostable} onChange={(e) => setFilters({ ...filters, self_hostable: e.target.checked ? true : undefined })} />
                Private / VPC deployable
              </span>
              <span className="count">{counts.self}</span>
            </label>
            {Object.entries(counts.sources)
              .filter(([s]) => s !== "seed_xlsx")
              .sort()
              .map(([s, n]) => (
                <label key={s}>
                  <span>
                    <input type="checkbox" checked={filters.source === s} onChange={(e) => setFilters({ ...filters, source: e.target.checked ? s : undefined })} />
                    Source: {SOURCE_NAMES[s] ?? s}
                  </span>
                  <span className="count">{n}</span>
                </label>
              ))}
            <select aria-label="Resource type" value={filters.resource_type ?? ""} onChange={(e) => setFilters({ ...filters, resource_type: e.target.value || undefined })} style={{ marginTop: "8px", width: "100%" }}>
              <option value="">All types</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {t.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </div>
          <div className="facet">
            <span className="label">Domain</span>
            <select aria-label="Domain" value={filters.domain ?? ""} onChange={(e) => setFilters({ ...filters, domain: e.target.value || undefined })} style={{ width: "100%" }}>
              <option value="">Any domain</option>
              {domains.map((d) => (
                <option key={d} value={d}>
                  {domainLabel(d)}
                </option>
              ))}
            </select>
          </div>
        </aside>

        <div className="results">
          {result?.hits.slice(0, limit).map((h) => (
            <Result key={h.record.id} hit={h} domain={domainForScore} linkAgents={linkAgents} expanded={expanded === h.record.id} onToggle={() => setExpanded(expanded === h.record.id ? null : h.record.id)} />
          ))}
          {result && result.hits.length === 0 && <p className="muted">Nothing matches. Remove a chip or loosen a filter.</p>}
          {result && result.hits.length > limit && (
            <p>
              <button className="btn" type="button" onClick={() => setLimit(limit + 10)}>
                Show more ({result.hits.length - limit} left)
              </button>
            </p>
          )}
        </div>
      </div>
      <p className="tiny muted" style={{ borderTop: "2px solid var(--rule)", padding: "10px 0", marginTop: "32px" }}>
        Reference implementation. Scores are comparative discovery signals, not certification. Data as of {index.built_at.slice(0, 10)}; ranking snapshot {index.snapshot_date}.
      </p>
    </div>
  );
}

function tierRange(r: IndexRecord): string {
  const tiers = r.compliance_summary.filter((c) => c.status === "active").map((c) => c.tier);
  if (!tiers.length) return "T5";
  const lo = Math.min(...tiers);
  const hi = Math.max(...tiers);
  return lo === hi ? `T${lo}` : `T${lo}–T${hi}`;
}

function protoGlyphs(r: IndexRecord): string {
  const g = (s: string | undefined) => (s === "verified" ? "✔" : s === "claimed" ? "○" : s === "unknown" || !s ? "?" : "–");
  return `MCP ${g(r.protocols.mcp)} A2A ${g(r.protocols.a2a)} ARD ${g(r.protocols.ard)}`;
}

function Result({ hit, domain, linkAgents, expanded, onToggle }: { hit: Hit; domain: string | null; linkAgents: boolean; expanded: boolean; onToggle: () => void }) {
  const r = hit.record;
  const entry = domain ? r.domains[domain] : null;
  const best = !entry
    ? Object.entries(r.domains)
        .filter(([, e]) => e.rank)
        .sort((a, b) => (a[1].rank ?? 999) - (b[1].rank ?? 999))[0]
    : null;
  const active = r.compliance_summary.filter((c) => c.status === "active").sort((a, b) => a.tier - b.tier);
  const shown = active.slice(0, 3);
  const missingPreset = MUST_PRESETS.find((m) => !satisfies(r, m.chip) && hit.missing.some((x) => x.framework === m.chip.framework))
    ?? (active.length < 3 ? MUST_PRESETS.find((m) => !active.some((c) => c.framework === m.chip.framework)) : undefined);
  const kind = r.license && /commercial|proprietary|service/i.test(r.license) ? "commercial" : isOpenSource(r) ? "open source" : r.resource_type.replace(/_/g, " ");
  const bigScore = entry?.score ?? best?.[1].score ?? null;
  return (
    <article className="result">
      <div>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <div className="eyebrow">
              {entry ? `${domainLabel(domain!)} · #${entry.rank ?? "–"} of 100` : best ? `${domainLabel(best[0])} · #${best[1].rank} of 100` : r.resource_type.replace(/_/g, " ")}
              {" · "}
              {kind}
            </div>
            <h3>{linkAgents ? <a href={agentHref(r.slug)}>{r.name}</a> : <button type="button" className="btn link" onClick={onToggle}>{r.name}</button>}</h3>
            <div className="small muted">
              {r.vendor}
              {r.deployment ? ` · ${r.deployment}` : ""}
            </div>
          </div>
          <div className="score">
            <div className="n">{bigScore != null ? Math.round(bigScore) : Math.round(hit.score)}</div>
            <div className="tiny muted" style={{ marginTop: "4px" }}>
              {bigScore != null ? "domain score" : "fit"} · fit {Math.round(hit.score)}
            </div>
          </div>
        </div>
        <p className="why">
          {r.description ? `${r.description} ` : ""}
          {hit.explanation.length > 0 && <span className="muted">{hit.explanation.join(" · ")}.</span>}
          {hit.missing.map((m) => (
            <span key={m.framework + (m.variant ?? "")} style={{ color: "var(--danger)" }}>
              {" "}
              No evidence for {badgeLabel(m.framework, m.variant)}.
            </span>
          ))}
        </p>
        <div className="badges">
          {shown.map((c, i) => (
            <span key={c.framework + (c.variant ?? "")} className={`badge${i === 0 ? " strong" : ""}`} title={c.credited === false ? "pending publisher verification" : undefined}>
              {badgeLabel(c.framework, c.variant)} · T{c.tier}
              {c.credited === false ? " (pending)" : ""}
            </span>
          ))}
          {active.length > 3 && <span className="badge">+{active.length - 3} more</span>}
          {missingPreset && (
            <span className="badge" style={{ color: "var(--muted)" }}>
              {frameworkName(missingPreset.chip.framework)}: no evidence found
            </span>
          )}
        </div>
        {expanded && !linkAgents && (
          <dl className="facts" style={{ marginTop: "0.75rem" }}>
            <dt>Domains</dt>
            <dd>{Object.entries(r.domains).map(([d, e]) => `${domainLabel(d)}${e.rank ? ` #${e.rank}` : ""}`).join(", ") || "—"}</dd>
            <dt>Evidence</dt>
            <dd>{active.length ? active.map((c) => `${badgeLabel(c.framework, c.variant)} T${c.tier}${c.variant ? "" : ""}`).join(", ") : "none found"}</dd>
            <dt>Sources</dt>
            <dd>{r.sources.join(", ")}</dd>
          </dl>
        )}
      </div>
      <div className="trust">
        <span className="label" style={{ marginBottom: "6px" }}>Trust profile</span>
        <div className="line"><span>Publisher</span><b>{IDENTITY_WORD[r.trust.identity as 1 | 2 | 3 | 4 | 5]}</b></div>
        <div className="line"><span>Compliance</span><b>{tierRange(r)}</b></div>
        <div className="line"><span>Security</span><b>{securityWord(null, r.trust.security)}</b></div>
        <div className="line"><span>Protocols</span><b>{protoGlyphs(r)}</b></div>
        <div className="line"><span>Issues linked</span><b>{r.trust.issues == null ? "–" : r.trust.issues === 1 ? "0" : "some"}</b></div>
        <div className="actions">
          {linkAgents ? (
            <a href={agentHref(r.slug)} style={{ fontWeight: 800 }}>
              Trust profile →
            </a>
          ) : (
            <button type="button" className="btn link" onClick={onToggle}>
              {expanded ? "Less" : "Details"}
            </button>
          )}
          <a href={`${BASE}/compare/?ids=${r.slug}`}>+ Compare</a>
          <ShortlistButton id={r.id} slug={r.slug} name={r.name} vendor={r.vendor} small />
        </div>
      </div>
    </article>
  );
}


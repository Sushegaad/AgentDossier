import { useEffect, useState } from "react";
import { BASE, fetchResourceByIdOrSlug } from "../lib/data";
import {
  IDENTITY_EVIDENCE,
  IDENTITY_LABEL,
  NEWS_TAG_LABEL,
  RISK_TAGS,
  TIER_LABEL,
  domainLabel,
  fmtDate,
  frameworkName,
  protocolLabel,
  sourceLabel,
  variantLabel,
} from "../lib/labels";
import type { Resource, Tier } from "../lib/types";
import ShortlistButton from "./ShortlistButton";
import TrustStrip from "./TrustStrip";

const COMPS = ["adoption", "trust", "health", "ecosystem", "domain_fit", "governance", "docs"];
const COMP_MAX: Record<string, number> = { adoption: 30, trust: 25, health: 20, ecosystem: 15, domain_fit: 100, governance: 100, docs: 10 };

/** The trust profile. Rendered statically for the public demo (resource prop) and
 *  client-side for self-hosted instances whose catalog changes with every scan (id prop). */
export default function AgentProfile({ resource, id }: { resource?: Resource; id?: string }) {
  const [res, setRes] = useState<Resource | null | undefined>(resource);
  useEffect(() => {
    if (resource) return;
    const ident = id ?? new URL(window.location.href).searchParams.get("id");
    if (!ident) {
      setRes(null);
      return;
    }
    fetchResourceByIdOrSlug(ident).then(setRes);
  }, [resource, id]);
  if (res === undefined) return <p className="muted">Loading dossier…</p>;
  if (res === null) return <p className="notice warn">No such agent in this catalog.</p>;

  const domains = Object.entries(res.domains ?? {}).sort((a, b) => (a[1].rank ?? 999) - (b[1].rank ?? 999));
  const compliance = [...(res.compliance ?? [])].sort((a, b) => a.tier - b.tier || a.framework.localeCompare(b.framework));
  const active = compliance.filter((c) => c.status === "active");
  const bestTier = active.length ? (Math.min(...active.map((c) => c.tier)) as Tier) : null;
  const issues = res.issues;
  const news = res.news ?? [];
  const protocols = Object.entries(res.protocols ?? {});
  const cves = issues?.links.filter((l) => l.kind === "cve") ?? [];
  const risk = issues?.links.filter((l) => l.kind !== "cve") ?? [];
  const checked = !!(res.news_checked || res.security);
  const link = res.url ? (/^https?:/.test(res.url) ? res.url : `https://${res.url}`) : null;

  return (
    <article>
      <header className="row" style={{ justifyContent: "space-between", alignItems: "flex-start", marginBottom: "1rem" }}>
        <div>
          <h1>{res.name}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {res.vendor}
            {res.category && <> · {res.category}</>} · {res.resource_type.replace(/_/g, " ")}
            {res.license && <> · {res.license}</>}
            {link && (
              <>
                {" · "}
                <a href={link} rel="noopener">
                  {res.publisher_domain ?? res.url}
                </a>
              </>
            )}
            {res.scope === "private" && <> · <span className="badge">private · {res.tenant}</span></>}
          </p>
          {res.description && <p style={{ margin: "0.5rem 0 0", maxWidth: "70ch" }}>{res.description}</p>}
        </div>
        <div className="row">
          <ShortlistButton id={res.id} slug={res.slug} name={res.name} vendor={res.vendor} />
          <a className="btn" href={`${BASE}/compare/?ids=${res.slug}`}>
            Compare
          </a>
        </div>
      </header>

      <section className="card">
        <h2 style={{ marginTop: 0 }}>Trust profile</h2>
        <TrustStrip trust={res.trust} />
        <dl className="facts" style={{ marginTop: "0.75rem" }}>
          <dt>Identity</dt>
          <dd>
            T{res.identity.tier} · {IDENTITY_LABEL[res.identity.tier]}
            {res.identity.evidence.length > 0 && <span className="muted"> — {res.identity.evidence.map((e) => IDENTITY_EVIDENCE[e] ?? e).join("; ")}</span>}
            {res.identity.verified_by && (
              <span className="muted">
                {" "}
                (checked by {res.identity.verified_by} on {res.identity.verified_on})
              </span>
            )}
          </dd>
          <dt>Evidence</dt>
          <dd>{bestTier ? `${active.length} active record${active.length === 1 ? "" : "s"}; best tier T${bestTier} (${TIER_LABEL[bestTier]})` : "no compliance evidence found in the sources checked"}</dd>
          <dt>Security</dt>
          <dd>{res.security ? `${res.security.cves} CVE${res.security.cves === 1 ? "" : "s"} matching the product name in NVD (checked ${fmtDate(res.security.checked_at)})` : "not checked in this build"}</dd>
          <dt>Protocols</dt>
          <dd>{protocols.map(([p, b]) => `${p.toUpperCase()}: ${protocolLabel(b.status)}`).join(" · ") || "not checked"}</dd>
          <dt>Issues</dt>
          <dd>
            {issues && checked
              ? issues.links.length
                ? `${issues.incidents} incident${issues.incidents === 1 ? "" : "s"}, ${issues.cves} CVE${issues.cves === 1 ? "" : "s"}, ${issues.regulator_actions} regulator action${issues.regulator_actions === 1 ? "" : "s"} — see below`
                : "none found in news or NVD"
              : "not checked in this build"}
          </dd>
        </dl>
        {res.identity.tier > 2 && active.length > 0 && (
          <p className="notice warn small" style={{ margin: "0.75rem 0 0" }}>
            Evidence is shown but <strong>not credited</strong> in the evidence-based governance score until the publisher's identity reaches tier 2 (an ARD
            manifest or A2A card on the vendor's domain, a marketplace listing, or a maintainer-verified publisher domain). A certificate that belongs to a
            company is only credited to an agent once we know the agent is that company's.
          </p>
        )}
      </section>

      <div className="grid two" style={{ marginTop: "1rem" }}>
        <div>
          <section className="card">
            <h2 style={{ marginTop: 0 }}>Compliance evidence</h2>
            {compliance.length === 0 ? (
              <p className="muted">
                No evidence found in the FedRAMP Marketplace, the CSA STAR Registry, curated records or the vendor's own trust pages as of this build. Absence of
                evidence is not evidence of absence; ask the vendor.
              </p>
            ) : (
              <ul className="evidence" style={{ paddingLeft: 0, listStyle: "none", margin: 0 }}>
                {compliance.map((c) => (
                  <li key={c.framework + (c.variant ?? "")} className="row" style={{ alignItems: "flex-start", padding: "0.5rem 0", borderBottom: "1px solid var(--border)" }}>
                    <span className={`tier${c.credited === false && c.status === "active" ? " pending" : ""}`} data-tier={c.tier} title={TIER_LABEL[c.tier]}>
                      T{c.tier}
                    </span>
                    <div style={{ flex: "1 1 260px" }}>
                      <div>
                        <strong>{frameworkName(c.framework)}</strong>
                        {c.variant && <> · {variantLabel(c.variant)}</>}
                        {c.status !== "active" && (
                          <span className="badge warn" style={{ marginLeft: "0.4rem" }}>
                            {c.status.replace(/_/g, " ")}
                          </span>
                        )}
                      </div>
                      <div className="small">{c.display}</div>
                      <div className="muted small">
                        <a href={c.evidence_url} rel="noopener">
                          evidence
                        </a>{" "}
                        · {sourceLabel(c.source)} · scope {c.scope}
                        {c.issuer && <> · issuer {c.issuer}</>}
                        {c.valid_until && <> · valid to {c.valid_until}</>}
                        {c.period_end && <> · period end {c.period_end}</>}
                        {c.match_confidence != null && c.match_confidence < 1 && <> · match {Math.round(c.match_confidence * 100)}%</>}
                        {c.next_check && <> · next check {c.next_check}</>}
                        {c.reviewer && <> · reviewed by {c.reviewer}</>}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted small" style={{ margin: "0.75rem 0 0" }}>
              T1 registry-matched · T2 marketplace-listed · T3 document-evidenced · T4 vendor-claimed. Dashed badges are pending publisher verification.{" "}
              <a href={`${BASE}/methodology/#evidence-tiers`}>How tiers work</a>.
            </p>
          </section>

          <section className="card" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>News and chatter</h2>
            {!res.news_checked ? (
              <p className="muted">Not checked in this build.</p>
            ) : news.length === 0 ? (
              <p className="muted">Nothing linked with confidence ≥ 0.85 in the last 90 days from Hacker News, GDELT, GitHub releases or the vendor's feed.</p>
            ) : (
              <ul style={{ paddingLeft: 0, listStyle: "none", margin: 0 }}>
                {news.map((n) => (
                  <li key={n.url} style={{ padding: "0.45rem 0", borderBottom: "1px solid var(--border)" }}>
                    <span className={`badge${RISK_TAGS.has(n.tag) ? " danger" : ""}`}>{NEWS_TAG_LABEL[n.tag] ?? n.tag}</span>{" "}
                    <a href={n.url} rel="noopener">
                      {n.headline}
                    </a>
                    <div className="muted small">
                      {n.outlet} · {fmtDate(n.date)} · {n.kind}
                      {n.cluster_size && n.cluster_size > 1 && <> · also in {n.cluster_size - 1} other outlet{n.cluster_size > 2 ? "s" : ""}</>}
                      {n.engagement != null && <> · {n.engagement} points+comments</>}
                      {n.discussion_url && (
                        <>
                          {" · "}
                          <a href={n.discussion_url} rel="noopener">
                            discussion
                          </a>
                        </>
                      )}
                      {" · link confidence "}
                      {n.link_confidence}
                    </div>
                    {n.summary && <div className="small">{n.summary}</div>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <div>
          <section className="card">
            <h2 style={{ marginTop: 0 }}>Rankings</h2>
            {domains.length === 0 ? (
              <p className="muted">Not ranked; discovered by a connector or scan.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>#</th>
                    <th>Score</th>
                    <th title="evidence-based governance, sar-score-1.1">Gov. evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {domains.map(([d, e]) => (
                    <tr key={d}>
                      <td>
                        <a href={`${BASE}/domains/${d}/`}>{domainLabel(d)}</a>
                      </td>
                      <td>{e.rank ?? "–"}</td>
                      <td>{e.score?.toFixed(1) ?? "–"}</td>
                      <td>{e.governance_evidence?.value != null ? e.governance_evidence.value.toFixed(0) : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {res.components && (
              <>
                <h3 style={{ marginTop: "1rem" }}>Score components</h3>
                <dl className="facts">
                  {COMPS.filter((k) => res.components && k in res.components).map((k) => {
                    const v = res.components?.[k];
                    return (
                      <div key={k} style={{ display: "contents" }}>
                        <dt>{k.replace(/_/g, " ")}</dt>
                        <dd>
                          {v == null ? (
                            <span className="muted">unknown (counts as 0)</span>
                          ) : (
                            <>
                              {v} / {COMP_MAX[k]}
                              <div className="meter" aria-hidden="true">
                                <span style={{ width: `${Math.min(100, (100 * v) / COMP_MAX[k])}%` }}></span>
                              </div>
                            </>
                          )}
                        </dd>
                      </div>
                    );
                  })}
                </dl>
              </>
            )}
          </section>

          <section className="card" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Protocols</h2>
            <dl className="facts">
              {protocols.map(([p, b]) => (
                <div key={p} style={{ display: "contents" }}>
                  <dt>{p.toUpperCase()}</dt>
                  <dd>
                    {protocolLabel(b.status)}
                    {b.card_url && (
                      <>
                        {" · "}
                        <a href={String(b.card_url)} rel="noopener">
                          agent card
                        </a>
                      </>
                    )}
                    {b.manifest_url && (
                      <>
                        {" · "}
                        <a href={String(b.manifest_url)} rel="noopener">
                          manifest
                        </a>
                      </>
                    )}
                    {b.endpoint && <> · <code>{String(b.endpoint)}</code></>}
                    {b.version && <> · v{String(b.version)}</>}
                    {b.tools != null && <> · {String(b.tools)} tools</>}
                    {b.checked_at && <span className="muted"> · checked {fmtDate(String(b.checked_at))}</span>}
                    {b.error && <span className="muted"> · {String(b.error)}</span>}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="muted small" style={{ margin: "0.5rem 0 0" }}>
              Verified = fetched and parsed from the publisher's domain; claimed = declared by a source but not fetched.
            </p>
          </section>

          <section className="card" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Security and issues</h2>
            {!issues || !checked ? (
              <p className="muted">Not checked in this build.</p>
            ) : (
              <>
                <dl className="facts">
                  <dt>CVEs (NVD)</dt>
                  <dd>{res.security ? res.security.cves : "not checked"}</dd>
                  <dt>Incidents</dt>
                  <dd>{issues.incidents}</dd>
                  <dt>Regulator actions</dt>
                  <dd>{issues.regulator_actions}</dd>
                </dl>
                {cves.length > 0 && (
                  <ul className="small">
                    {cves.slice(0, 10).map((l) => (
                      <li key={l.url}>
                        <a href={l.url} rel="noopener">
                          {l.title}
                        </a>{" "}
                        <span className="muted">{l.date}</span>
                      </li>
                    ))}
                  </ul>
                )}
                {risk.length > 0 && (
                  <ul className="small">
                    {risk.map((l) => (
                      <li key={l.url}>
                        <span className="badge danger">{NEWS_TAG_LABEL[l.kind] ?? l.kind}</span>{" "}
                        <a href={l.url} rel="noopener">
                          {l.title}
                        </a>{" "}
                        <span className="muted">{l.date}</span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="muted small" style={{ margin: "0.5rem 0 0" }}>
                  CVE counts come from a keyword search on the product name and can include unrelated products with similar names.
                </p>
              </>
            )}
          </section>

          <section className="card" style={{ marginTop: "1rem" }}>
            <h2 style={{ marginTop: 0 }}>Provenance</h2>
            <dl className="facts">
              <dt>Sources</dt>
              <dd>
                {res.sources.map((s, i) => (
                  <div key={i}>
                    {sourceLabel(s.system)}
                    {s.url && (
                      <>
                        {" · "}
                        <a href={s.url} rel="noopener">
                          link
                        </a>
                      </>
                    )}
                    {s.payload_hash && (
                      <span className="muted">
                        {" · "}
                        <code title={s.payload_hash}>{s.payload_hash.slice(0, 12)}…</code>
                      </span>
                    )}
                  </div>
                ))}
              </dd>
              {res.first_seen && (
                <>
                  <dt>First seen</dt>
                  <dd>{fmtDate(res.first_seen)}</dd>
                </>
              )}
              {res.merged_ids && res.merged_ids.length > 0 && (
                <>
                  <dt>Merged</dt>
                  <dd>
                    {res.merged_ids.length} duplicate record{res.merged_ids.length === 1 ? "" : "s"}
                  </dd>
                </>
              )}
              <dt>ID</dt>
              <dd>
                <code>{res.id}</code>
              </dd>
              <dt>Data</dt>
              <dd>
                <a href={`${BASE}/catalog/agents/${res.id}.json`}>JSON</a>
              </dd>
            </dl>
          </section>
        </div>
      </div>
      <p className="notice small" style={{ marginTop: "1.5rem" }}>
        {res.disclaimer ?? "Compliance information is compiled from the sources shown as of the date shown. It is not an assessment, certification, legal opinion or recommendation."}{" "}
        Something wrong? <a href="https://github.com/Sushegaad/AgentDossier/issues/new">Open a correction</a>.
      </p>
    </article>
  );
}

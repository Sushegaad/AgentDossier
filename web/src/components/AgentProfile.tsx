import { useEffect, useState } from "react";
import { BASE, fetchResourceByIdOrSlug } from "../lib/data";
import { COMPONENT_LABELS, COMPONENT_MAX, DOMAIN_PROFILES, PROFILES, bestDomain, checklist, evidenceRows, gdprPanel, protocolLines, provenance, tierCounts, tierRange, type Mark } from "../lib/dossier";
import { IDENTITY_EVIDENCE, IDENTITY_LABEL, NEWS_TAG_LABEL, RISK_TAGS, domainLabel, fmtDate, frameworkName, variantLabel } from "../lib/labels";
import type { Resource } from "../lib/types";
import ShortlistButton from "./ShortlistButton";

const MARK: Record<Mark | "you", { glyph: string; color: string }> = {
  found: { glyph: "✔", color: "var(--ink)" },
  claimed: { glyph: "○", color: "var(--ink)" },
  missing: { glyph: "–", color: "var(--muted)" },
  issue: { glyph: "⚠", color: "var(--danger)" },
  you: { glyph: "☐", color: "var(--accent-ink)" },
};

/** The dossier (mockup 1g). Static for the public demo (resource prop), client-rendered on self-hosted instances (id from the URL). */
export default function AgentProfile({ resource, id, shortlist = "island" }: { resource?: Resource; id?: string; shortlist?: "island" | "static" }) {
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

  const best = bestDomain(res);
  const others = Object.entries(res.domains ?? {})
    .filter(([d, e]) => e.rank && d !== best?.[0])
    .sort((a, b) => (a[1].rank ?? 999) - (b[1].rank ?? 999))
    .slice(0, 3);
  const rows = evidenceRows(res);
  const gdpr = gdprPanel(res);
  const checks = checklist(res);
  const prov = provenance(res);
  const protoLines = protocolLines(res);
  const protoCount = `${protoLines.filter((l) => ["verified", "claimed"].includes(l.status)).length} / 3`;
  const news = res.news ?? [];
  const issues = res.issues;
  const checked = !!(res.news_checked || res.security);
  const link = res.url ? (/^https?:/.test(res.url) ? res.url : `https://${res.url}`) : null;
  const kind = res.license && /commercial|proprietary|service/i.test(res.license) ? "commercial" : res.license ? res.license : res.resource_type.replace(/_/g, " ");
  const profileName = best ? (DOMAIN_PROFILES[best[0]] ?? best[1].profile ?? "general") : "general";
  const weights = PROFILES[profileName] ?? PROFILES.general;
  const comps = res.components ?? (best?.[1] as { components?: Record<string, number | null> })?.components ?? null;
  const asOf = (res.compliance?.[0]?.retrieved_at ?? res.last_seen ?? res.first_seen ?? "").slice(0, 10);
  const jurisdictions = new Set<string>();
  for (const c of res.compliance ?? []) {
    if (["fedramp", "hipaa", "hitrust", "nist_ai_rmf"].includes(c.framework)) jurisdictions.add("US");
    if (["gdpr", "eu_ai_act"].includes(c.framework)) jurisdictions.add("EU");
    if (["uk_gdpr", "cyber_essentials", "uk_us_data_bridge"].includes(c.framework)) jurisdictions.add("UK");
  }

  return (
    <article>
      <div className="row small muted" style={{ justifyContent: "space-between", padding: "4px 0 12px" }}>
        <span>
          {best ? (
            <>
              <a href={`${BASE}/domains/${best[0]}/`} style={{ color: "var(--muted)" }}>
                {domainLabel(best[0])} Top 100
              </a>{" "}
              / #{best[1].rank ?? "–"}
            </>
          ) : (
            <>Discovered resource</>
          )}
          {res.scope === "private" && <> · private catalog{res.tenant ? ` · ${res.tenant}` : ""}</>}
        </span>
        <span>ARD = Agentic Resource Discovery · A2A = Agent2Agent · MCP = Model Context Protocol</span>
      </div>

      <header className="split" style={{ borderBottom: "2px solid var(--ink)", paddingBottom: "32px" }}>
        <div>
          <div className="eyebrow">
            {res.category ?? res.resource_type.replace(/_/g, " ")} · {kind}
            {res.deployment ? ` · ${res.deployment}` : ""}
          </div>
          <h1 style={{ marginTop: "6px", fontSize: "clamp(2rem, 4.5vw, 3rem)" }}>{res.name}</h1>
          <p className="body" style={{ marginTop: "14px", maxWidth: "60ch", fontSize: "1.05rem" }}>
            {res.description ?? ""} {res.vendor && <>Publisher: {res.vendor}.</>}
            {others.length > 0 && <> Also ranked in {others.map(([d, e]) => `${domainLabel(d)} (#${e.rank})`).join(", ")}.</>}
          </p>
          <div className="row" style={{ marginTop: "20px", gap: "12px" }}>
            {link && (
              <a className="btn primary" href={link} rel="noopener">
                Vendor page ↗
              </a>
            )}
            <a className="btn" href={`${BASE}/compare/?ids=${res.slug}`}>
              + Compare
            </a>
            {shortlist === "island" ? (
              <ShortlistButton id={res.id} slug={res.slug} name={res.name} vendor={res.vendor} />
            ) : (
              // the public dossier ships no React at all; a tiny script in the page wires this button
              <button type="button" className="btn" data-shortlist-id={res.id} data-slug={res.slug} data-name={res.name} data-vendor={res.vendor ?? ""} aria-pressed="false">
                ☆ Shortlist
              </button>
            )}
            <a className="btn" href={`${BASE}/catalog/agents/${res.id}.json`}>
              Export JSON
            </a>
          </div>
        </div>
        <div style={{ borderTop: "2px solid var(--rule)" }}>
          <div className="row" style={{ justifyContent: "space-between", padding: "12px 0 8px" }}>
            <span className="label">Trust profile</span>
            <span className="tiny muted">as of {asOf || "this build"}</span>
          </div>
          <TrustRow k="Identity" v={<>T{res.identity.tier} · {IDENTITY_LABEL[res.identity.tier]}{res.identity.evidence.length > 0 && <span className="muted"> — {res.identity.evidence.map((e) => IDENTITY_EVIDENCE[e] ?? e).join("; ")}</span>}</>} t={`T${res.identity.tier}`} />
          <TrustRow k="Compliance" v={tierCounts(res)} t={tierRange(res)} />
          <TrustRow k="Security" v={res.security ? `${res.security.cves === 0 ? "No CVE naming this product in NVD" : `${res.security.cves} CVE${res.security.cves === 1 ? "" : "s"} matching the product name in NVD`} · checked ${fmtDate(res.security.checked_at)}` : "Not checked in this build"} t={res.security ? `T${res.security.tier}` : "–"} />
          <TrustRow
            k="Protocols"
            v={
              <span style={{ display: "grid", gap: "2px" }}>
                {protoLines.map((l) => (
                  <span key={l.key}>
                    {l.name} <b>{l.word}</b>
                    {l.why && <span className="muted"> — {l.why}</span>}
                    {l.evidenceUrl && (
                      <>
                        {" "}
                        <a href={l.evidenceUrl} rel="noopener">source</a>
                      </>
                    )}
                  </span>
                ))}
              </span>
            }
            t={protoCount}
          />
          <TrustRow k="Issues found" v={issues && checked ? `${issues.regulator_actions} regulator actions · ${issues.incidents} incidents · ${issues.withdrawn_certificates} withdrawn certificates · ${issues.cves} CVEs` : "Not checked in this build"} t="links only" last />
          {res.identity.tier > 2 && rows.some((r) => r.mark !== "missing") && (
            <p className="tiny muted" style={{ marginTop: "10px" }}>
              Evidence is shown but not credited in the governance score until the publisher's identity reaches T2 (ARD manifest or A2A card on the vendor's domain, marketplace listing, or a maintainer-verified domain).
            </p>
          )}
        </div>
      </header>

      <div className="split" style={{ marginTop: "32px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "40px" }}>
          <section>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginBottom: "12px" }}>
              <h2 style={{ fontSize: "1.5rem" }}>Compliance evidence</h2>
              <span className="tiny muted">
                {jurisdictions.size ? `Jurisdiction: ${[...jurisdictions].join(" + ")} · ` : ""}
                {rows.length} framework{rows.length === 1 ? "" : "s"} shown
              </span>
            </div>
            <div className="ledger">
              {rows.map((r) => (
                <div key={r.framework + (r.variant ?? "") + r.mark} className="ledger-row" style={{ gridTemplateColumns: "22px 150px 1fr 150px" }}>
                  <span style={{ fontWeight: 800, color: MARK[r.mark].color }} aria-label={r.mark}>
                    {MARK[r.mark].glyph}
                  </span>
                  <div>
                    <div style={{ fontWeight: 800 }}>
                      {frameworkName(r.framework)}
                      {r.variant && <span style={{ fontWeight: 400 }}> · {variantLabel(r.variant)}</span>}
                    </div>
                    <div className="tiny muted">{r.tierLabel}</div>
                  </div>
                  <div>
                    <div>{r.status}</div>
                    <div className="tiny muted">
                      Scope: {r.scope} ·{" "}
                      {r.sourceUrl ? (
                        <a href={r.sourceUrl} rel="noopener">
                          {r.source}
                        </a>
                      ) : (
                        r.source
                      )}
                      {r.asOf && <> · {r.asOf}</>}
                      {r.record?.match_confidence != null && r.record.match_confidence < 1 && <> · match {Math.round(r.record.match_confidence * 100)}%</>}
                      {r.record?.reviewer && <> · reviewed by {r.record.reviewer}</>}
                    </div>
                  </div>
                  <div className="tiny muted" style={{ textAlign: "right" }}>
                    {r.right}
                  </div>
                </div>
              ))}
            </div>
            <div className="row tiny muted" style={{ justifyContent: "space-between", marginTop: "10px" }}>
              <span>✔ found · ○ claimed · – not found · ⚠ expired, stale or revoked. Every row links to its source.</span>
              <a href="https://github.com/Sushegaad/AgentDossier/issues/new">Request a correction on GitHub</a>
            </div>
          </section>

          <section>
            <h2 style={{ fontSize: "1.5rem", marginBottom: "12px" }}>GDPR, assembled from checks</h2>
            <div className="panel small" style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              <div className="row" style={{ fontWeight: 800, borderBottom: "1px solid var(--rule)", paddingBottom: "8px", marginBottom: "4px", gap: "18px" }}>
                <span>GDPR</span>
                <span>● {gdpr.found} found in registries or documents</span>
                <span>○ {gdpr.claimed} vendor-claimed</span>
                <span>⚠ {issues?.regulator_actions ?? 0} issues linked</span>
                <span className="muted" style={{ marginLeft: "auto", fontWeight: 400 }}>
                  as of {asOf || "this build"}
                </span>
              </div>
              {gdpr.rows.map((g, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: "12px", ...(g.mark === "you" ? { borderTop: "1px solid var(--rule)", paddingTop: "8px", marginTop: "4px" } : {}) }}>
                  <span style={{ fontWeight: 800, color: MARK[g.mark].color }}>
                    {MARK[g.mark].glyph} {g.label}
                  </span>
                  <span>{g.text}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", marginBottom: "12px" }}>
              <h2 style={{ fontSize: "1.5rem" }}>News and chatter</h2>
              <span className="tiny muted">last 90 days · linked with confidence ≥ 0.85</span>
            </div>
            {!res.news_checked ? (
              <p className="muted small">Not checked in this build.</p>
            ) : news.length === 0 ? (
              <p className="muted small">Nothing linked from Hacker News, GDELT, GitHub releases or the vendor's feed in the last 90 days.</p>
            ) : (
              <div className="ledger">
                {news.map((n) => (
                  <div key={n.url} className="ledger-row" style={{ gridTemplateColumns: "90px 1fr 120px" }}>
                    <span className="muted" style={{ fontVariantNumeric: "tabular-nums" }}>
                      {fmtDate(n.date)}
                    </span>
                    <div>
                      <a href={n.url} rel="noopener" style={{ fontWeight: 800, color: "var(--ink)" }}>
                        {n.headline}
                      </a>
                      <div className="tiny muted" style={{ marginTop: "2px" }}>
                        {n.outlet}
                        {n.cluster_size && n.cluster_size > 1 ? ` · +${n.cluster_size - 1} outlet${n.cluster_size > 2 ? "s" : ""}` : ""}
                        {n.engagement != null ? ` · ${n.engagement} points+comments` : ""}
                        {n.summary ? ` · ${n.summary}` : ""}
                        {n.discussion_url && (
                          <>
                            {" · "}
                            <a href={n.discussion_url} rel="noopener">
                              discussion
                            </a>
                          </>
                        )}
                      </div>
                    </div>
                    <span className={`badge${RISK_TAGS.has(n.tag) ? " danger" : ""}`} style={{ justifySelf: "end" }}>
                      {NEWS_TAG_LABEL[n.tag] ?? n.tag}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p className="tiny muted" style={{ marginTop: "10px" }}>
              Headline, link and a summary attributed to the outlet. News never changes trust or domain scores.
            </p>
          </section>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
          <section>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline", borderTop: "2px solid var(--rule)", paddingTop: "12px" }}>
              <h3 style={{ fontSize: "1.15rem" }}>{best ? `${domainLabel(best[0])} score` : "Domain score"}</h3>
              <span style={{ fontWeight: 800, fontSize: "2rem", lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{best?.[1].score?.toFixed(1) ?? "–"}</span>
            </div>
            <div className="tiny muted" style={{ margin: "4px 0 12px" }}>
              {profileName} profile · {best?.[1].score_version ?? "sar-score-1.0"}
              {best?.[1].evidence_coverage != null ? ` · evidence coverage ${Math.round(best[1].evidence_coverage * 100)}%` : ""}
              {best?.[1].rank ? ` · rank #${best[1].rank} of 100` : " · unranked"}
            </div>
            {comps ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", fontSize: "0.85rem" }}>
                {Object.keys(COMPONENT_MAX)
                  .filter((k) => k in comps)
                  .map((k) => {
                    const v = comps[k];
                    const max = COMPONENT_MAX[k];
                    return (
                      <div key={k} style={{ display: "grid", gridTemplateColumns: "130px 1fr 60px", gap: "10px", alignItems: "center" }}>
                        <span>{COMPONENT_LABELS[k] ?? k}</span>
                        <div className="meter" aria-hidden="true">
                          <span style={{ width: v == null ? "0%" : `${Math.min(100, (100 * v) / max)}%` }}></span>
                        </div>
                        <span className="muted" style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                          {v == null ? "unknown" : `${v} / ${max}`}
                        </span>
                      </div>
                    );
                  })}
              </div>
            ) : (
              <p className="muted small">Not scored against the seed baseline.</p>
            )}
            <p className="tiny muted" style={{ marginTop: "12px" }}>
              Raw component / maximum, then weighted by the {profileName} profile ({Object.entries(weights).map(([k, w]) => `${(COMPONENT_LABELS[k] ?? k).split(" ")[0].toLowerCase()} ${w}`).join(", ")}). Unknown components count as 0 and are never imputed.
              {best?.[1].governance_evidence?.value != null && <> Evidence-based governance (sar-score-1.1): {best[1].governance_evidence.value.toFixed(0)} / 100.</>}
            </p>
          </section>

          <section style={{ borderTop: "2px solid var(--accent)", paddingTop: "12px" }}>
            <h3 style={{ fontSize: "1.15rem" }}>Before you procure, you still verify</h3>
            <div className="checklist" style={{ marginTop: "2px" }}>
              {checks.map((c) => (
                <div key={c}>
                  <span aria-hidden="true">☐</span>
                  <span>{c}</span>
                </div>
              ))}
            </div>
          </section>

          <section style={{ borderTop: "2px solid var(--rule)", paddingTop: "12px" }} className="small">
            <h3 style={{ fontSize: "1.15rem" }}>Provenance</h3>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "10px" }} className="body">
              {prov.map((p) => (
                <div key={p.source} style={{ display: "flex", justifyContent: "space-between", gap: "1rem" }}>
                  <span>{p.source}</span>
                  <span className="muted" style={{ textAlign: "right" }}>
                    {p.what}
                  </span>
                </div>
              ))}
              {res.first_seen && (
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span>First seen</span>
                  <span className="muted">{fmtDate(res.first_seen)}</span>
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span>Record</span>
                <span className="muted">
                  <code>{res.id}</code>
                </span>
              </div>
            </div>
            <a href={`${BASE}/catalog/agents/${res.id}.json`} style={{ display: "inline-block", marginTop: "12px", fontWeight: 800 }}>
              Open the full record (JSON) →
            </a>
          </section>
        </div>
      </div>
      <p className="tiny muted" style={{ borderTop: "2px solid var(--rule)", padding: "10px 0", marginTop: "32px" }}>
        {res.disclaimer ?? "Compliance information is compiled from the sources shown as of the date shown. It is not an assessment, certification, legal opinion or recommendation. Confirm current status with the vendor and the issuing body."}
      </p>
    </article>
  );
}

function TrustRow({ k, v, t, last = false }: { k: string; v: React.ReactNode; t: string; last?: boolean }) {
  return (
    <div className="ledger-row" style={{ gridTemplateColumns: "110px 1fr auto", borderTop: "1px solid var(--rule)", borderBottom: last ? "1px solid var(--rule)" : 0, padding: "9px 0" }}>
      <b>{k}</b>
      <span>{v}</span>
      <span className="tierbox">{t}</span>
    </div>
  );
}

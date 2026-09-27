import { useEffect, useMemo, useState } from "react";
import { BASE, fetchIndex, fetchResource } from "../lib/data";
import { FRAMEWORKS, domainLabel, frameworkName, protocolLabel, variantLabel } from "../lib/labels";
import { getShortlist, onShortlistChange } from "../lib/shortlist";
import type { CatalogIndex, IndexRecord, Resource } from "../lib/types";
import TrustStrip from "./TrustStrip";

const MAX = 4;

export default function CompareApp() {
  const [index, setIndex] = useState<CatalogIndex | null | undefined>();
  const [slugs, setSlugs] = useState<string[]>([]);
  const [details, setDetails] = useState<Record<string, Resource | null>>({});
  const [shortlist, setShortlist] = useState(getShortlist());
  const [pick, setPick] = useState("");

  useEffect(() => {
    fetchIndex().then(setIndex);
    const u = new URL(window.location.href);
    const ids = (u.searchParams.get("ids") ?? "").split(",").filter(Boolean);
    setSlugs(ids.length ? ids.slice(0, MAX) : getShortlist().slice(0, MAX).map((s) => s.slug));
    return onShortlistChange(() => setShortlist(getShortlist()));
  }, []);

  useEffect(() => {
    const u = new URL(window.location.href);
    if (slugs.length) u.searchParams.set("ids", slugs.join(","));
    else u.searchParams.delete("ids");
    window.history.replaceState(null, "", u.toString());
  }, [slugs]);

  const records = useMemo(
    () => slugs.map((s) => index?.records.find((r) => r.slug === s)).filter((r): r is IndexRecord => !!r),
    [index, slugs],
  );

  useEffect(() => {
    for (const r of records) {
      if (!(r.id in details)) {
        setDetails((d) => ({ ...d, [r.id]: null }));
        fetchResource(r.id).then((res) => setDetails((d) => ({ ...d, [r.id]: res })));
      }
    }
  }, [records, details]);

  if (index === null) return <p className="notice warn">No catalog in this build.</p>;
  if (!index) return <p className="muted">Loading…</p>;

  const frameworks = [...new Set(records.flatMap((r) => r.compliance_summary.map((c) => c.framework)))].sort();
  const domains = [...new Set(records.flatMap((r) => Object.keys(r.domains)))].sort();
  const options = index.records.filter((r) => !slugs.includes(r.slug)).sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <select aria-label="Add an agent" value={pick} onChange={(e) => setPick(e.target.value)} disabled={slugs.length >= MAX}>
          <option value="">Add an agent…</option>
          {shortlist.filter((s) => !slugs.includes(s.slug)).length > 0 && (
            <optgroup label="From your shortlist">
              {shortlist
                .filter((s) => !slugs.includes(s.slug))
                .map((s) => (
                  <option key={s.slug} value={s.slug}>
                    {s.name}
                  </option>
                ))}
            </optgroup>
          )}
          <optgroup label="All">
            {options.map((r) => (
              <option key={r.slug} value={r.slug}>
                {r.name} ({r.vendor})
              </option>
            ))}
          </optgroup>
        </select>
        <button
          type="button"
          className="btn"
          disabled={!pick || slugs.length >= MAX}
          onClick={() => {
            if (pick) setSlugs([...slugs, pick]);
            setPick("");
          }}
        >
          Add
        </button>
        <span className="muted small">up to {MAX} agents · share this page's URL to share the comparison</span>
      </div>
      {records.length === 0 && (
        <p className="muted">
          Pick agents above, or shortlist some from <a href={`${BASE}/`}>search</a>.
        </p>
      )}
      {records.length > 0 && (
        <div className="scroll-x">
          <table>
            <thead>
              <tr>
                <th></th>
                {records.map((r) => (
                  <th key={r.id} style={{ textTransform: "none", fontSize: "1rem", color: "var(--text)" }}>
                    <a href={`${BASE}/agents/${r.slug}/`}>{r.name}</a>
                    <div className="muted small" style={{ fontWeight: 400 }}>
                      {r.vendor}
                    </div>
                    <button type="button" className="btn small" style={{ marginTop: "0.3rem" }} onClick={() => setSlugs(slugs.filter((s) => s !== r.slug))}>
                      remove
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <Row label="Type / license">{records.map((r) => <td key={r.id}>{r.resource_type.replace(/_/g, " ")}{r.license ? ` · ${r.license}` : ""}</td>)}</Row>
              <Row label="Trust summary">{records.map((r) => <td key={r.id}><TrustStrip trust={r.trust} /></td>)}</Row>
              <Row label="Identity">
                {records.map((r) => {
                  const d = details[r.id];
                  return <td key={r.id}>T{r.trust.identity}{d ? ` · ${d.identity.evidence.map((e) => e.replace(/_/g, " ")).join(", ")}` : ""}</td>;
                })}
              </Row>
              {domains.map((d) => (
                <Row key={d} label={`${domainLabel(d)} rank`}>
                  {records.map((r) => {
                    const e = r.domains[d];
                    return <td key={r.id}>{e ? `${e.rank ? `#${e.rank}` : "unranked"}${e.score != null ? ` (${e.score.toFixed(1)})` : ""}` : "—"}</td>;
                  })}
                </Row>
              ))}
              {frameworks.map((fw) => (
                <Row key={fw} label={frameworkName(fw)} title={FRAMEWORKS[fw]?.name}>
                  {records.map((r) => {
                    const recs = r.compliance_summary.filter((c) => c.framework === fw);
                    if (!recs.length) return <td key={r.id} className="muted">no evidence</td>;
                    return (
                      <td key={r.id}>
                        {recs.map((c) => (
                          <div key={c.variant ?? "-"}>
                            <span className={`tier${c.credited === false ? " pending" : ""}`} data-tier={c.tier}>T{c.tier}</span>{" "}
                            {c.variant ? variantLabel(c.variant) : ""} {c.status !== "active" ? `(${c.status})` : ""}
                          </div>
                        ))}
                      </td>
                    );
                  })}
                </Row>
              ))}
              <Row label="Protocols">
                {records.map((r) => (
                  <td key={r.id}>{Object.entries(r.protocols).map(([p, s]) => `${p.toUpperCase()} ${protocolLabel(s).toLowerCase()}`).join(" · ")}</td>
                ))}
              </Row>
              <Row label="CVEs (NVD)">
                {records.map((r) => {
                  const d = details[r.id];
                  return <td key={r.id}>{d?.security ? d.security.cves : d === null ? "…" : "not checked"}</td>;
                })}
              </Row>
              <Row label="Open issues">
                {records.map((r) => {
                  const d = details[r.id];
                  return <td key={r.id}>{d?.issues ? d.issues.links.filter((l) => l.kind !== "cve").length : d === null ? "…" : "not checked"}</td>;
                })}
              </Row>
              <Row label="Recent news">
                {records.map((r) => {
                  const d = details[r.id];
                  return <td key={r.id}>{d?.news_checked ? `${d.news?.length ?? 0} items in 90 days` : d === null ? "…" : "not checked"}</td>;
                })}
              </Row>
              <Row label="Sources">{records.map((r) => <td key={r.id}>{r.sources.join(", ")}</td>)}</Row>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Row({ label, title, children }: { label: string; title?: string; children: React.ReactNode }) {
  return (
    <tr>
      <th scope="row" title={title}>
        {label}
      </th>
      {children}
    </tr>
  );
}

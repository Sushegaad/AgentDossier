import { useState } from "react";
import type { CatalogIndex, SearchDoc } from "../lib/types";
import SearchApp from "./SearchApp";

/**
 * Loads a catalog produced by a self-hosted AgentDossier (`agentdossier build` or the
 * enterprise scanner) from a local file or a URL and searches it entirely in the browser.
 * Nothing is uploaded anywhere.
 */
export default function PrivateCatalogApp() {
  const [index, setIndex] = useState<CatalogIndex | null>(null);
  const [docs, setDocs] = useState<SearchDoc[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");

  const accept = (data: unknown, source: string) => {
    const idx = data as CatalogIndex;
    if (!idx || !Array.isArray(idx.records)) {
      setError(`${source}: not a catalog index (expected an object with a "records" array)`);
      return;
    }
    setError(null);
    setIndex(idx);
  };

  const onFile = async (file: File | undefined, kind: "index" | "docs") => {
    if (!file) return;
    try {
      const data = JSON.parse(await file.text());
      if (kind === "index") accept(data, file.name);
      else setDocs(Array.isArray(data) ? (data as SearchDoc[]) : []);
    } catch (e) {
      setError(`${file.name}: ${(e as Error).message}`);
    }
  };

  const onUrl = async () => {
    if (!url) return;
    try {
      const base = url.replace(/\/index\.json$/, "").replace(/\/$/, "");
      const r = await fetch(`${base}/index.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      accept(await r.json(), url);
      const d = await fetch(`${base}/search-docs.json`);
      if (d.ok) setDocs((await d.json()) as SearchDoc[]);
    } catch (e) {
      setError(`${url}: ${(e as Error).message} (the server must allow CORS for this origin)`);
    }
  };

  return (
    <div>
      {!index && (
        <div className="card">
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
            <div>
              <h3>From files</h3>
              <p className="small muted">Pick the catalog's <code>index.json</code> (and optionally <code>search-docs.json</code> for richer text search).</p>
              <label className="small">
                index.json <input type="file" accept="application/json,.json" onChange={(e) => onFile(e.target.files?.[0], "index")} />
              </label>
              <br />
              <label className="small">
                search-docs.json <input type="file" accept="application/json,.json" onChange={(e) => onFile(e.target.files?.[0], "docs")} />
              </label>
            </div>
            <div>
              <h3>From a URL</h3>
              <p className="small muted">The catalog directory of a self-hosted instance, e.g. <code>https://registry.example.internal/catalog</code>.</p>
              <div className="row">
                <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/catalog" style={{ flex: "1 1 200px" }} />
                <button type="button" className="btn" onClick={onUrl}>
                  Load
                </button>
              </div>
            </div>
          </div>
          {error && <p className="notice warn" style={{ marginTop: "0.75rem" }}>{error}</p>}
        </div>
      )}
      {index && (
        <div>
          <p className="notice small">
            Viewing a {index.scope} catalog{index.tenant ? ` for ${index.tenant}` : ""} · snapshot {index.snapshot_date} · {index.records.length} resources · loaded
            in this browser only.{" "}
            <button type="button" className="btn small" onClick={() => { setIndex(null); setDocs([]); }}>
              load another
            </button>
          </p>
          <SearchApp index={index} docs={docs} syncUrl={false} linkAgents={false} examples={["agents with SOC 2", "MCP servers", "self-hosted coding agent"]} />
        </div>
      )}
    </div>
  );
}

// Client-side fetch of the bundled catalog (served from <base>/catalog/).
import type { CatalogIndex, Resource, SearchDoc } from "./types";

export const BASE = import.meta.env.BASE_URL.replace(/\/$/, "");

export async function fetchIndex(): Promise<CatalogIndex | null> {
  const r = await fetch(`${BASE}/catalog/index.json`);
  return r.ok ? ((await r.json()) as CatalogIndex) : null;
}

export async function fetchSearchDocs(): Promise<SearchDoc[]> {
  const r = await fetch(`${BASE}/catalog/search-docs.json`);
  return r.ok ? ((await r.json()) as SearchDoc[]) : [];
}

export async function fetchResource(id: string): Promise<Resource | null> {
  const r = await fetch(`${BASE}/catalog/agents/${id}.json`);
  return r.ok ? ((await r.json()) as Resource) : null;
}

/** Agent files are keyed by id; accept a slug too by looking it up in the index. */
export async function fetchResourceByIdOrSlug(ident: string): Promise<Resource | null> {
  if (ident.startsWith("res_")) return fetchResource(ident);
  const idx = await fetchIndex();
  const rec = idx?.records.find((r) => r.slug === ident || r.id === ident);
  return rec ? fetchResource(rec.id) : null;
}

/** Self-hosted builds (PUBLIC_DYNAMIC_AGENTS=1) have no pre-rendered agent pages; link to the dynamic dossier. */
export const DYNAMIC_AGENTS = import.meta.env.PUBLIC_DYNAMIC_AGENTS === "1";
export function agentHref(slugOrId: string): string {
  return DYNAMIC_AGENTS ? `${BASE}/agent/?id=${encodeURIComponent(slugOrId)}` : `${BASE}/agents/${slugOrId}/`;
}

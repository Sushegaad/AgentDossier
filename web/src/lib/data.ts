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

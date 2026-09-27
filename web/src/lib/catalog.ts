// Build-time access to the catalog written by `agentdossier build` (server only).
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import type { CatalogIndex, ChangelogEvent, DomainFile, IndexRecord, Resource, SearchDoc } from "./types";

export const CATALOG_DIR = resolve(process.env.CATALOG_DIR ?? "../data/catalog");
const CHANGELOG = resolve(process.env.CHANGELOG_PATH ?? "../data/changelog/trust-changelog.jsonl");

function readJson<T>(path: string): T | null {
  return existsSync(path) ? (JSON.parse(readFileSync(path, "utf8")) as T) : null;
}

let _index: CatalogIndex | null | undefined;
export function loadIndex(): CatalogIndex | null {
  if (_index === undefined) _index = readJson<CatalogIndex>(resolve(CATALOG_DIR, "index.json"));
  return _index;
}

export function loadIndexMeta(): Omit<CatalogIndex, "records"> | null {
  const idx = loadIndex();
  if (!idx) return null;
  const { records: _r, ...meta } = idx;
  return meta;
}

export function loadSearchDocs(): SearchDoc[] {
  return readJson<SearchDoc[]>(resolve(CATALOG_DIR, "search-docs.json")) ?? [];
}

export function loadResources(): Resource[] {
  const dir = resolve(CATALOG_DIR, "agents");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => readJson<Resource>(resolve(dir, f)))
    .filter((r): r is Resource => !!r)
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function loadResource(id: string): Resource | null {
  return readJson<Resource>(resolve(CATALOG_DIR, "agents", `${id}.json`));
}

export function loadDomain(id: string): DomainFile | null {
  return readJson<DomainFile>(resolve(CATALOG_DIR, "domains", `${id}.json`));
}

export function loadDomains(): DomainFile[] {
  const dir = resolve(CATALOG_DIR, "domains");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => readJson<DomainFile>(resolve(dir, f)))
    .filter((d): d is DomainFile => !!d);
}

export function loadSummary(): Record<string, unknown> | null {
  return readJson(resolve(CATALOG_DIR, "summary.json"));
}

export function loadChangelog(limit = 500): ChangelogEvent[] {
  if (!existsSync(CHANGELOG)) return [];
  const lines = readFileSync(CHANGELOG, "utf8").split("\n").filter(Boolean);
  return lines
    .slice(-limit)
    .map((l) => JSON.parse(l) as ChangelogEvent)
    .reverse();
}

export function recordOf(res: Resource): IndexRecord | undefined {
  return loadIndex()?.records.find((r) => r.id === res.id);
}

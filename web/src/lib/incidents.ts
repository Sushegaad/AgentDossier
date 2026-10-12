// The incident registry (data/curated/incidents.yaml): public traces of AI agents attacking or
// defending systems, one record per real, sourced event. Loaded at build time, rendered as the
// Traces section's registry index and per-incident pages, and exported as JSON and STIX 2.1.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { load as yamlLoad } from "js-yaml";

export type AiRole = "attacker" | "defender" | "target";

export interface IncidentSource {
  title: string;
  url: string;
  date?: string | null;
  outlet?: string | null;
}
export interface TimelineEntry {
  date: string;
  text: string;
  tier?: number | null;
  source?: string | null;
}
export interface NamedModel {
  name: string;
  role: AiRole;
  note?: string | null;
}
export interface Incident {
  id: string;
  status: "published" | "placeholder";
  title: string;
  date: string;
  window?: string | null;
  summary: string;
  ai_role: AiRole;
  category?: "red_team" | "injection_eval" | "incident" | "ctf";
  attacker: { description: string; models?: string[] };
  defender: { description: string; models?: string[] };
  scale?: string | null;
  impact?: string | null;
  tactics?: string[];
  timeline?: TimelineEntry[];
  lessons?: string[];
  models_named?: NamedModel[];
  related_agents?: string[];
  vendor_response?: string | null;
  sources: IncidentSource[];
  reviewer?: string | null;
  checked_on?: string | null;
  specimen?: boolean;
}
export interface IncidentSet {
  version: string;
  collected_on: string;
  collected_by: string;
  incidents: Incident[];
}

/** MITRE ATT&CK tactic ids → short labels, for the ones the registry uses. */
export const TACTIC_LABEL: Record<string, string> = {
  TA0043: "Reconnaissance",
  TA0001: "Initial Access",
  TA0002: "Execution",
  TA0003: "Persistence",
  TA0004: "Privilege Escalation",
  TA0005: "Defense Evasion",
  TA0006: "Credential Access",
  TA0007: "Discovery",
  TA0008: "Lateral Movement",
  TA0009: "Collection",
  TA0010: "Exfiltration",
  TA0011: "Command and Control",
  TA0040: "Impact",
};

export const AI_ROLE_WORD: Record<AiRole, string> = {
  attacker: "agent was the attacker",
  defender: "agent defended",
  target: "agent was the target",
};

let cached: IncidentSet | null | undefined;

export function loadIncidents(): IncidentSet | null {
  if (cached !== undefined) return cached;
  const path = resolve(process.env.INCIDENTS ?? "../data/curated/incidents.yaml");
  try {
    const doc = yamlLoad(readFileSync(path, "utf8")) as IncidentSet;
    doc.incidents = (doc.incidents ?? []).filter((i) => i.status === "published");
    doc.incidents.sort((a, b) => a.id.localeCompare(b.id));
    cached = doc;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") cached = null;
    else throw e;
  }
  return cached;
}

/** The scout's candidates file (data/curated/incident_candidates.yaml): leads awaiting a maintainer,
 *  never incidents. The site shows only the count and the scout date. */
export interface CandidateSummary {
  awaiting: number;
  scoutedOn: string | null;
  sourcesChecked: number;
  sourcesFailed: string[];
}

let cachedCandidates: CandidateSummary | null | undefined;

export function loadCandidates(): CandidateSummary | null {
  if (cachedCandidates !== undefined) return cachedCandidates;
  const path = resolve(process.env.INCIDENT_CANDIDATES ?? "../data/curated/incident_candidates.yaml");
  try {
    const doc = yamlLoad(readFileSync(path, "utf8")) as {
      scouted_on?: string | null;
      sources_checked?: number;
      sources_failed?: string[];
      candidates?: Array<{ status?: string }>;
    };
    cachedCandidates = {
      awaiting: (doc.candidates ?? []).filter((c) => c.status === "new").length,
      scoutedOn: doc.scouted_on ? String(doc.scouted_on) : null,
      sourcesChecked: doc.sources_checked ?? 0,
      sourcesFailed: doc.sources_failed ?? [],
    };
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") cachedCandidates = null;
    else throw e;
  }
  return cachedCandidates;
}

export function incidentSlug(id: string): string {
  return id.toLowerCase();
}

export function incidentById(slug: string): Incident | null {
  return loadIncidents()?.incidents.find((i) => incidentSlug(i.id) === slug.toLowerCase()) ?? null;
}

/** Incidents that name a catalog agent (by slug), for the dossier cross-link. */
export function incidentsForAgent(agentSlug: string): Incident[] {
  return (loadIncidents()?.incidents ?? []).filter((i) => (i.related_agents ?? []).includes(agentSlug));
}

/** A STIX 2.1 bundle for one incident: an incident SDO, attack-pattern per tactic, and the
 *  attacker/defender identities, with the sources as external references. Minimal but valid shape. */
export function toStix(inc: Incident): Record<string, unknown> {
  const now = `${inc.date}T00:00:00.000Z`;
  const refs = inc.sources.map((s) => ({ source_name: s.outlet ?? "source", url: s.url, description: s.title }));
  const idOf = (kind: string, seed: string) => `${kind}--${uuidFrom(inc.id + kind + seed)}`;
  const attacker = {
    type: "identity",
    spec_version: "2.1",
    id: idOf("identity", "attacker"),
    created: now,
    modified: now,
    name: inc.attacker.description,
    roles: ["attacker"],
  };
  const defender = {
    type: "identity",
    spec_version: "2.1",
    id: idOf("identity", "defender"),
    created: now,
    modified: now,
    name: inc.defender.description,
    roles: ["defender"],
  };
  const patterns = (inc.tactics ?? []).map((t) => ({
    type: "attack-pattern",
    spec_version: "2.1",
    id: idOf("attack-pattern", t),
    created: now,
    modified: now,
    name: `${t} ${TACTIC_LABEL[t] ?? ""}`.trim(),
    external_references: [{ source_name: "mitre-attack", external_id: t }],
  }));
  const incident = {
    type: "incident",
    spec_version: "2.1",
    id: idOf("incident", "root"),
    created: now,
    modified: now,
    name: inc.title,
    description: inc.summary,
    external_references: [
      { source_name: "AgentDossier", external_id: inc.id, url: `https://sushegaad.github.io/AgentDossier/traces/${incidentSlug(inc.id)}/` },
      ...refs,
    ],
  };
  return {
    type: "bundle",
    id: `bundle--${uuidFrom(inc.id)}`,
    objects: [incident, attacker, defender, ...patterns],
  };
}

/** Deterministic UUIDv5-ish id from a string (so a rebuild yields stable STIX ids without a dep). */
function uuidFrom(s: string): string {
  let h = 0x811c9dc5;
  const out: number[] = [];
  for (let i = 0; i < 16; i++) {
    for (let j = 0; j < s.length; j++) h = Math.imul(h ^ s.charCodeAt(j) ^ i, 0x01000193) >>> 0;
    out.push(h & 0xff);
  }
  out[6] = (out[6] & 0x0f) | 0x50;
  out[8] = (out[8] & 0x3f) | 0x80;
  const hex = out.map((b) => b.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
}

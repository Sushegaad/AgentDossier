// The reference set (data/curated/reference_set.yaml): a small group of agents whose dossiers answer
// deployment questions from the vendor's own documentation. Loaded at build time only; the public
// dossier and the worked comparisons are static.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { load as yamlLoad } from "js-yaml";

export type AnswerValue = "yes" | "no" | "configurable" | "unknown";
export const ANSWER_VALUES: AnswerValue[] = ["yes", "no", "configurable", "unknown"];

export interface Answer {
  value: AnswerValue;
  note: string;
  source: string;
}
export interface Question {
  id: string;
  label: string;
}
export interface UseCase {
  id: string;
  title: string;
  question: string;
  intro: string;
  questions: Question[];
}
export interface ReferenceAgent {
  slug: string;
  use_case: string;
  answers: Record<string, Answer>;
}
export interface ReferenceSet {
  version: string;
  collected_on: string;
  collected_by: string;
  reviewed_by: string | null;
  use_cases: UseCase[];
  agents: ReferenceAgent[];
}

const PLACEHOLDERS = new Set(["", "maintainer", "todo", "tbd", "pending", "n/a", "none"]);

export function parseReferenceSet(text: string): ReferenceSet {
  const doc = yamlLoad(text) as ReferenceSet;
  const problems: string[] = [];
  if (!doc || !Array.isArray(doc.use_cases) || !Array.isArray(doc.agents)) throw new Error("reference_set.yaml: use_cases and agents are required");
  if (doc.reviewed_by != null && PLACEHOLDERS.has(String(doc.reviewed_by).trim().toLowerCase())) problems.push(`reviewed_by must be a person's handle or null, not "${doc.reviewed_by}"`);
  const useCases = new Map(doc.use_cases.map((u) => [u.id, u]));
  for (const u of doc.use_cases) {
    if (!u.id || !u.title || !u.question || !Array.isArray(u.questions) || !u.questions.length) problems.push(`use case ${u.id ?? "?"}: id, title, question and questions are required`);
  }
  for (const a of doc.agents) {
    const uc = useCases.get(a.use_case);
    if (!a.slug) problems.push("agent without slug");
    if (!uc) {
      problems.push(`${a.slug}: unknown use_case ${a.use_case}`);
      continue;
    }
    for (const q of uc.questions) {
      const ans = a.answers?.[q.id];
      if (!ans) {
        problems.push(`${a.slug}: no answer for ${q.id}`);
        continue;
      }
      if (!ANSWER_VALUES.includes(ans.value)) problems.push(`${a.slug}.${q.id}: value must be one of ${ANSWER_VALUES.join(", ")}`);
      if (!ans.note || !ans.source || !/^https?:\/\//.test(ans.source)) problems.push(`${a.slug}.${q.id}: note and an http(s) source are required`);
    }
    for (const k of Object.keys(a.answers ?? {})) if (!uc.questions.some((q) => q.id === k)) problems.push(`${a.slug}: answer ${k} is not a question of ${uc.id}`);
  }
  if (problems.length) throw new Error("reference_set.yaml:\n  " + problems.join("\n  "));
  return doc;
}

let cached: ReferenceSet | null | undefined;

export function loadReferenceSet(): ReferenceSet | null {
  if (cached !== undefined) return cached;
  const path = resolve(process.env.REFERENCE_SET ?? "../data/curated/reference_set.yaml");
  try {
    cached = parseReferenceSet(readFileSync(path, "utf8"));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") cached = null;
    else throw e;
  }
  return cached;
}

export function referenceFor(slug: string, ref: ReferenceSet | null = loadReferenceSet()): { entry: ReferenceAgent; useCase: UseCase; set: ReferenceSet } | null {
  if (!ref) return null;
  const entry = ref.agents.find((a) => a.slug === slug);
  if (!entry) return null;
  const useCase = ref.use_cases.find((u) => u.id === entry.use_case);
  return useCase ? { entry, useCase, set: ref } : null;
}

export const ANSWER_GLYPH: Record<AnswerValue, string> = { yes: "✔", configurable: "◐", no: "✕", unknown: "?" };
export const ANSWER_WORD: Record<AnswerValue, string> = { yes: "documented", configurable: "configurable", no: "not provided", unknown: "not documented" };

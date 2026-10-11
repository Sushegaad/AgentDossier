// "Before you deploy": the decision-oriented block on every dossier. Three groups, all derived
// from data — the evidence ledger, the reference-set answers (when the agent is in the set) and
// config/deploy_rules.json — never hand-written per agent.
import rulesFile from "../../../config/deploy_rules.json";
import { agentScoped, checklist, evidenceRows, presetFrameworks } from "./dossier";
import { frameworkName, variantLabel } from "./labels";
import type { Answer, AnswerValue, ReferenceAgent, UseCase } from "./reference";
import type { Resource } from "./types";

export interface DeployItem {
  text: string;
  /** where the statement comes from */
  source?: string | null;
  /** a question id, framework id or rule id for keys and tests */
  key: string;
}

export interface BeforeYouDeploy {
  supporting: DeployItem[];
  unknowns: DeployItem[];
  restrictions: DeployItem[];
  /** reference-set answers shown on the dossier, in question order */
  answers: { question: string; label: string; answer: Answer }[];
  inReferenceSet: boolean;
}

interface Rule {
  id: string;
  when: {
    answer?: Record<string, AnswerValue[]>;
    evidence_missing?: string;
    identity_tier_min?: number;
    protocol?: Record<string, string[]>;
  };
  restriction: string;
}

export const RULES: Rule[] = (rulesFile as { rules: Rule[] }).rules;

function ruleFires(rule: Rule, res: Resource, answers: Record<string, Answer> | null): boolean {
  const w = rule.when;
  if (w.answer) {
    if (!answers) return false; // answer-based rules need the reference set
    for (const [q, values] of Object.entries(w.answer)) {
      const a = answers[q];
      if (!a || !values.includes(a.value)) return false;
    }
  }
  if (w.evidence_missing) {
    const active = (res.compliance ?? []).filter((c) => c.status === "active" && c.framework === w.evidence_missing);
    if (active.length || !presetFrameworks(res).includes(w.evidence_missing)) return false;
  }
  if (w.identity_tier_min != null && res.identity.tier < w.identity_tier_min) return false;
  if (w.protocol) {
    for (const [p, statuses] of Object.entries(w.protocol)) {
      const s = res.protocols?.[p]?.status as string | undefined;
      if (!s || !statuses.includes(s)) return false;
    }
  }
  return true;
}

export function beforeYouDeploy(res: Resource, ref: { entry: ReferenceAgent; useCase: UseCase } | null): BeforeYouDeploy {
  const supporting: DeployItem[] = [];
  const unknowns: DeployItem[] = [];
  const restrictions: DeployItem[] = [];
  const answers = ref?.entry.answers ?? null;

  // one short line per ledger row: what it is and how firm it is; the ledger above carries the detail
  const rows = evidenceRows(res).filter((r) => r.mark !== "missing");
  for (const r of rows.filter((r) => r.mark !== "issue")) {
    const scoped = r.record ? agentScoped(r.record) : false;
    const fw = frameworkName(r.framework);
    const vl = r.variant ? variantLabel(r.variant) : "";
    const name = vl ? (vl.toLowerCase().startsWith(fw.toLowerCase()) ? vl : `${fw} ${vl}`) : fw;
    const firmness = r.mark === "claimed" ? "vendor-claimed" : "registry-matched";
    supporting.push({
      key: `evidence:${r.framework}:${r.variant ?? ""}`,
      text: `${name} — ${firmness}${scoped ? "" : ", vendor-level"}`,
      source: r.sourceUrl,
    });
  }
  for (const r of rows.filter((r) => r.mark === "issue")) unknowns.push({ key: `evidence-issue:${r.framework}`, text: `${frameworkName(r.framework)} evidence is ${r.record?.status ?? "no longer current"}: confirm current status with the issuer`, source: r.sourceUrl });

  const answerList: BeforeYouDeploy["answers"] = [];
  if (ref) {
    for (const q of ref.useCase.questions) {
      const a = ref.entry.answers[q.id];
      if (!a) continue;
      answerList.push({ question: q.id, label: q.label, answer: a });
      if (a.value === "yes" || a.value === "configurable") supporting.push({ key: `answer:${q.id}`, text: `${q.label.replace(/\?$/, "")}: ${a.value === "yes" ? "yes" : "configurable"} — ${a.note}`, source: a.source });
      else if (a.value === "unknown") unknowns.push({ key: `answer:${q.id}`, text: `${q.label.replace(/\?$/, "")}: not documented — ${a.note}. Ask the vendor.`, source: a.source });
      else unknowns.push({ key: `answer:${q.id}`, text: `${q.label.replace(/\?$/, "")}: no — ${a.note}`, source: a.source });
    }
  }

  for (const c of checklist(res)) unknowns.push({ key: `check:${c.slice(0, 40)}`, text: c });

  for (const rule of RULES) if (ruleFires(rule, res, answers)) restrictions.push({ key: `rule:${rule.id}`, text: rule.restriction });

  return { supporting, unknowns, restrictions, answers: answerList, inReferenceSet: !!ref };
}

/** One honest sentence per agent for the worked comparison; never a ranking. */
export function verdictSentence(b: BeforeYouDeploy, name: string): string {
  const unknownAnswers = b.answers.filter((a) => a.answer.value === "unknown").length;
  const noAnswers = b.answers.filter((a) => a.answer.value === "no").length;
  const total = b.answers.length;
  if (!total) return `${name} is not in the reference set; its dossier shows evidence only.`;
  if (unknownAnswers >= Math.ceil(total / 2)) return `${name}: the documentation checked answers ${total - unknownAnswers} of ${total} questions. The evidence is not sufficient to scope a pilot without answers from the vendor.`;
  const parts = [`${name}: ${total - unknownAnswers} of ${total} questions documented`];
  if (noAnswers) parts.push(`${noAnswers} of them answered no`);
  if (unknownAnswers) parts.push(`${unknownAnswers} to ask the vendor`);
  return `${parts.join(", ")}; a bounded pilot is possible under ${b.restrictions.length} restriction${b.restrictions.length === 1 ? "" : "s"}.`;
}

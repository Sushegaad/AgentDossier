import { readFileSync } from "node:fs";
import { load as yamlLoad } from "js-yaml";

export function loadYaml<T>(rel: string): T {
  return yamlLoad(readFileSync(new URL(rel, import.meta.url), "utf8")) as T;
}

export interface EvalQuery { id: string; query: string; relevant: string[]; tags?: string[] }
export interface EvalSet { version: string; threshold: number; max_drop?: number; queries: EvalQuery[] }
export interface IntentCase { id: string; text: string; expected: Record<string, unknown[]> }

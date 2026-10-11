"""Turn a harness run into a trace bundle and append it to the store.

One bundle per (model, suite, attack): manifest (what was run), transcript (human-readable,
per injection task), verdict (the numbers). The trace is ``kind: injection_eval``, ``scope:
model``, tier 1 (a reproducible run with public artifacts), attributed to AgentDojo. The store
line's ``agent`` is the model key; :func:`agentdossier.traces.apply_traces` fans model-scoped
records out to the catalog agents the model is evidence for.
"""

from __future__ import annotations

import json
from typing import Any

from ..traces.store import TraceStore
from .run import SOURCE, SOURCE_URL, HarnessResult


def _slug(s: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def trace_id(result: HarnessResult, model_key: str) -> str:
    return f"tr_hn_{_slug(model_key)}_{result.suite}_{_slug(result.attack)}"


def observation_key(result: HarnessResult, model_key: str) -> str:
    """A bundle is re-appended only when the outcome changes for this model+suite+attack."""
    facts = {
        "model": model_key,
        "suite": result.suite,
        "attack": result.attack,
        "benchmark": result.benchmark_version,
        "security": {f"{u}|{j}": v for (u, j), v in sorted(result.security.items())},
    }
    import hashlib

    return "sha256:" + hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _transcript(result: HarnessResult, model_key: str) -> str:
    lines = [
        f"# Prompt-injection benchmark — {model_key} on AgentDojo `{result.suite}`",
        "",
        f"Backend `{result.model_name}` · attack `{result.attack}` · {SOURCE} {result.agentdojo_version} "
        f"({result.benchmark_version}) · scope: model",
        "",
        f"The agent ran {result.pairs} user-task × injection-task pairs. In each, benign tool output "
        f"carried an attacker instruction; the trace records whether the agent acted on it.",
        "",
        f"- **Resisted:** {result.resisted} / {result.pairs}",
        f"- **Injection succeeded:** {result.injections_succeeded} / {result.pairs}"
        + (
            f"  (attack success rate {result.attack_success_rate})"
            if result.attack_success_rate is not None
            else ""
        ),
        "",
        "## Per injection task",
        "",
    ]
    by_injection: dict[str, list[tuple[str, bool]]] = {}
    for (user, inj), succeeded in sorted(result.security.items()):
        by_injection.setdefault(inj, []).append((user, succeeded))
    for inj, rows in by_injection.items():
        hit = sum(1 for _, s in rows if s)
        lines.append(f"### {inj} — injection succeeded in {hit} of {len(rows)} tasks")
        for user, succeeded in rows:
            util = result.utility.get((user, inj))
            lines.append(
                f"- `{user}`: {'INJECTION SUCCEEDED' if succeeded else 'resisted'}"
                + (f" · user task {'completed' if util else 'not completed'}" if util is not None else "")
            )
        lines.append("")
    lines += [
        "---",
        f"Scenarios, attacks and the success check are AgentDojo's ({SOURCE_URL}, MIT). This registry ran "
        "the agent against them in a sandbox and recorded the outcome; it did not author the attacks. "
        "A model-level result is inherited evidence for agents built on this model, not a test of any one "
        "product. One model, one date.",
    ]
    return "\n".join(lines) + "\n"


def _verdict(result: HarnessResult) -> dict[str, Any]:
    any_success = result.injections_succeeded > 0
    return {
        "entry": "attacker instructions embedded in tool output (AgentDojo injection tasks)",
        "actions": [f"{result.pairs} user-task × injection-task pairs on the {result.suite} suite"],
        "egress": None,
        "approval": None,
        "secrets_touched": None,
        "refused": None if result.pairs == 0 else not any_success,
        "outcome": (
            f"injection succeeded in {result.injections_succeeded} of {result.pairs} pairs"
            f" (attack success rate {result.attack_success_rate})"
            if result.pairs
            else "no pairs run"
        ),
    }


def _manifest(result: HarnessResult, model_key: str, tid: str) -> dict[str, Any]:
    return {
        "id": tid,
        "model_key": model_key,
        "backend": result.model_name,
        "kind": "injection_eval",
        "benchmark": {
            "name": SOURCE,
            "version": result.agentdojo_version,
            "suite_set": result.benchmark_version,
            "url": SOURCE_URL,
        },
        "suite": result.suite,
        "attack": result.attack,
        "pairs": result.pairs,
        "injections_succeeded": result.injections_succeeded,
        "attack_success_rate": result.attack_success_rate,
        "security_results": {f"{u}|{j}": v for (u, j), v in sorted(result.security.items())},
        "utility_results": {f"{u}|{j}": v for (u, j), v in sorted(result.utility.items())},
    }


def record_run(
    store: TraceStore, result: HarnessResult, model_key: str, *, site: str, date: str
) -> str | None:
    """Append a bundle for this run unless the outcome is unchanged. Returns the trace id, or None."""
    if result.error or not result.pairs:
        return None
    key = observation_key(result, model_key)
    if key in store.keys():
        return None
    tid = trace_id(result, model_key)
    manifest = _manifest(result, model_key, tid)
    verdict = _verdict(result)
    files = {
        "manifest.json": json.dumps(manifest, indent=1, sort_keys=True).encode(),
        "transcript.md": _transcript(result, model_key).encode(),
        "verdict.json": json.dumps(verdict, indent=1, sort_keys=True).encode(),
    }
    record = {
        "id": tid,
        "kind": "injection_eval",
        "tier": 1,
        "scope": "model",
        "title": f"{model_key}: AgentDojo {result.suite} prompt-injection suite under the {result.attack} attack",
        "scenario": f"{result.pairs} tasks where benign tool output carried an attacker instruction; "
        f"injection succeeded in {result.injections_succeeded}",
        "source": f"{SOURCE} {result.agentdojo_version}",
        "url": f"{site.rstrip('/')}/traces/{tid}/",
        "date": date,
        "format": "bundle",
        "observed": verdict,
        "vendor_response": None,
        "agent_version": None,
        "harness_version": f"agentdojo-{result.agentdojo_version}",
        "reviewer": None,
        "checked_on": None,
        "notes": f"Model-level: inherited evidence for agents built on {model_key}. Scenarios and the "
        f"success check are AgentDojo's; this registry ran the agent and recorded the result.",
    }
    store.append(record, agent=model_key, key=key, files=files)
    return tid

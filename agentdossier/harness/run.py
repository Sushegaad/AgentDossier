"""Run one AgentDojo suite against a pipeline and summarise the outcome (no I/O of our own)."""

from __future__ import annotations

import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "v1.2.1"
SUITES = ("workspace", "slack", "banking", "travel")
SOURCE = "AgentDojo"
SOURCE_URL = "https://github.com/ethz-spylab/agentdojo"


@dataclass
class HarnessResult:
    """Outcome of one (suite, attack, model) run, ready to turn into a trace bundle."""

    suite: str
    attack: str
    model_name: str
    benchmark_version: str
    agentdojo_version: str
    # (user_task, injection_task) -> injection succeeded (True is bad)
    security: dict[tuple[str, str], bool] = field(default_factory=dict)
    utility: dict[tuple[str, str], bool] = field(default_factory=dict)
    error: str | None = None

    @property
    def pairs(self) -> int:
        return len(self.security)

    @property
    def injections_succeeded(self) -> int:
        return sum(1 for v in self.security.values() if v)

    @property
    def resisted(self) -> int:
        return self.pairs - self.injections_succeeded

    @property
    def attack_success_rate(self) -> float | None:
        return round(self.injections_succeeded / self.pairs, 3) if self.pairs else None

    @property
    def injection_tasks(self) -> list[str]:
        return sorted({j for _, j in self.security})


def _agentdojo_version() -> str:
    import importlib.metadata as m

    try:
        return m.version("agentdojo")
    except Exception:  # pragma: no cover
        return "unknown"


def run_suite(
    pipeline: Any,
    suite_name: str,
    *,
    attack_name: str = "ignore_previous",
    user_tasks: list[str] | None = None,
    injection_tasks: list[str] | None = None,
    benchmark_version: str = BENCHMARK_VERSION,
) -> HarnessResult:
    """Benchmark ``pipeline`` on one suite with one attack. ``pipeline`` is any AgentDojo
    ``BasePipelineElement`` (a model backend for real runs, a mock for tests)."""
    from agentdojo.attacks.attack_registry import load_attack
    from agentdojo.benchmark import benchmark_suite_with_injections
    from agentdojo.logging import OutputLogger
    from agentdojo.task_suite.load_suites import get_suites

    res = HarnessResult(
        suite=suite_name,
        attack=attack_name,
        model_name=getattr(pipeline, "name", "unknown"),
        benchmark_version=benchmark_version,
        agentdojo_version=_agentdojo_version(),
    )
    try:
        suite = get_suites(benchmark_version)[suite_name]
    except KeyError as exc:
        res.error = f"unknown suite or version: {exc}"
        return res
    attack = load_attack(attack_name, suite, pipeline)
    with tempfile.TemporaryDirectory() as d, warnings.catch_warnings(), OutputLogger(d):
        warnings.simplefilter("ignore")
        out = benchmark_suite_with_injections(
            pipeline,
            suite,
            attack,
            logdir=Path(d),
            force_rerun=True,
            user_tasks=user_tasks,
            injection_tasks=injection_tasks,
            verbose=False,
            benchmark_version=benchmark_version,
        )
    # AgentDojo returns a SuiteResults TypedDict (a plain dict at runtime).
    if isinstance(out, dict):
        data = out
    else:  # pragma: no cover - defensive against a future dataclass return
        data = {"security_results": out.security_results, "utility_results": out.utility_results}
    res.security = dict(data.get("security_results", {}))
    res.utility = dict(data.get("utility_results", {}))
    return res

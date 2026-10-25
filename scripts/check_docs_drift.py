"""Documentation drift check: facts the docs state that the repository can verify.

Runs in CI (lint job) and under pytest (tests/test_docs_drift.py). Every check names the two places
that disagree, so the fix is obvious. Add a check here whenever a doc starts stating a number or a
version that lives somewhere else in the repo — the point is that a doc can never silently go stale.

    uv run python scripts/check_docs_drift.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DOCKERFILE = ROOT / "deploy" / "Dockerfile"
PYPROJECT = ROOT / "pyproject.toml"
INCIDENTS = ROOT / "data" / "curated" / "incidents.yaml"
INCIDENTS_DOC = ROOT / "docs" / "incidents.md"
TESTS = ROOT / "tests"
TEST_COUNT_TOLERANCE = 0.10  # README says "~N tests"; N may lag the real count by this fraction


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _ints(pattern: str, text: str) -> list[int]:
    return [int(m) for m in re.findall(pattern, text)]


def check_test_count(problems: list[str]) -> None:
    actual = sum(len(re.findall(r"^\s*def test_", _read(f), re.M)) for f in TESTS.glob("test_*.py"))
    stated = _ints(r"~\s*(\d+)\s+tests", _read(README))
    if not stated:
        problems.append("README.md: no '~N tests' statement found (Quick start)")
        return
    for n in stated:
        if abs(n - actual) > TEST_COUNT_TOLERANCE * actual:
            problems.append(
                f"README.md says '~{n} tests' but tests/ defines {actual} test functions (update the number)"
            )


def _ci_versions() -> tuple[list[str], set[str]]:
    ci = _read(CI)
    m = re.search(r"python:\s*\[([^\]]*)\]", ci)
    matrix = re.findall(r'"(\d+\.\d+)"', m.group(1)) if m else []
    nodes = set(re.findall(r'node-version:\s*"?(\d+)"?', ci))
    return matrix, nodes


def check_versions(problems: list[str]) -> None:
    matrix, nodes = _ci_versions()
    readme = _read(README)
    docker = _read(DOCKERFILE)
    pyproject = _read(PYPROJECT)

    # README minimum Python == pyproject requires-python minimum == lowest CI matrix entry
    rm = re.search(r"Python\s+(\d+\.\d+)\+", readme)
    pm = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', pyproject)
    if rm and pm and rm.group(1) != pm.group(1):
        problems.append(
            f"README.md says Python {rm.group(1)}+ but pyproject requires-python is >={pm.group(1)}"
        )
    # Dockerfile Python tag must be a version CI tests
    for tag in set(re.findall(r"^FROM python:(\d+\.\d+)-", docker, re.M)):
        if tag not in matrix:
            problems.append(
                f"deploy/Dockerfile uses python:{tag} but ci.yml tests {matrix} — pin the image or add it to the matrix"
            )
    # Dockerfile Node major must equal CI node-version(s)
    for tag in set(re.findall(r"^FROM node:(\d+)-", docker, re.M)):
        if tag not in nodes:
            problems.append(f"deploy/Dockerfile uses node:{tag} but ci.yml uses node-version {sorted(nodes)}")
    # README Node version must equal CI
    nm = re.search(r"Node\s+(\d+)", readme)
    if nm and nm.group(1) not in nodes:
        problems.append(f"README.md says Node {nm.group(1)} but ci.yml uses node-version {sorted(nodes)}")


def check_docs_list(problems: list[str]) -> None:
    readme = _read(README)
    for doc in sorted((ROOT / "docs").glob("*.md")):
        rel = f"docs/{doc.name}"
        if rel not in readme:
            problems.append(f"README.md does not link {rel} (add it to the Docs line)")


def check_incident_count(problems: list[str]) -> None:
    if not INCIDENTS.exists() or not INCIDENTS_DOC.exists():
        return
    published = len(re.findall(r"^    status: published\s*$", _read(INCIDENTS), re.M))
    placeholders = len(re.findall(r"^    status: placeholder\b", _read(INCIDENTS), re.M))
    doc = _read(INCIDENTS_DOC)
    m = re.search(r"\*\*(\d+)\s+published\*\*", doc)
    if not m:
        problems.append("docs/incidents.md: expected a '**N published**' count (Where new entries come from)")
    elif int(m.group(1)) != published:
        problems.append(
            f"docs/incidents.md says {m.group(1)} published incidents; incidents.yaml has {published}"
        )
    p = re.search(r"\*\*(\d+)\s+placeholders?\*\*", doc)
    if p and int(p.group(1)) != placeholders:
        problems.append(
            f"docs/incidents.md says {p.group(1)} placeholders; incidents.yaml has {placeholders}"
        )


def run() -> list[str]:
    problems: list[str] = []
    for check in (check_test_count, check_versions, check_docs_list, check_incident_count):
        check(problems)
    return problems


def main() -> int:
    problems = run()
    for p in problems:
        print("  drift:", p)
    print(f"check_docs_drift: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

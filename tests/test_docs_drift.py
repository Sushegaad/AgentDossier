"""The docs state facts the repo can verify (test count, versions, docs list, incident counts).
scripts/check_docs_drift.py is the source of truth; this makes a plain `pytest` catch drift too."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_docs_drift.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_drift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_docs_do_not_drift_from_the_repo():
    problems = _load().run()
    assert not problems, "documentation drift:\n  " + "\n  ".join(problems)

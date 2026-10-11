"""Verify the trace store's hash chain and bundles (CI gate)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentdossier.traces.store import TraceStore  # noqa: E402

store = TraceStore(Path(sys.argv[1]) if len(sys.argv) > 1 else TraceStore().root)
problems = store.verify()
for p in problems:
    print("trace store:", p)
print(f"verify_traces: {len(store.lines())} lines, {len(problems)} problems")
sys.exit(1 if problems else 0)

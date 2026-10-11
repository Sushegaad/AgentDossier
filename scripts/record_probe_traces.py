"""Append self_test trace bundles from the probe results in a built catalog.

The build does this on every refresh; this script does it for an existing catalog (the
first fill of the store, or a catalog built elsewhere). Idempotent: an unchanged
observation appends nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agentdossier.build import SITE  # noqa: E402
from agentdossier.traces.selftest import record_probes  # noqa: E402
from agentdossier.traces.store import TraceStore  # noqa: E402
from agentdossier.util import now_iso  # noqa: E402

catalog = Path(sys.argv[1] if len(sys.argv) > 1 else "data/catalog")
index = json.loads((catalog / "index.json").read_text())
date = (index.get("built_at") or now_iso())[:10]
resources = [json.loads(p.read_text()) for p in sorted((catalog / "agents").glob("*.json"))]
store = TraceStore()
counts = record_probes(resources, store, site=SITE, date=date)
print(f"record_probe_traces: {counts} · {len(store.lines())} lines in {store.index_path}")

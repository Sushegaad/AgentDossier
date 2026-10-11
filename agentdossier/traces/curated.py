"""Curated public traces (``data/curated/traces.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import ROOT

CURATED = ROOT / "data" / "curated" / "traces.yaml"
MAX_TIER = 4  # 5 is reserved for "nothing found"


def load_curated(path: Path = CURATED) -> list[dict[str, Any]]:
    """One record per (trace, agent). Sibling-platform rows are tiered one step lower."""
    if not path.exists():
        return []
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    out: list[dict[str, Any]] = []
    for row in doc.get("records") or []:
        agents = list(row.get("agents") or [])
        base = {
            k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items() if k != "agents"
        }  # YAML dates → ISO strings
        base.setdefault("scope", "product")
        base.setdefault("reviewer", None)
        base.setdefault("checked_on", None)
        for i, slug in enumerate(agents):
            rec = dict(base)
            rec["agent"] = slug
            if i > 0 and rec["scope"] == "product":
                rec["scope"] = "platform"
            if rec["scope"] != "product":
                rec["tier"] = min(MAX_TIER, int(rec["tier"]) + 1)
            out.append(rec)
    return out

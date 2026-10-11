"""The harness model map (``data/traces/harness/models.yaml``): which agents a model's traces
are evidence for, and how to build its AgentDojo backend for a real run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..util import ROOT

MODELS = ROOT / "data" / "traces" / "harness" / "models.yaml"


def load_models(path: Path = MODELS) -> dict[str, dict[str, Any]]:
    """model_key -> {backend, agents}. Empty when the file or PyYAML is absent."""
    if not path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    return {str(k): (v or {}) for k, v in (doc.get("models") or {}).items()}


def agents_for_model(model_key: str, models: dict[str, dict[str, Any]] | None = None) -> list[str]:
    models = load_models() if models is None else models
    return [str(a) for a in (models.get(model_key, {}).get("agents") or [])]

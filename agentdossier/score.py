"""Domain scoring (BRD v3.2 §3.2, FR-08, FR-16, FR-25).

Score version ``sar-score-2.0``: seven weight profiles reproduce every score
in the 25 Sep 2026 seed workbook to within 0.07 points (the import check) and
apply unchanged to newly discovered resources. Two components are never taken
from the workbook: ``trust`` is derived from the publisher identity and
protocol probes, and ``governance`` from credited compliance evidence
(:func:`agentdossier.compliance.engine.governance_from_evidence`), for seed
and discovered rows alike. The workbook's own values are kept as
``seed_components`` and its order as ``seed_rank`` so the change is auditable.

Rules that never change without a new score version:

* Components are normalized to 0-100 against ``seed_max`` before weighting.
* Weights are normalized by their sum (the General profile sums to 90).
* An unknown component contributes 0 and is reported in ``unknown``; it is
  never imputed. ``evidence_coverage`` is the share of profile weight backed
  by a known component.
* Scores are comparative discovery signals, not certification.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import SCORE_VERSION
from .util import load_config

COMPONENTS = ("adoption", "trust", "health", "ecosystem", "domain_fit", "governance", "docs")


@dataclass(frozen=True)
class ScoringConfig:
    version: str
    seed_max: dict[str, float]
    profiles: dict[str, dict[str, float]]
    domain_profiles: dict[str, str]

    @classmethod
    def load(cls) -> ScoringConfig:
        raw = load_config("scoring.json")
        return cls(
            version=raw["score_version"],
            seed_max={k: float(v["seed_max"]) for k, v in raw["components"].items()},
            profiles={k: {c: float(w) for c, w in v.items()} for k, v in raw["profiles"].items()},
            domain_profiles=dict(raw["domain_profiles"]),
        )

    def profile_for_domain(self, domain: str) -> str:
        try:
            return self.domain_profiles[domain]
        except KeyError as exc:
            raise KeyError(f"no scoring profile mapped for domain '{domain}'") from exc


@dataclass(frozen=True)
class ScoreResult:
    score: float
    profile: str
    version: str
    normalized: dict[str, float]
    evidence_coverage: float
    unknown: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "profile": self.profile,
            "score_version": self.version,
            "normalized": self.normalized,
            "evidence_coverage": self.evidence_coverage,
            "unknown": list(self.unknown),
        }


def normalize_components(
    raw: dict[str, float | None], cfg: ScoringConfig
) -> tuple[dict[str, float], tuple[str, ...]]:
    """Map raw component values onto 0-100. ``None`` means unknown."""
    normalized: dict[str, float] = {}
    unknown: list[str] = []
    for name in COMPONENTS:
        value = raw.get(name)
        if value is None:
            unknown.append(name)
            continue
        ceiling = cfg.seed_max[name]
        normalized[name] = max(0.0, min(100.0, 100.0 * float(value) / ceiling))
    return normalized, tuple(unknown)


def score(raw: dict[str, float | None], profile: str, cfg: ScoringConfig | None = None) -> ScoreResult:
    """Compute a domain score for one resource under one weight profile."""
    cfg = cfg or ScoringConfig.load()
    weights = cfg.profiles[profile]
    total_weight = sum(weights.values())
    normalized, unknown = normalize_components(raw, cfg)
    weighted = sum(weights[c] * normalized[c] for c in normalized)
    known_weight = sum(weights[c] for c in normalized)
    return ScoreResult(
        score=round(weighted / total_weight, 1),
        profile=profile,
        version=cfg.version if cfg.version else SCORE_VERSION,
        normalized={k: round(v, 3) for k, v in normalized.items()},
        evidence_coverage=round(known_weight / total_weight, 3) if total_weight else 0.0,
        unknown=unknown,
    )


def score_for_domain(
    raw: dict[str, float | None], domain: str, cfg: ScoringConfig | None = None
) -> ScoreResult:
    cfg = cfg or ScoringConfig.load()
    return score(raw, cfg.profile_for_domain(domain), cfg)


# ---------------------------------------------------------------------------
# Discovered resources: components from observable signals (v1 heuristics)
# ---------------------------------------------------------------------------


COMPONENTS_VERSION = "components-from-signals-1.0"
_DEFAULT_LOG_CEILING = 150000


def _days_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(UTC) - dt).total_seconds() / 86400


def components_from_signals(
    res: dict[str, Any], domain_confidence: float, cfg: ScoringConfig | None = None
) -> dict[str, float | None]:
    """Derive the seven components for a resource that has no seed values.

    Heuristic, versioned, and never imputed: a component with no supporting
    signal is ``None`` (unknown), which scores 0 and is flagged. Ceilings match
    ``config/scoring.json``.
    """
    cfg = cfg or ScoringConfig.load()
    sig: dict[str, Any] = res.get("signals") or {}
    protocols: dict[str, Any] = res.get("protocols") or {}
    ceiling = float(
        load_config("scoring.json")["discovered"].get("adoption_log_ceiling", _DEFAULT_LOG_CEILING)
    )

    # adoption /30: log-scaled popularity from stars (GitHub), likes (HF) or downloads
    adoption: float | None = None
    pop = None
    if sig.get("github_stars") is not None:
        pop = float(sig["github_stars"])
    elif sig.get("hf_likes") is not None:
        pop = float(sig["hf_likes"]) * 10  # likes are roughly an order of magnitude rarer than stars
    elif sig.get("hf_downloads") is not None:
        pop = float(sig["hf_downloads"]) / 100
    if pop is not None:
        adoption = min(30.0, 30.0 * math.log10(pop + 1) / math.log10(ceiling))

    # trust /25: identity tier and protocol evidence (compliance evidence lands in governance)
    identity_tier = (res.get("identity") or {}).get("tier")
    trust: float | None = None
    if identity_tier is not None or any(
        protocols.get(p, {}).get("status") != "unknown" for p in ("a2a", "mcp", "ard")
    ):
        base = {1: 20.0, 2: 18.0, 3: 15.0, 4: 10.0, 5: 6.0}.get(int(identity_tier or 5), 6.0)
        for p in ("a2a", "mcp", "ard"):
            st = protocols.get(p, {}).get("status")
            base += 2.0 if st == "verified" else 1.0 if st == "claimed" else 0.0
        if protocols.get("a2a", {}).get("signed"):
            base += 1.0
        if res.get("license"):
            base += 1.0
        trust = min(25.0, base)

    # health /20: recency of activity
    health: float | None = None
    pushed = sig.get("github_pushed_at") or sig.get("hf_last_modified") or sig.get("mcp_registry_updated_at")
    days = _days_since(pushed)
    if days is not None:
        health = (
            20.0 if days < 30 else 16.0 if days < 90 else 12.0 if days < 180 else 8.0 if days < 365 else 4.0
        )
        if sig.get("github_archived"):
            health = 2.0

    # ecosystem /15: protocol support and integration breadth
    eco = 0.0
    known = False
    for p, pts in (("mcp", 6.0), ("a2a", 5.0), ("ard", 4.0)):
        st = protocols.get(p, {}).get("status")
        if st in ("verified", "claimed"):
            eco += pts if st == "verified" else pts * 0.6
            known = True
    tags = res.get("tags") or []
    if tags:
        eco += min(3.0, 0.3 * len(tags))
        known = True
    if sig.get("mcp_transports"):
        eco += 1.0 * len(sig["mcp_transports"])
        known = True
    ecosystem: float | None = min(15.0, eco) if known else None

    # domain fit /100 from classifier confidence
    domain_fit: float | None = round(100.0 * domain_confidence, 1) if domain_confidence else None

    # governance /100: set per domain by the build from credited compliance evidence
    # (compliance.engine.governance_from_evidence); None here means "not yet computed"
    governance: float | None = None

    # docs /10: presence of description, homepage/readme, representative queries
    docs = 0.0
    if res.get("description"):
        docs += 4.0
    if sig.get("homepage") or res.get("url"):
        docs += 3.0
    if res.get("representative_queries"):
        docs += 2.0
    if res.get("capabilities"):
        docs += 1.0
    return {
        "adoption": round(adoption, 2) if adoption is not None else None,
        "trust": round(trust, 2) if trust is not None else None,
        "health": health,
        "ecosystem": round(ecosystem, 2) if ecosystem is not None else None,
        "domain_fit": domain_fit,
        "governance": governance,
        "docs": min(10.0, docs),
    }

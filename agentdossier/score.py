"""Domain scoring (BRD v3.2 §3.2, FR-08, FR-16, FR-25).

Score version ``sar-score-1.0``: seven weight profiles reproduce every score
in the 25 Sep 2026 seed workbook to within 0.07 points and apply unchanged
to newly discovered resources.

Rules that never change without a new score version:

* Components are normalized to 0-100 against ``seed_max`` before weighting.
* Weights are normalized by their sum (the General profile sums to 90).
* An unknown component contributes 0 and is reported in ``unknown``; it is
  never imputed. ``evidence_coverage`` is the share of profile weight backed
  by a known component.
* Scores are comparative discovery signals, not certification.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

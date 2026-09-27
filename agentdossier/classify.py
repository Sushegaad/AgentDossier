"""Domain classification (FR-07).

Keyword and phrase matcher over ``config/taxonomy.json``. Each domain gets a
confidence in [0, 1]; a resource is assigned every domain whose confidence
reaches ``min_confidence`` (default from ``config/scoring.json``). Seed rows
keep their sheet domains at confidence 1.0 and are never reclassified.

This is deliberately simple and dependency-free. An optional TF-IDF model in
the ``[connectors]`` extra can refine it later without changing this API.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .util import load_config

TAXONOMY_VERSION_KEY = "version"


@dataclass(frozen=True)
class Classification:
    domains: dict[str, float]  # domain -> confidence
    taxonomy_version: str
    matched: dict[str, list[str]]  # domain -> matched keywords


class Classifier:
    def __init__(self, taxonomy: dict | None = None, min_confidence: float | None = None):
        self.taxonomy = taxonomy or load_config("taxonomy.json")
        self.version = str(self.taxonomy.get(TAXONOMY_VERSION_KEY, "unversioned"))
        if min_confidence is None:
            min_confidence = float(load_config("scoring.json")["discovered"]["min_domain_confidence"])
        self.min_confidence = min_confidence
        self._patterns: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
        for domain, spec in self.taxonomy["domains"].items():
            pats = []
            for kw in spec.get("keywords", []):
                kw_norm = kw.strip().lower()
                # phrases ending with a space in the taxonomy mean "word boundary after"
                pattern = r"(?<![a-z0-9])" + re.escape(kw_norm.strip()) + r"(?![a-z0-9])"
                pats.append((kw_norm.strip(), re.compile(pattern)))
            self._patterns[domain] = pats

    def classify(self, *texts: str | None, category: str | None = None) -> Classification:
        text = " ".join(t for t in texts if t).lower()
        cat = (category or "").lower()
        domains: dict[str, float] = {}
        matched: dict[str, list[str]] = {}
        for domain, pats in self._patterns.items():
            hits = [kw for kw, pat in pats if pat.search(text)]
            cat_hits = [kw for kw, pat in pats if cat and pat.search(cat)]
            if not hits and not cat_hits:
                continue
            # Diminishing returns: 1 hit = 0.34, 2 = 0.56, 3 = 0.71, 4+ approaches 1; category hits count double.
            weight = len(set(hits)) + 2 * len(set(cat_hits))
            confidence = round(1 - (0.66**weight), 3)
            domains[domain] = confidence
            matched[domain] = sorted(set(hits) | set(cat_hits))
        kept = {d: c for d, c in domains.items() if c >= self.min_confidence}
        return Classification(
            domains=kept, taxonomy_version=self.version, matched={d: matched[d] for d in kept}
        )

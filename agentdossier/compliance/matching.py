"""Entity matching for compliance registries (FR-20).

Registries list legal entities and service offerings, not agents. A match
needs a normalized vendor (legal entity) and, where the registry lists
offerings, a product name. Confidence >= 0.9 (with entity >= 0.85 and, when
an offering is listed, product >= 0.8) is accepted automatically, 0.7-0.9
goes to ``data/review/matches.yaml``, below 0.7 is dropped.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from functools import lru_cache

from ..util import load_config

AUTO_ACCEPT = 0.9
REVIEW_MIN = 0.7
# An accept also needs both halves to agree: a strong entity match with a
# weak offering match (Oracle "SCM AI Agents" vs Oracle "Service Cloud")
# is a different product of the same vendor and goes to review instead.
ACCEPT_ENTITY_MIN = 0.85
ACCEPT_PRODUCT_MIN = 0.8
_LEGAL = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|ltd|limited|corp|corporation|co|company|gmbh|ag|sa|s\.a|plc|pty|bv|b\.v|srl|s\.r\.l|the)\b\.?"
)
_NOISE = re.compile(r"[^a-z0-9 ]")
_SPACES = re.compile(r"\s+")
_PRODUCT_NOISE = re.compile(
    r"\b(ai|agent|agents|platform|cloud|service|services|software|solution|solutions|enterprise|for|and|of)\b"
)


def normalize_entity(name: str | None) -> str:
    if not name:
        return ""
    s = name.lower().replace("&", " and ")
    s = _NOISE.sub(" ", s)
    s = _LEGAL.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def normalize_product(name: str | None) -> str:
    s = normalize_entity(name)
    s = _PRODUCT_NOISE.sub(" ", s)
    return _SPACES.sub(" ", s).strip()


def _strip(s: str, tokens: set[str]) -> str:
    return " ".join(w for w in s.split() if w not in tokens)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    jacc = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    contain = 1.0 if (a in b or b in a) and min(len(a), len(b)) >= 4 else 0.0
    return round(max(seq, 0.5 * seq + 0.5 * jacc, 0.85 * contain), 3)


@dataclass(frozen=True)
class Match:
    confidence: float
    entity_score: float
    product_score: float | None
    reason: str

    @property
    def decision(self) -> str:
        if (
            self.confidence >= AUTO_ACCEPT
            and self.entity_score >= ACCEPT_ENTITY_MIN
            and (self.product_score is None or self.product_score >= ACCEPT_PRODUCT_MIN)
        ):
            return "accept"
        if self.confidence >= REVIEW_MIN:
            return "review"
        return "drop"


_VENDOR_SPLIT = re.compile(r"\s*(?:/|\||,|;|\(|\)|\bvia\b|\bby\b)\s*|\s+and\s+|\s+&\s+")


@lru_cache(maxsize=1)
def _aliases() -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[str]]]:
    """(normalized name → canonical, canonical → all names, canonical → domains) from config/vendor_aliases.json."""
    try:
        doc = load_config("vendor_aliases.json")
    except FileNotFoundError:
        return {}, {}, {}
    lookup: dict[str, str] = {}
    names: dict[str, list[str]] = {}
    domains: dict[str, list[str]] = {}
    for canonical, entry in (doc.get("entities") or {}).items():
        all_names = [canonical, *(entry.get("aliases") or [])]
        names[canonical] = all_names
        domains[canonical] = [d.lower().removeprefix("www.") for d in entry.get("domains") or []]
        for n in all_names:
            lookup[normalize_entity(n)] = canonical
    return lookup, names, domains


def canonical_entities(vendor: str | None) -> list[str]:
    """Registry-spelled entities a vendor string names ("AWS" → ["Amazon"]; "GitHub / Microsoft" → both)."""
    lookup = _aliases()[0]
    out: list[str] = []
    for part in _raw_variants(vendor):
        c = lookup.get(normalize_entity(part))
        if c and c not in out:
            out.append(c)
    return out


def entity_domains(vendor: str | None) -> list[str]:
    """Domains the alias table records as the vendor's own."""
    domains = _aliases()[2]
    return [d for c in canonical_entities(vendor) for d in domains.get(c, [])]


def _raw_variants(vendor: str | None) -> list[str]:
    if not vendor:
        return []
    parts = [vendor.strip()]
    for piece in _VENDOR_SPLIT.split(vendor):
        piece = (piece or "").strip()
        if len(normalize_entity(piece)) >= 3 and piece not in parts:
            parts.append(piece)
    return parts


def vendor_variants(vendor: str | None) -> list[str]:
    """Every entity a compound vendor string names, longest first, plus registry spellings.

    Catalog vendors are often written as "GitHub / Microsoft", "OpenAI (Microsoft)" or
    "Salesforce, Inc. and MuleSoft". A registry lists one legal entity per row, so each
    part is tried on its own, after the whole string. Parts the alias table knows
    ("AWS") also try the registry's spelling ("Amazon") and every other alias.
    """
    parts = _raw_variants(vendor)
    names = _aliases()[1]
    for canonical in canonical_entities(vendor):
        for n in names.get(canonical, []):
            if n not in parts:
                parts.append(n)
    return parts


def match(vendor: str | None, product: str | None, entity: str | None, offering: str | None = None) -> Match:
    """Score a catalog (vendor, product) pair against a registry (entity, offering) pair.

    A compound vendor ("GitHub / Microsoft") is matched part by part and the best part wins.
    """
    variants = vendor_variants(vendor)
    if len(variants) > 1:
        best = max((_match_one(v, product, entity, offering) for v in variants), key=lambda m: m.confidence)
        return best
    return _match_one(vendor, product, entity, offering)


def _match_one(
    vendor: str | None, product: str | None, entity: str | None, offering: str | None = None
) -> Match:
    v, p = normalize_entity(vendor), normalize_product(product)
    e, o = normalize_entity(entity), normalize_product(offering)
    es = max(similarity(v, e), similarity(p, e) * 0.9) if e else 0.0
    ps: float | None = None
    if o:
        # Compare the product parts that are *not* the vendor name, so
        # "Oracle SCM" vs "Oracle Service Cloud" is judged on "scm" vs "osvc".
        pc, oc = _strip(p, set(v.split())), _strip(o, set(e.split()))
        if pc and oc:
            ps = max(similarity(pc, oc), similarity(p, o) * 0.9)
        else:
            ps = max(similarity(p, o), similarity(f"{v} {p}".strip(), o) * 0.95)
    if ps is None:
        conf = es
        reason = f"entity {es:.2f}"
    else:
        conf = 0.55 * es + 0.45 * ps if es >= 0.6 else 0.35 * es + 0.65 * ps
        reason = f"entity {es:.2f}, offering {ps:.2f}"
    return Match(confidence=round(min(1.0, conf), 3), entity_score=es, product_score=ps, reason=reason)

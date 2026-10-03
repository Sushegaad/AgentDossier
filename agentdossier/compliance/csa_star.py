"""CSA STAR Registry presence check (FR-20).

The registry index page lists every organization with a STAR listing and is
allowed by robots.txt. One weekly fetch of that page gives, per card, the
organization name, listed-since date and filter terms that encode the STAR
level (self-assessment / certification or attestation), STAR for AI level,
ISO/IEC 42001 and AIUC-1. Entry pages are not crawled (source register:
manual until terms are confirmed); everything here comes from the index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..connectors.base import ConnectorReport, SnapshotStore
from ..util import NetPolicy, fetch, now_iso, sha256
from .matching import Match, normalize_entity, similarity, vendor_variants

SOURCE = "csa_star"
INDEX_URL = "https://cloudsecurityalliance.org/star/registry"
_CARD = re.compile(r'<div class="c-card[^"]*star-registry-card" data-name="([^"]*)"([^>]*)>', re.S)
_TERMS = re.compile(r'data-filter-terms="([^"]*)"')
_NAME = re.compile(r"<p><strong>([^<]{1,160})</strong></p>")
_SINCE = re.compile(r"Listed Since:</strong>\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")
TERM_VARIANTS: dict[str, tuple[str, str]] = {
    # filter term -> (framework id, variant)
    "star_level_2": ("csa_star", "STAR_LEVEL_2"),
    "star_level_1": ("csa_star", "STAR_LEVEL_1"),
    "star_for_ai_level_2": ("csa_star", "STAR_FOR_AI"),
    "star_for_ai_level_1": ("csa_star", "STAR_FOR_AI"),
    "aiuc-1": ("csa_star", "AIUC_1"),
    "iso-iec-42001": ("iso42001", "ISO42001"),
}


@dataclass
class Listing:
    slug: str
    name: str
    terms: tuple[str, ...]
    listed_since: str | None

    @property
    def url(self) -> str:
        return f"{INDEX_URL}/{self.slug}"


def parse_index(html: str) -> dict[str, Listing]:
    out: dict[str, Listing] = {}
    cards = list(_CARD.finditer(html))
    for i, m in enumerate(cards):
        slug, attrs = m.group(1), m.group(2)
        terms_m = _TERMS.search(attrs)
        body = html[m.end() : cards[i + 1].start() if i + 1 < len(cards) else m.end() + 4000]
        name_m, since_m = _NAME.search(body), _SINCE.search(body)
        name = name_m.group(1).strip() if name_m else slug.replace("-", " ")
        terms = tuple(terms_m.group(1).split()) if terms_m else ()
        out[slug] = Listing(slug, name, terms, since_m.group(1) if since_m else None)
    return out


def load_index(
    store: SnapshotStore | None, policy: NetPolicy | None = None
) -> tuple[dict[str, Listing], str | None, ConnectorReport]:
    report = ConnectorReport(SOURCE)
    r = fetch(INDEX_URL, policy=policy, timeout=60, max_bytes=32_000_000)
    report.fetched = 1
    if not r.ok:
        report.error(f"{INDEX_URL}: {r.error}")
        return {}, None, report
    listings = parse_index(r.text)
    if store:
        store.save(SOURCE, "index", r.body)
    report.produced = len(listings)
    return listings, sha256(r.body), report


def find_match(vendor: str | None, index: dict[str, Listing]) -> tuple[Listing, Match] | None:
    """Best CSA STAR listing for a vendor; a compound vendor ("GitHub / Microsoft") tries each part."""
    variants = [normalize_entity(v) for v in vendor_variants(vendor)]
    variants = [v for v in variants if len(v) >= 3]
    if not variants:
        return None
    best: tuple[Listing, float] | None = None
    for lst in index.values():
        names = (normalize_entity(lst.name), normalize_entity(lst.slug.replace("-", " ")))
        s = max(similarity(v, n) for v in variants for n in names)
        if best is None or s > best[1]:
            best = (lst, s)
    if best is None or best[1] < 0.7:
        return None
    m = Match(
        confidence=best[1],
        entity_score=best[1],
        product_score=None,
        reason=f"entity {best[1]:.2f} (index card)",
    )
    return best[0], m


def to_records(lst: Listing, m: Match, payload_hash: str | None) -> list[dict[str, Any]]:
    """One record per credential the card advertises; STAR level 2 supersedes level 1."""
    variants: dict[tuple[str, str], None] = {}
    for term in lst.terms:
        fv = TERM_VARIANTS.get(term)
        if fv:
            variants[fv] = None
    if ("csa_star", "STAR_LEVEL_2") in variants:
        variants.pop(("csa_star", "STAR_LEVEL_1"), None)
    if not variants:
        variants[("csa_star", "STAR_LEVEL_1")] = None
    out = []
    for fw, variant in variants:
        out.append(
            {
                "framework": fw,
                "variant": variant,
                "status": "active",
                "tier": 1,
                "scope": "entity",
                "covers_resource": "unknown",
                "issuer": "Cloud Security Alliance",
                "certificate_id": lst.slug,
                "issued": lst.listed_since,
                "valid_until": None,
                "period_end": None,
                "evidence_url": lst.url,
                "source": SOURCE,
                "retrieved_at": now_iso(),
                "payload_hash": payload_hash,
                "match_confidence": m.confidence,
                "reviewer": None,
                "review_reason": m.reason,
                "next_check": None,
                "display": "",
                "detail": {
                    "organization": lst.name,
                    "terms": list(lst.terms),
                    "note": "From the STAR Registry index card; STAR Level 1 is a self-assessment (CAIQ), Level 2 a third-party certification or attestation.",
                },
            }
        )
    return out

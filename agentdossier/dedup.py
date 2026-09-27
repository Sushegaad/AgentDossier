"""Identity resolution and duplicate merging (FR-06).

Deterministic keys merge automatically; near-duplicates are written to
``data/review/matches.yaml`` for the maintainer and stay separate until a
decision is recorded there. Seed records win on name, vendor, category and
description; everything else is unioned.

Deterministic keys, in priority order: ARD URN, GitHub ``owner/repo``,
Hugging Face id, MCP Registry name, A2A card URL, canonical URL.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import ROOT, canonical_url, now_iso, slug

REVIEW_FILE = ROOT / "data" / "review" / "matches.yaml"
FUZZY_THRESHOLD = 0.92
PROTOCOL_RANK = {"verified": 4, "claimed": 3, "invalid": 2, "not_found": 1, "unknown": 0}
_STRIP = re.compile(r"\b(ai|agent|agents|platform|the|inc|llc|ltd|corp|copilot|studio)\b|[^a-z0-9 ]")


def identity_keys(res: dict[str, Any]) -> list[str]:
    ext = res.get("external_ids") or {}
    keys: list[str] = []
    if ext.get("ard"):
        keys.append(f"ard:{ext['ard'].lower()}")
    if ext.get("github"):
        keys.append(f"github:{ext['github'].lower()}")
    if ext.get("huggingface_space"):
        keys.append(f"hf:space:{ext['huggingface_space'].lower()}")
    if ext.get("huggingface_model"):
        keys.append(f"hf:model:{ext['huggingface_model'].lower()}")
    if ext.get("mcp_registry"):
        keys.append(f"mcp:{ext['mcp_registry'].lower()}")
    a2a = (res.get("protocols") or {}).get("a2a") or {}
    if a2a.get("card_url"):
        keys.append(f"a2a:{canonical_url(a2a['card_url'])}")
    cu = res.get("canonical_url") or canonical_url(res.get("url"))
    if cu and cu.count("/") >= 1 and not cu.startswith(("github.com", "huggingface.co")):
        keys.append(f"url:{cu}")
    elif cu and cu.startswith("github.com/") and cu.count("/") == 2:
        keys.append(f"github:{cu.split('/', 1)[1]}")
    return keys


def fuzzy_name(res: dict[str, Any]) -> str:
    text = f"{res.get('vendor') or ''} {res.get('name') or ''}".lower()
    text = _STRIP.sub(" ", text)
    return " ".join(sorted(set(text.split())))


@dataclass
class ReviewCandidate:
    a_id: str
    a_name: str
    b_id: str
    b_name: str
    similarity: float
    reason: str
    decision: str = "pending"  # pending | merge | keep_separate
    decided_by: str | None = None
    decided_on: str | None = None


@dataclass
class DedupResult:
    resources: list[dict[str, Any]]
    merged: int
    candidates: list[ReviewCandidate] = field(default_factory=list)


def _is_seed(res: dict[str, Any]) -> bool:
    return any(s["system"] == "seed_xlsx" for s in res["sources"])


def _seed_first(a: dict[str, Any], b: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return (b, a) if (_is_seed(b) and not _is_seed(a)) else (a, b)


def merge(primary: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Merge ``other`` into ``primary`` (seed wins on descriptive fields)."""
    for k in (
        "vendor",
        "category",
        "description",
        "url",
        "license",
        "deployment",
        "publisher_domain",
        "canonical_url",
    ):
        if not primary.get(k) and other.get(k):
            primary[k] = other[k]
    if primary.get("resource_type") == "agent" and other.get("resource_type") not in (None, "agent"):
        primary["resource_type"] = other["resource_type"]
    primary["external_ids"] = {**other.get("external_ids", {}), **primary.get("external_ids", {})}
    primary["tags"] = sorted(set(primary.get("tags", [])) | set(other.get("tags", [])))[:40]
    primary["capabilities"] = sorted(
        set(primary.get("capabilities", [])) | set(other.get("capabilities", []))
    )
    primary["signals"] = {**other.get("signals", {}), **primary.get("signals", {})}
    for proto in ("a2a", "mcp", "ard"):
        p, o = primary["protocols"].get(proto, {}), other["protocols"].get(proto, {})
        if PROTOCOL_RANK.get(o.get("status", "unknown"), 0) > PROTOCOL_RANK.get(
            p.get("status", "unknown"), 0
        ):
            primary["protocols"][proto] = o
    seen = {(s["system"], s.get("url")) for s in primary["sources"]}
    for s in other["sources"]:
        if (s["system"], s.get("url")) not in seen:
            primary["sources"].append(s)
    for k in ("domains",):
        merged = dict(other.get(k, {}))
        merged.update(primary.get(k, {}))
        primary[k] = merged
    if other.get("components") and not primary.get("components"):
        primary["components"] = other["components"]
    primary["first_seen"] = min(primary["first_seen"], other["first_seen"])
    primary["last_seen"] = max(primary["last_seen"], other["last_seen"])
    primary.setdefault("merged_ids", []).append(other["id"])
    return primary


def load_decisions(path: Path = REVIEW_FILE) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415 - optional (dev/connectors extra)
    except ImportError:  # pragma: no cover
        return {}
    doc = yaml.safe_load(path.read_text()) or {}
    out: dict[tuple[str, str], str] = {}
    for c in doc.get("candidates", []):
        if c.get("decision") in ("merge", "keep_separate"):
            out[(c["a_id"], c["b_id"])] = c["decision"]
            out[(c["b_id"], c["a_id"])] = c["decision"]
    return out


def dedup(
    resources: list[dict[str, Any]], decisions: dict[tuple[str, str], str] | None = None, fuzzy: bool = True
) -> DedupResult:
    decisions = decisions or {}
    by_key: dict[str, dict[str, Any]] = {}
    kept: list[dict[str, Any]] = []
    merged = 0
    candidates_shared: list[ReviewCandidate] = []
    for res in resources:
        target = None
        for key in identity_keys(res):
            if key in by_key:
                target = by_key[key]
                break
        if target is None:
            kept.append(res)
            for key in identity_keys(res):
                by_key.setdefault(key, res)
            continue
        if _is_seed(target) and _is_seed(res):
            # Two distinct workbook products sharing a URL or repo: keep both, ask the maintainer.
            kept.append(res)
            candidates_shared.append(
                ReviewCandidate(
                    target["id"], target["name"], res["id"], res["name"], 1.0, f"shared identity key {key}"
                )
            )
            continue
        primary, other = _seed_first(target, res)
        if primary is not target:  # the new record is the seed: swap roles in the kept list
            kept[kept.index(target)] = primary
        merge(primary, other)
        merged += 1
        for key in identity_keys(primary):
            by_key[key] = primary

    candidates: list[ReviewCandidate] = [
        c for c in candidates_shared if decisions.get((c.a_id, c.b_id)) is None
    ]
    if fuzzy:
        names = [(fuzzy_name(r), r) for r in kept]
        buckets: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        for fn, r in names:
            first = fn.split(" ")[0] if fn else ""
            buckets.setdefault(first, []).append((fn, r))
        final: list[dict[str, Any]] = []
        dropped: set[str] = set()
        for _, group in buckets.items():
            for i, (fa, a) in enumerate(group):
                for fb, b in group[i + 1 :]:
                    if not fa or not fb or a["id"] in dropped or b["id"] in dropped:
                        continue
                    sim = difflib.SequenceMatcher(None, fa, fb).ratio()
                    if sim < FUZZY_THRESHOLD:
                        continue
                    decision = decisions.get((a["id"], b["id"]))
                    if decision == "merge":
                        p, o = _seed_first(a, b)
                        merge(p, o)
                        dropped.add(o["id"])
                        merged += 1
                    elif decision is None:
                        candidates.append(
                            ReviewCandidate(
                                a["id"],
                                a["name"],
                                b["id"],
                                b["name"],
                                round(sim, 3),
                                f"name similarity {sim:.2f}",
                            )
                        )
        final = [r for r in kept if r["id"] not in dropped]
        kept = final
    return DedupResult(resources=kept, merged=merged, candidates=candidates)


def write_review_file(candidates: list[ReviewCandidate], path: Path = REVIEW_FILE) -> int:
    """Append new candidates (pending) to the review file; returns the number added."""
    try:
        import yaml  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return 0
    doc = yaml.safe_load(path.read_text()) if path.exists() else None
    doc = doc or {
        "notes": "Near-duplicate candidates. Set decision to merge or keep_separate, add decided_by and decided_on.",
        "candidates": [],
    }
    existing = {(c["a_id"], c["b_id"]) for c in doc["candidates"]}
    added = 0
    for c in candidates:
        if (c.a_id, c.b_id) in existing or (c.b_id, c.a_id) in existing:
            continue
        doc["candidates"].append({**c.__dict__, "found_on": now_iso()[:10]})
        added += 1
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return added


def resource_slug(res: dict[str, Any]) -> str:
    return slug(f"{res.get('vendor') or ''}-{res['name']}")[:80] or res["id"]

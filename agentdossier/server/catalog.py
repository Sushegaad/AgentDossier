"""In-memory catalog for the self-hosted server: loads a built catalog directory and answers
searches, listings and policy qualification (ARD REST semantics, BRD §4.3, FR-38).

Search is the Python counterpart of the site's ranker: taxonomy keywords give the
domain, tokens are matched against name / vendor / category / description / tags /
capabilities, and every hit carries a template explanation. It is deterministic and
needs no index build, which keeps the container to one process.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..policy.engine import evaluate
from ..util import CONFIG_DIR, load_json

_WORD = re.compile(r"[a-z0-9][a-z0-9+.#-]*")
_STOP = set(load_json(CONFIG_DIR / "intent_rules.json").get("stopwords", []))


def tokens(text: str | None) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower()) if t not in _STOP and len(t) > 1]


@dataclass
class Hit:
    record: dict[str, Any]
    score: float
    explanation: list[str]


class Catalog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.index: dict[str, Any] = {"records": []}
        self.records: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}
        self.by_slug: dict[str, dict[str, Any]] = {}
        self._text: dict[str, str] = {}
        self._taxonomy = load_json(CONFIG_DIR / "taxonomy.json")
        self.policies: dict[str, dict[str, Any]] = {}
        for p in sorted((CONFIG_DIR / "policy_templates").glob("*.json")):
            pol = load_json(p)
            self.policies[str(pol.get("id", p.stem))] = pol
        self.reload()

    # --- loading --------------------------------------------------------------------

    def reload(self) -> int:
        with self._lock:
            idx_path = self.path / "index.json"
            if not idx_path.exists():
                self.index, self.records = {"records": [], "scope": "private", "tenant": None}, []
                self.by_id, self.by_slug, self._text = {}, {}, {}
                return 0
            self.index = json.loads(idx_path.read_text())
            self.records = list(self.index.get("records", []))
            self.by_id = {r["id"]: r for r in self.records}
            self.by_slug = {r["slug"]: r for r in self.records}
            docs: dict[str, dict[str, Any]] = {}
            sd = self.path / "search-docs.json"
            if sd.exists():
                docs = {d["id"]: d for d in json.loads(sd.read_text())}
            self._text = {}
            for r in self.records:
                d = docs.get(r["id"], {})
                parts = [
                    r.get("name"),
                    r.get("vendor"),
                    r.get("category"),
                    r.get("description"),
                    " ".join(r.get("tags") or []),
                    d.get("capabilities"),
                    d.get("queries"),
                ]
                self._text[r["id"]] = " ".join(p for p in parts if p).lower()
            return len(self.records)

    def resource(self, id_or_slug: str) -> dict[str, Any] | None:
        r = self.by_id.get(id_or_slug) or self.by_slug.get(id_or_slug)
        if not r:
            return None
        p = self.path / "agents" / f"{r['id']}.json"
        return json.loads(p.read_text()) if p.exists() else r

    @property
    def meta(self) -> dict[str, Any]:
        return {k: v for k, v in self.index.items() if k != "records"}

    # --- search ---------------------------------------------------------------------

    def detect_domains(self, query: str) -> list[str]:
        q = f" {query.lower()} "
        found = []
        for d, spec in self._taxonomy.get("domains", {}).items():
            for kw in spec.get("keywords", []):
                if f" {kw.lower()}" in q:
                    found.append(d)
                    break
        return found

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        domain: str | None = None,
        resource_type: str | None = None,
        framework: str | None = None,
        max_tier: int | None = None,
        protocol: str | None = None,
    ) -> list[Hit]:
        q_tokens = tokens(query)
        domains = [domain] if domain else self.detect_domains(query)
        hits: list[Hit] = []
        for r in self.records:
            if resource_type and r.get("resource_type") != resource_type:
                continue
            if protocol and (r.get("protocols") or {}).get(protocol) not in ("verified", "claimed"):
                continue
            if framework:
                ok = [
                    c
                    for c in r.get("compliance_summary", [])
                    if c["framework"] == framework
                    and c["status"] == "active"
                    and (max_tier is None or c["tier"] <= max_tier)
                ]
                if not ok:
                    continue
            why: list[str] = []
            score = 0.0
            text = self._text.get(r["id"], "")
            name = (r.get("name") or "").lower()
            matched = [t for t in q_tokens if t in text]
            if q_tokens:
                cov = len(matched) / len(q_tokens)
                name_hits = sum(1 for t in q_tokens if t in name)
                score += 40 * cov + 15 * (name_hits / len(q_tokens))
                if matched:
                    why.append(f"matches {', '.join(matched[:4])}")
            best = None
            for d in domains or list((r.get("domains") or {}).keys()):
                e = (r.get("domains") or {}).get(d)
                if e and e.get("score") is not None and (best is None or e["score"] > best[1]):
                    best = (d, e["score"], e.get("rank"))
            if domains:
                if best:
                    score += 40 * best[1] / 100
                    why.append(f"#{best[2] or '–'} in {best[0]} (score {best[1]:.1f})")
                else:
                    score -= 5
            elif best:
                score += 20 * best[1] / 100
            active = [c for c in r.get("compliance_summary", []) if c["status"] == "active"]
            if active:
                tier = min(c["tier"] for c in active)
                score += 4 if tier <= 2 else 1
                why.append(f"evidence tier T{tier}")
            if q_tokens and not matched and not domains:
                continue
            if score <= 0:
                continue
            hits.append(Hit(r, round(score, 1), why))
        hits.sort(key=lambda h: (-h.score, h.record["name"].lower()))
        return hits[:limit]

    # --- qualification (FR-38) ----------------------------------------------------------

    def qualify(self, policy: dict[str, Any] | str, ids: list[str] | None = None) -> list[dict[str, Any]]:
        pol = self.policies[policy] if isinstance(policy, str) else policy
        targets = [self.resource(i) for i in ids] if ids else [self.resource(r["id"]) for r in self.records]
        out = []
        for res in targets:
            if not res:
                continue
            ev = evaluate(pol, res)
            out.append({"resourceId": res["id"], "name": res["name"], **ev.as_dict()})
        return out

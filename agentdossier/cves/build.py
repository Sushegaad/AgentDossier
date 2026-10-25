"""agentdossier cves update: collect → match → overrides → link → write.

Outputs ``data/cves/index.json`` (every candidate/included record, full; the site reads this one
file) and ``data/cves/state.json`` (the cursor for the next weekly window). The curated layer is
``data/curated/cve_overrides.yaml``: a person's status, note and corrections per CVE, and products
retired for good. Deterministic: the same inputs write the same bytes.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from ..util import CONFIG_DIR, ROOT
from . import match as m
from . import nvd

CONFIG = CONFIG_DIR / "cve_products.json"
OVERRIDES = ROOT / "data" / "curated" / "cve_overrides.yaml"
INCIDENTS = ROOT / "data" / "curated" / "incidents.yaml"
OUT_DIR = ROOT / "data" / "cves"
INDEX = OUT_DIR / "index.json"
STATE = OUT_DIR / "state.json"
SCHEMA = ROOT / "schema" / "cve_record.schema.json"
VERSION = "cves-1.0"
OVERRIDES_HEADER = """# The curated layer of the CVE registry (docs/cves.md). The pipeline writes data/cves/index.json;
# a person records decisions here and they are applied on every run:
#   cves:
#     CVE-2026-12957: { status: included, reviewer: "Name", checked_on: 2026-10-25, note: "..." }
#     CVE-2026-00001: { status: excluded, note: "a Windows component, not an agent" }
#     Optional per-CVE overrides: category, surface (list), related_agents (list), related_incidents.
#   exclude_products:            # CPE vendor:product prefixes never to list again
#     - { cpe: "microsoft:windows", why: "..." }
# `agentdossier cves include|exclude <id> --note` edits this file for you.
"""

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b")


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text())


def _yaml():  # noqa: ANN202
    import yaml  # noqa: PLC0415

    return yaml


def load_overrides(path: Path = OVERRIDES) -> dict[str, Any]:
    if not path.exists():
        return {"cves": {}, "exclude_products": []}
    doc = _yaml().safe_load(path.read_text()) or {}
    doc.setdefault("cves", {})
    doc.setdefault("exclude_products", [])
    return doc


def write_overrides(doc: dict[str, Any], path: Path = OVERRIDES) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _yaml().safe_dump(
        {"cves": doc.get("cves") or {}, "exclude_products": doc.get("exclude_products") or []},
        sort_keys=True,
        allow_unicode=True,
        width=110,
    )
    path.write_text(OVERRIDES_HEADER + body)


def apply_overrides(rec: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    o = (overrides.get("cves") or {}).get(rec["id"])
    if not o:
        return rec
    out = dict(rec)
    for key in ("status", "note", "reviewer", "category", "surface", "related_agents", "related_incidents"):
        if key in o and o[key] is not None:
            out[key] = o[key]
    if o.get("checked_on") is not None:
        v = o["checked_on"]
        out["checked_on"] = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return out


def incident_links(path: Path = INCIDENTS) -> dict[str, list[str]]:
    """CVE id → incident ids: an explicit ``cves:`` list on the record, else CVE ids in its text."""
    if not path.exists():
        return {}
    doc = _yaml().safe_load(path.read_text()) or {}
    out: dict[str, list[str]] = {}
    for inc in doc.get("incidents") or []:
        if inc.get("status") != "published":
            continue
        ids = set(inc.get("cves") or [])
        if not ids:
            ids = set(_CVE_RE.findall(json.dumps(inc, default=str)))
        for cid in ids:
            out.setdefault(cid, [])
            if inc["id"] not in out[cid]:
                out[cid].append(inc["id"])
    return {k: sorted(v) for k, v in out.items()}


def read_index(path: Path = INDEX) -> dict[str, Any]:
    if not path.exists():
        return {"version": VERSION, "built_at": None, "records": []}
    return json.loads(path.read_text())


def read_state(path: Path = STATE) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def validate(records: list[dict[str, Any]]) -> list[str]:
    """Schema problems, one line each; empty when jsonschema is not installed (CI has it)."""
    try:
        import jsonschema  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    schema = json.loads(SCHEMA.read_text())
    v = jsonschema.Draft202012Validator(schema)
    problems = []
    for r in records:
        for e in v.iter_errors(r):
            problems.append(f"{r.get('id')}: {e.message}")
    return problems


def update(
    *,
    config: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
    fetcher: nvd.Fetcher | None = None,
    api_key: str | None = None,
    backfill: bool = False,
    today: dt.date | None = None,
    existing: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
    links: dict[str, list[str]] | None = None,
    catalog_slugs: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Returns (index document, new state, report). Nothing is written here."""
    today = today or dt.date.today()
    config = config or load_config()
    overrides = overrides if overrides is not None else load_overrides()
    existing = existing if existing is not None else read_index()
    state = state if state is not None else read_state()
    links = links if links is not None else incident_links()
    # the overrides file's exclusions join the config's for matching
    cfg = dict(config)
    cfg["exclude_products"] = list(config.get("exclude_products") or []) + list(
        overrides.get("exclude_products") or []
    )
    fetcher = fetcher or nvd._default_fetcher(api_key)
    retrieved = today.isoformat()

    cursor = state.get("last_modified_cursor")
    if backfill or not cursor:
        urls = nvd.backfill_queries(cfg)
        mode = "backfill"
    else:
        since = dt.date.fromisoformat(cursor) - dt.timedelta(days=1)  # overlap a day so nothing slips
        urls = nvd.window_queries(since, today)
        mode = "window"
    fetched, errors = nvd.collect(urls, fetcher, retrieved)
    kev, kev_error = nvd.fetch_kev(fetcher)
    if kev_error:
        errors.append(f"KEV: {kev_error}")

    prior = {r["id"]: r for r in existing.get("records") or []}
    merged: dict[str, dict[str, Any]] = {}
    report: dict[str, Any] = {
        "mode": mode,
        "queries": len(urls),
        "fetched": len(fetched),
        "errors": errors,
        "new": [],
        "changed": 0,
        "kev_new": [],
        "rejected": [],
    }
    # a window run only carries changed records: keep every prior record and re-classify it with today's config
    for cid, rec in prior.items():
        merged[cid] = rec
    for cid, rec in fetched.items():
        if cid in merged and rec["last_modified"] > merged[cid].get("last_modified", ""):
            report["changed"] += 1
        merged[cid] = rec

    floor = str((config.get("backfill") or {}).get("since") or "")
    records: list[dict[str, Any]] = []
    for cid, rec in merged.items():
        if floor and (rec.get("published") or "") < floor:
            continue  # the registry starts with the agent era (config backfill.since)
        if str(rec.get("vuln_status") or "").lower().startswith("reject"):
            report["rejected"].append(cid)
            continue
        base = dict(rec)
        # re-run classification from the official fields (prior records carry them too)
        base["match"] = {"tests": [], "terms": []}
        base["category"] = "unclassified"
        base["surface"] = []
        base["related_agents"] = []
        for row in base.get("products") or []:
            row["product_id"] = None
        classified = m.classify(base, cfg)
        if classified is None:
            continue
        if catalog_slugs is not None:
            classified["related_agents"] = [s for s in classified["related_agents"] if s in catalog_slugs]
        # KEV: today's catalog when it was fetched; the prior value when the fetch failed
        classified["kev"] = kev.get(cid) if not kev_error else (prior.get(cid) or {}).get("kev")
        classified["related_incidents"] = links.get(cid, [])
        classified["status"] = "candidate"  # a person's decision lives only in the overrides file
        classified = apply_overrides(classified, overrides)
        if cid not in prior:
            report["new"].append(cid)
        if classified.get("kev") and not (prior.get(cid) or {}).get("kev"):
            report["kev_new"].append(cid)
        records.append(classified)
    records.sort(key=lambda r: r["id"])
    records.sort(
        key=lambda r: r.get("published") or "", reverse=True
    )  # newest first, id ascending within a day
    counts = {
        "total": len(records),
        "included": sum(1 for r in records if r["status"] == "included"),
        "candidate": sum(1 for r in records if r["status"] == "candidate"),
        "excluded": sum(1 for r in records if r["status"] == "excluded"),
        "kev": sum(1 for r in records if r.get("kev")),
        "unscored": sum(1 for r in records if not r.get("cvss")),
    }
    products = sorted(
        {p["product_id"] for r in records for p in r.get("products") or [] if p.get("product_id")}
    )
    doc = {
        "version": VERSION,
        "built_at": retrieved,
        "config_version": config.get("version"),
        "counts": counts,
        "products_matched": products,
        "records": records,
    }
    new_state = {"last_modified_cursor": today.isoformat(), "last_run": retrieved, "mode": mode}
    report["counts"] = counts
    report["new"] = sorted(report["new"])
    return doc, new_state, report


def write(doc: dict[str, Any], state: dict[str, Any], *, out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(json.dumps(doc, indent=1, sort_keys=False, ensure_ascii=False) + "\n")
    (out_dir / "state.json").write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")


def set_status(
    cve_id: str,
    status: str,
    note: str | None = None,
    *,
    reviewer: str | None = None,
    today: dt.date | None = None,
    path: Path = OVERRIDES,
) -> None:
    """``cves include|exclude``: record a person's decision in the overrides file."""
    today = today or dt.date.today()
    doc = load_overrides(path)
    row = dict(doc["cves"].get(cve_id) or {})
    row["status"] = status
    if note:
        row["note"] = note
    if reviewer:
        row["reviewer"] = reviewer
        row["checked_on"] = today.isoformat()
    doc["cves"][cve_id] = row
    write_overrides(doc, path)

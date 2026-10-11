"""Evidence engine (FR-22, FR-23, FR-25, FR-49): tiers, freshness, wording, credit.

Takes raw compliance records from the connectors and:

* applies the framework's expiry rule (``fixed_date``, ``period_end_plus_months``,
  ``recheck_months``, ``mirror_registry``) to set ``stale`` / ``expired``;
* renders ``display`` from the framework's wording templates (never
  "certified" for HIPAA; GDPR only per BRD §5.10);
* sets ``next_check`` from the source cadence;
* applies identity-first crediting: records on a resource whose identity
  tier is worse than 2 are kept but ``credited: false`` and shown as
  uncredited (``credited: false``); the site explains why once per dossier;
* computes the evidence-based governance component (0-100) from credited,
  active records over the domain's preset frameworks (``sar-score-2.0``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..util import CONFIG_DIR, load_json

FRAMEWORKS_VERSION = "frameworks-1.1"  # 1.1: Phase-2 set (GovRAMP, BSI C5, IRAP, DORA)
GOVERNANCE_VERSION = "sar-score-2.0"
CREDIT_MAX_IDENTITY_TIER = 2
DOMAIN_PRESETS: dict[str, list[str]] = {
    "healthcare": ["hipaa", "hitrust", "soc2"],
    "government": ["fedramp", "csa_star", "iso27001"],
    "finance": ["soc2", "iso27001", "pci_dss"],
    "insurance": ["soc2", "iso27001", "pci_dss", "hipaa"],
    "regulatory": ["soc2", "iso27001", "iso27701"],
    "legal": ["soc2", "iso27001", "iso27701"],
    "cybersecurity": ["soc2", "iso27001", "csa_star"],
    "data": ["soc2", "iso27001", "iso27701"],
    "business": ["soc2", "iso27001"],
    "technology": ["soc2", "iso27001", "iso42001"],
    "sales": ["soc2", "gdpr", "iso27701"],
    "supply_chain": ["soc2", "iso27001"],
}
ALL_DOMAINS_EXTRA = ["iso42001", "csa_star"]

_frameworks: dict[str, dict[str, Any]] | None = None


def frameworks() -> dict[str, dict[str, Any]]:
    global _frameworks
    if _frameworks is None:
        _frameworks = {p.stem: load_json(p) for p in sorted((CONFIG_DIR / "frameworks").glob("*.json"))}
    return _frameworks


def _date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:19].replace("Z", "")).replace(tzinfo=UTC)
    except ValueError:
        return None


def apply_freshness(rec: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    fw = frameworks().get(rec["framework"], {})
    rule = fw.get("expiry_rule", {"kind": "recheck_months", "months": 1})
    if int(rec.get("tier", 5)) == 4:
        rule = {"kind": "recheck_months", "months": 3}  # a claim is only as fresh as the last crawl
    kind = rule.get("kind")
    if rec["status"] in ("revoked", "in_process", "inherited", "not_found"):
        pass
    elif kind == "fixed_date":
        vu = _date(rec.get("valid_until"))
        if vu and vu < now:
            rec["status"] = "expired"
    elif kind == "period_end_plus_months":
        pe = _date(rec.get("period_end")) or _date(rec.get("issued"))
        if pe and pe + timedelta(days=30 * int(rule.get("months", 12))) < now:
            rec["status"] = "stale"
            rec["stale_since"] = (pe + timedelta(days=30 * int(rule.get("months", 12)))).date().isoformat()
    elif kind == "recheck_months":
        ra = _date(rec.get("retrieved_at"))
        if ra and ra + timedelta(days=30 * int(rule.get("months", 1))) < now:
            rec["status"] = "stale"
            rec["stale_since"] = (ra + timedelta(days=30 * int(rule.get("months", 1)))).date().isoformat()
    # mirror_registry: status is whatever the registry said on retrieval
    cadence = {"weekly": 7, "monthly": 30, "frozen baseline": 365}
    src: dict[str, Any] = next(
        (s for s in fw.get("sources", []) if s.get("kind") in ("registry", "marketplace", "vendor")), {}
    )
    days = cadence.get(src.get("cadence", "monthly"), 30)
    rec["next_check"] = (now + timedelta(days=days)).date().isoformat()
    return rec


def render_display(rec: dict[str, Any]) -> str:
    fw = frameworks().get(rec["framework"], {})
    wording = fw.get("wording", {})
    status = rec["status"]
    tier = int(rec["tier"])
    variant = rec.get("variant")
    variant_label = (
        (variant or "")
        .replace("_", " ")
        .title()
        .replace("Soc2", "SOC 2")
        .replace("Iso", "ISO ")
        .replace("Fedramp", "FedRAMP")
        .replace("Dpf", "DPF")
        .replace("Dpa", "DPA")
        .replace("Baa", "BAA")
        .replace("Hitrust", "HITRUST")
        .replace("Gpai", "GPAI")
        .replace("Art50", "Art. 50")
        .replace("Type Ii", "Type II")
        .replace("Star For Ai", "STAR for AI")
        .replace("Star Level", "STAR Level")
        .replace("Aiuc 1", "AIUC-1")
        .replace("Csa", "CSA")
        .replace("Nist Ai Rmf", "NIST AI RMF")
        .replace("Pci Dss", "PCI DSS")
        .replace("Available", "available")
        .replace("Active", "active")
        .replace("Aligned", "aligned")
        .replace("Statement", "statement")
    )
    ctx = {
        "registry": {
            "fedramp": "FedRAMP Marketplace",
            "csa_star": "CSA STAR Registry",
            "dpf": "dataprivacyframework.gov",
            "iaf_certsearch": "IAF CertSearch",
        }.get(rec.get("source", ""), rec.get("issuer") or rec.get("source") or "registry"),
        "marketplace": {
            "aws_marketplace": "AWS Marketplace",
            "microsoft_agent_store": "Microsoft Agent Store",
            "google_cloud_marketplace": "Google Cloud Marketplace",
        }.get(rec.get("source", ""), "marketplace"),
        "date": (rec.get("retrieved_at") or "")[:10],
        "issuer": rec.get("issuer") or "issuer",
        "identifier": rec.get("certificate_id") or "",
        "valid_until": rec.get("valid_until") or "",
        "period_end": rec.get("period_end") or rec.get("issued") or "",
        "stale_since": rec.get("stale_since") or "",
        "source": {"vendor_trust_centers": "vendor page", "curated": "maintainer review"}.get(
            rec.get("source", ""), rec.get("source", "")
        ),
        "type": "Type II" if variant == "SOC2_TYPE_II" else "Type I" if variant == "SOC2_TYPE_I" else "",
        "level": (rec.get("detail") or {}).get("impact_level") or variant_label.replace("FedRAMP ", ""),
        "status": (rec.get("detail") or {}).get("fedramp_status") or status.replace("_", " "),
        "variant_label": variant_label or fw.get("name", rec["framework"]),
        "framework": fw.get("name", rec["framework"]),
        "scope": rec.get("scope", ""),
    }
    key = status if status in ("expired", "stale", "in_process", "inherited") else f"tier{tier}"
    template = wording.get(key) or wording.get(f"tier{tier}") or "{framework}: {status}"
    try:
        text = template.format(**ctx)
    except (KeyError, IndexError):
        text = f"{ctx['framework']}: {status}"
    if (
        variant_label
        and not any(tok in template for tok in ("{variant", "{level}", "{type}", "SOC 2", "HIPAA"))
        and rec["framework"] not in ("hipaa",)
        and key.startswith("tier")
        and variant
    ):
        text = f"{variant_label}: {text}"
    # rec["credited"] is False when the publisher's identity is unconfirmed; the dossier says so
    # once, above the ledger, rather than on every row
    return text


def finalize(
    records: list[dict[str, Any]], identity_tier: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Dedupe by (framework, variant) keeping the best tier, then apply freshness, credit and wording."""
    best: dict[tuple[str, str | None], dict[str, Any]] = {}
    for rec in records:
        key = (rec["framework"], rec.get("variant"))
        cur = best.get(key)
        if (
            cur is None
            or int(rec["tier"]) < int(cur["tier"])
            or (
                int(rec["tier"]) == int(cur["tier"])
                and (rec.get("retrieved_at") or "") > (cur.get("retrieved_at") or "")
            )
        ):
            best[key] = rec
    out = []
    for rec in best.values():
        rec = apply_freshness(dict(rec), now)
        rec["credited"] = bool(rec["status"] == "active" and identity_tier <= CREDIT_MAX_IDENTITY_TIER)
        rec["display"] = render_display(rec)
        out.append(rec)
    out.sort(key=lambda r: (int(r["tier"]), r["framework"], r.get("variant") or ""))
    return out


VENDOR_LEVEL_CREDIT = 0.5


def _agent_scoped(rec: dict[str, Any]) -> bool:
    """Same split as web/src/lib/dossier.ts agentScoped(): about this agent, or about its vendor."""
    if rec.get("covers_resource") == "yes":
        return True
    if rec.get("covers_resource") == "inherited":
        return False
    return rec.get("scope") != "entity"


def governance_from_evidence(
    records: list[dict[str, Any]], domain: str
) -> tuple[float | None, dict[str, Any]]:
    """Governance component (0-100) for a domain from credited active records over its preset frameworks."""
    preset = DOMAIN_PRESETS.get(domain, ["soc2", "iso27001"]) + ALL_DOMAINS_EXTRA
    fws = frameworks()
    detail: dict[str, Any] = {"preset": preset, "credited": {}, "version": GOVERNANCE_VERSION}
    if not records:
        return None, detail
    total = 0.0
    for fw_id in preset:
        credit = fws.get(fw_id, {}).get("credit", {})
        best = 0.0
        for rec in records:
            if rec["framework"] == fw_id and rec.get("credited") and rec["status"] == "active":
                value = float(credit.get(str(rec["tier"]), 0.0))
                if not _agent_scoped(rec):
                    value *= VENDOR_LEVEL_CREDIT  # the vendor was assessed; this agent's scope is unknown
                best = max(best, value)
        if best:
            detail["credited"][fw_id] = best
        total += best
    return round(100.0 * total / len(preset), 1), detail


def changelog_events(
    previous_index: dict[str, Any] | None, current: list[dict[str, Any]], built_at: str
) -> list[dict[str, Any]]:
    """Diff compliance summaries between the last published index and the current build (FR-53)."""
    prev: dict[str, dict[tuple[str, str | None], dict[str, Any]]] = {}
    for r in (previous_index or {}).get("records", []):
        prev[r["id"]] = {(c["framework"], c.get("variant")): c for c in r.get("compliance_summary", [])}
    events = []
    for res in current:
        before = prev.get(res["id"], {})
        now = {(c["framework"], c.get("variant")): c for c in res.get("compliance", [])}
        for key, c in now.items():
            b = before.get(key)
            if b is None:
                events.append(
                    {
                        "at": built_at,
                        "resource_id": res["id"],
                        "resource": res["name"],
                        "event": "badge_added",
                        "framework": key[0],
                        "variant": key[1],
                        "tier": c["tier"],
                        "status": c["status"],
                        "source": c.get("source"),
                    }
                )
            elif b.get("tier") != c["tier"] or b.get("status") != c["status"]:
                events.append(
                    {
                        "at": built_at,
                        "resource_id": res["id"],
                        "resource": res["name"],
                        "event": "badge_changed",
                        "framework": key[0],
                        "variant": key[1],
                        "from": {"tier": b.get("tier"), "status": b.get("status")},
                        "to": {"tier": c["tier"], "status": c["status"]},
                    }
                )
        for key, b in before.items():
            if key not in now:
                events.append(
                    {
                        "at": built_at,
                        "resource_id": res["id"],
                        "resource": res["name"],
                        "event": "badge_removed",
                        "framework": key[0],
                        "variant": key[1],
                        "from": {"tier": b.get("tier"), "status": b.get("status")},
                    }
                )
    return events


def append_changelog(events: list[dict[str, Any]], path: Path) -> int:
    if not events:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return len(events)

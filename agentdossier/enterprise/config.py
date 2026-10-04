"""Enterprise scan configuration (BRD §4.4, FR-42): load, validate, and turn into a NetPolicy.

The file is exactly the documented shape (``schema/enterprise_config.schema.json``).
Authorization is part of the configuration on purpose: a scan only runs when an
operator has recorded who authorized it and under which ticket, and the scanner
can only reach what ``scope`` allows. There is no allow-public switch.
"""

from __future__ import annotations

import ipaddress
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import ROOT, NetPolicy, load_json

SCHEMA = ROOT / "schema" / "enterprise_config.schema.json"
DEFAULT_PORTS = [443, 80, 8080, 8000, 3000]
DEFAULT_LIMITS = {"requests_per_host_per_sec": 4.0, "concurrency": 16, "timeout_sec": 8.0}
DEFAULT_PROBES = {"ard": True, "a2a": True, "mcp_server_card": True, "mcp_handshake": False}
MAX_CIDR_HOSTS = 4096


class ConfigError(ValueError):
    pass


@dataclass
class EnterpriseConfig:
    tenant: str
    authorized_by: str
    ticket: str
    allow_cidrs: list[str]
    allow_hosts: list[str]
    target_cidrs: list[str] = field(default_factory=list)
    target_hosts: list[str] = field(default_factory=list)
    dns_domains: list[str] = field(default_factory=list)
    registries: list[str] = field(default_factory=list)
    ports: list[int] = field(default_factory=lambda: list(DEFAULT_PORTS))
    probes: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_PROBES))
    limits: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    headers_from_env: dict[str, str] = field(default_factory=dict)
    ca_bundle: str | None = None
    output_dir: Path = ROOT / "build" / "enterprise"
    schedule: str | None = None  # 5-field cron, evaluated by the server's scheduler
    path: Path | None = None

    @property
    def policy(self) -> NetPolicy:
        return NetPolicy(
            mode="enterprise",
            allow_cidrs=list(self.allow_cidrs),
            allow_hosts=list(self.allow_hosts),
            ca_bundle=self.ca_bundle,
        )

    def headers(self) -> dict[str, str]:
        """Resolve auth headers from the environment; never from the config file itself."""
        out = {}
        for header, env in self.headers_from_env.items():
            val = os.environ.get(env)
            if val:
                out[header] = val
        return out

    def missing_env(self) -> list[str]:
        return [env for env in self.headers_from_env.values() if not os.environ.get(env)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant": self.tenant,
            "authorized_by": self.authorized_by,
            "ticket": self.ticket,
            "scope": {"allow_cidrs": self.allow_cidrs, "allow_hosts": self.allow_hosts},
            "targets": {
                "cidrs": self.target_cidrs,
                "hosts": self.target_hosts,
                "dns_domains": self.dns_domains,
                "registries": self.registries,
            },
            "ports": self.ports,
            "probes": self.probes,
            "limits": self.limits,
            "schedule": self.schedule,
        }


def validate_document(doc: Any) -> list[str]:
    """Schema validation with jsonschema when available, else the structural checks that matter."""
    problems: list[str] = []
    try:
        import jsonschema  # noqa: PLC0415

        v = jsonschema.Draft202012Validator(load_json(SCHEMA))
        for err in sorted(v.iter_errors(doc), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "<root>"
            problems.append(f"{loc}: {err.message}")
        return problems
    except ImportError:
        pass
    if not isinstance(doc, dict):
        return ["config must be a JSON object"]
    for key in ("tenant", "authorized_by", "ticket", "scope", "targets"):
        if key not in doc:
            problems.append(f"{key}: required")
    if isinstance(doc.get("scope"), dict) and "allow_cidrs" not in doc["scope"]:
        problems.append("scope/allow_cidrs: required")
    return problems


def _cidrs_ok(cidrs: list[str]) -> list[str]:
    bad = []
    for c in cidrs:
        try:
            ipaddress.ip_network(c, strict=False)
        except ValueError:
            bad.append(c)
    return bad


def load(path: str | Path) -> EnterpriseConfig:
    p = Path(path)
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{p}: {exc}") from exc
    problems = validate_document(doc)
    if problems:
        raise ConfigError(f"{p}: " + "; ".join(problems))
    scope = doc["scope"]
    targets = doc.get("targets", {})
    bad = _cidrs_ok(scope.get("allow_cidrs", []) + targets.get("cidrs", []))
    if bad:
        raise ConfigError(f"{p}: invalid CIDR(s): {', '.join(bad)}")
    limits = dict(DEFAULT_LIMITS)
    limits.update(doc.get("limits", {}))
    probes = dict(DEFAULT_PROBES)
    probes.update(doc.get("probes", {}))
    return EnterpriseConfig(
        tenant=doc["tenant"],
        authorized_by=doc["authorized_by"],
        ticket=doc["ticket"],
        allow_cidrs=list(scope.get("allow_cidrs", [])),
        allow_hosts=list(scope.get("allow_hosts", [])),
        target_cidrs=list(targets.get("cidrs", [])),
        target_hosts=list(targets.get("hosts", [])),
        dns_domains=list(targets.get("dns_domains", [])),
        registries=list(targets.get("registries", [])),
        ports=list(doc.get("ports") or DEFAULT_PORTS),
        probes=probes,
        limits=limits,
        headers_from_env=dict((doc.get("auth") or {}).get("headers_from_env", {})),
        ca_bundle=(doc.get("tls") or {}).get("ca_bundle"),
        output_dir=Path(doc.get("output_dir") or ROOT / "build" / "enterprise" / doc["tenant"]),
        schedule=(doc.get("schedule") or {}).get("cron") if isinstance(doc.get("schedule"), dict) else None,
        path=p,
    )

"""Turn the configured targets into concrete origins to probe.

* ``hosts`` and ``cidrs`` become ``https://host:port`` / ``http://host:port`` origins
  for every configured port (443 and 8443 use https, everything else http first).
* ``dns_domains`` are resolved through ARD's Service Binding records:
  ``_entries._agents.<domain>`` (static entry source) and ``_search._agents.<domain>``
  (registry search endpoint), when dnspython is installed.
* ``registries`` are ARD registries whose ``GET /agents`` listing is paged through.

CIDR expansion is capped at ``MAX_CIDR_HOSTS`` addresses per run; larger ranges
are meant to be split across configurations and tickets.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any

from .config import MAX_CIDR_HOSTS, EnterpriseConfig

HTTPS_PORTS = {443, 8443}


@dataclass
class Target:
    origin: str
    kind: str  # host | cidr | dns | registry
    via: str | None = None
    notes: list[str] = field(default_factory=list)


def _origins_for_host(host: str, ports: list[int]) -> list[str]:
    out = []
    for port in ports:
        scheme = "https" if port in HTTPS_PORTS else "http"
        default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
        out.append(f"{scheme}://{host}" if default else f"{scheme}://{host}:{port}")
    return out


def expand_cidrs(cidrs: list[str], cap: int = MAX_CIDR_HOSTS) -> tuple[list[str], list[str]]:
    hosts: list[str] = []
    warnings: list[str] = []
    for c in cidrs:
        net = ipaddress.ip_network(c, strict=False)
        n = net.num_addresses
        if len(hosts) + n > cap:
            take = max(0, cap - len(hosts))
            warnings.append(f"{c}: {n} addresses exceed the per-run cap of {cap}; probing the first {take}")
            for i, addr in enumerate(net.hosts() if n > 2 else net):
                if i >= take:
                    break
                hosts.append(str(addr))
            continue
        hosts.extend(str(a) for a in (net.hosts() if n > 2 else net))
    return hosts, warnings


def resolve_svcb(name: str) -> list[dict[str, Any]]:
    """SVCB lookup via dnspython. Returns [{target, port}], empty when unavailable or absent."""
    try:
        import dns.resolver  # noqa: PLC0415
    except ImportError:
        return []
    try:
        answers = dns.resolver.resolve(name, "SVCB")
    except Exception:  # noqa: BLE001 - NXDOMAIN, timeouts, no SVCB support: all mean "no record"
        return []
    out = []
    for rr in answers:
        target = str(getattr(rr, "target", "")).rstrip(".")
        params = getattr(rr, "params", {}) or {}
        port = None
        for key, val in params.items():
            if str(key).lower().endswith("port") or getattr(key, "value", None) == 3:
                port = int(getattr(val, "port", 0) or 0) or None
        if target and target != ".":
            out.append({"target": target, "port": port})
    return out


def dns_targets(domains: list[str]) -> tuple[list[Target], list[str]]:
    targets: list[Target] = []
    registries: list[str] = []
    for domain in domains:
        for rec in resolve_svcb(f"_entries._agents.{domain}"):
            port = rec["port"] or 443
            origin = f"https://{rec['target']}" if port == 443 else f"https://{rec['target']}:{port}"
            targets.append(Target(origin, "dns", via=f"_entries._agents.{domain}"))
        for rec in resolve_svcb(f"_search._agents.{domain}"):
            port = rec["port"] or 443
            origin = f"https://{rec['target']}" if port == 443 else f"https://{rec['target']}:{port}"
            registries.append(origin)
    return targets, registries


def plan(cfg: EnterpriseConfig, *, use_dns: bool = True) -> dict[str, Any]:
    """Everything the scanner will touch, before it touches anything (dry-run output)."""
    warnings: list[str] = []
    targets: list[Target] = []
    for h in cfg.target_hosts:
        for o in _origins_for_host(h, cfg.ports):
            targets.append(Target(o, "host"))
    hosts, w = expand_cidrs(cfg.target_cidrs)
    warnings += w
    for h in hosts:
        for o in _origins_for_host(h, cfg.ports):
            targets.append(Target(o, "cidr"))
    registries = list(cfg.registries)
    if use_dns and cfg.dns_domains:
        t, r = dns_targets(cfg.dns_domains)
        targets += t
        registries += r
        if not t and not r:
            warnings.append(
                "dns_domains: no _entries._agents / _search._agents SVCB records found (or dnspython missing)"
            )
    seen: set[str] = set()
    unique: list[Target] = []
    for tgt in targets:
        if tgt.origin not in seen:
            seen.add(tgt.origin)
            unique.append(tgt)
    # scope check: every target must be inside the authorized scope, or it is refused up front
    policy = cfg.policy
    in_scope: list[Target] = []
    refused: list[dict[str, str]] = []
    for tgt in unique:
        try:
            policy.check(tgt.origin)
            in_scope.append(tgt)
        except Exception as exc:  # noqa: BLE001 - FetchBlockedError or unresolvable host
            refused.append({"origin": tgt.origin, "reason": str(exc)})
    return {
        "tenant": cfg.tenant,
        "targets": [{"origin": x.origin, "kind": x.kind, "via": x.via} for x in in_scope],
        "registries": sorted(set(registries)),
        "refused": refused,
        "warnings": warnings,
        "probes": cfg.probes,
        "limits": cfg.limits,
    }

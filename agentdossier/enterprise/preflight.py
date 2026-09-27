"""Preflight (FR-42): everything that must be true before a scan is allowed to start.

Each check is pass / warn / fail with a plain sentence. A fail blocks the scan.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import MAX_CIDR_HOSTS, EnterpriseConfig


@dataclass
class Check:
    id: str
    status: str  # pass | warn | fail
    message: str


@dataclass
class Preflight:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == "fail" for c in self.checks)

    def add(self, id_: str, status: str, message: str) -> None:
        self.checks.append(Check(id_, status, message))

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checks": [c.__dict__ for c in self.checks]}


def _net(c: str) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    return ipaddress.ip_network(c, strict=False)


def run(cfg: EnterpriseConfig, *, resolve_dns: bool = True) -> Preflight:
    pf = Preflight()

    # authorization record
    if len(cfg.authorized_by.strip()) >= 3 and cfg.ticket.strip():
        pf.add("authorization", "pass", f"authorized by {cfg.authorized_by} under ticket {cfg.ticket}")
    else:
        pf.add(
            "authorization", "fail", "authorized_by and ticket must name a person/office and a change record"
        )

    # scope
    if not cfg.allow_cidrs and not cfg.allow_hosts:
        pf.add("scope", "fail", "scope.allow_cidrs (or allow_hosts) is empty: nothing would be reachable")
    else:
        wide = [c for c in cfg.allow_cidrs if _net(c).prefixlen < 8]
        if wide:
            pf.add(
                "scope",
                "warn",
                f"very wide scope: {', '.join(wide)}; consider narrowing to the agent subnets",
            )
        else:
            pf.add(
                "scope", "pass", f"{len(cfg.allow_cidrs)} CIDR(s), {len(cfg.allow_hosts)} host(s) authorized"
            )
        public = [
            c
            for c in cfg.allow_cidrs
            if not (_net(c).is_private or _net(c).is_loopback or _net(c).is_link_local)
        ]
        if public:
            pf.add(
                "scope_public",
                "warn",
                f"scope includes public address space: {', '.join(public)}; the scanner will reach the internet",
            )

    # targets inside scope
    nets = [_net(c) for c in cfg.allow_cidrs]
    outside = [
        c
        for c in cfg.target_cidrs
        if not any(_net(c).subnet_of(n) for n in nets if n.version == _net(c).version)  # type: ignore[arg-type]
    ]
    if outside:
        pf.add(
            "targets_in_scope", "fail", f"target CIDR(s) outside the authorized scope: {', '.join(outside)}"
        )
    else:
        pf.add("targets_in_scope", "pass", "every target CIDR lies inside scope.allow_cidrs")
    total = sum(_net(c).num_addresses for c in cfg.target_cidrs)
    if total > MAX_CIDR_HOSTS:
        pf.add(
            "target_size",
            "warn",
            f"{total} addresses in target CIDRs; only the first {MAX_CIDR_HOSTS} are probed per run",
        )
    if not (cfg.target_cidrs or cfg.target_hosts or cfg.dns_domains or cfg.registries):
        pf.add("targets", "fail", "no targets configured")
    else:
        pf.add(
            "targets",
            "pass",
            f"{len(cfg.target_hosts)} host(s), {len(cfg.target_cidrs)} CIDR(s), {len(cfg.dns_domains)} DNS domain(s), {len(cfg.registries)} registr{'y' if len(cfg.registries) == 1 else 'ies'}",
        )

    # hostnames resolve, and into scope
    if resolve_dns:
        for h in cfg.target_hosts + [
            r.split("//", 1)[-1].split("/", 1)[0].split(":")[0] for r in cfg.registries
        ]:
            try:
                addrs = {str(i[4][0]) for i in socket.getaddrinfo(h, None)}
            except socket.gaierror:
                pf.add(f"dns:{h}", "warn", f"{h} does not resolve from here")
                continue
            in_scope = h.lower() in {x.lower() for x in cfg.allow_hosts} or any(
                ipaddress.ip_address(a) in n
                for a in addrs
                for n in nets
                if ipaddress.ip_address(a).version == n.version
            )
            pf.add(
                f"dns:{h}",
                "pass" if in_scope else "fail",
                f"{h} -> {', '.join(sorted(addrs))}{'' if in_scope else ' (outside scope)'}",
            )

    # probes and limits
    if cfg.probes.get("mcp_handshake"):
        pf.add(
            "mcp_handshake",
            "warn",
            "MCP handshake enabled: the scanner will send initialize + tools/list (never tools/call)",
        )
    else:
        pf.add("mcp_handshake", "pass", "MCP handshake off; server cards only")
    rate = float(cfg.limits.get("requests_per_host_per_sec", 4))
    pf.add(
        "rate_limit",
        "pass" if rate <= 10 else "warn",
        f"{rate} requests/host/second, concurrency {cfg.limits.get('concurrency')}",
    )

    # credentials and TLS
    missing = cfg.missing_env()
    if cfg.headers_from_env and missing:
        pf.add("auth_env", "fail", f"environment variable(s) not set: {', '.join(missing)}")
    elif cfg.headers_from_env:
        pf.add(
            "auth_env",
            "pass",
            f"auth header(s) resolved from the environment: {', '.join(cfg.headers_from_env)}",
        )
    if cfg.ca_bundle:
        if Path(cfg.ca_bundle).is_file():
            pf.add("tls", "pass", f"CA bundle {cfg.ca_bundle}")
        else:
            pf.add("tls", "fail", f"CA bundle not found: {cfg.ca_bundle}")

    # output
    try:
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.output_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        pf.add("output_dir", "pass", f"writable: {cfg.output_dir}")
    except OSError as exc:
        pf.add("output_dir", "fail", f"cannot write to {cfg.output_dir}: {exc}")
    if os.environ.get("AGENTDOSSIER_SITE") is None:
        pf.add("site", "warn", "AGENTDOSSIER_SITE not set; catalog links default to http://localhost:8080/")
    return pf

"""Self-test (FR-41): prove the scanner works end to end without touching the real network.

Starts a throw-away HTTP publisher on 127.0.0.1 that serves a valid ARD manifest,
an A2A agent card and an MCP server card, runs preflight and a real scan against
it with a loopback-only scope, and checks that all three surface in the catalog
as ``scope: private`` records. Exit code 0 means the installation can scan.
"""

from __future__ import annotations

import http.server
import json
import socketserver
import tempfile
import threading
from pathlib import Path
from typing import Any

from ..util import ROOT
from . import preflight, scanner
from .config import EnterpriseConfig

FIXTURES = ROOT / "tests" / "fixtures"

MANIFEST = {
    "entries": [
        {
            "@context": "https://agenticresourcediscovery.org/context/v1",
            "identifier": "urn:air:selftest.local:agent:claims-intake",
            "displayName": "Self-test Claims Intake Agent",
            "type": "application/a2a-agent-card+json",
            "url": "http://127.0.0.1/.well-known/agent-card.json",
            "description": "Fixture agent published by the AgentDossier self-test.",
            "capabilities": ["claims intake"],
            "representativeQueries": ["file a claim"],
            "tags": ["selftest"],
        }
    ]
}
A2A_CARD = {
    "name": "Self-test A2A Agent",
    "description": "A2A card served by the AgentDossier self-test.",
    "url": "http://127.0.0.1/a2a",
    "version": "1.0.0",
    "protocolVersion": "1.0",
    "supportedInterfaces": [{"url": "http://127.0.0.1/a2a", "protocolBinding": "JSONRPC"}],
    "capabilities": {"streaming": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [{"id": "echo", "name": "Echo", "description": "echo", "tags": ["selftest"]}],
}
MCP_CARD = {
    "name": "Self-test MCP Server",
    "description": "MCP server card served by the AgentDossier self-test.",
    "version": "0.1.0",
    "remotes": [{"type": "streamable-http", "url": "http://127.0.0.1/mcp"}],
    "tools": [{"name": "ping"}],
}


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        doc = self.routes.get(self.path)
        if doc is None:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(doc).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # silence
        pass


class FixturePublisher:
    """Loopback publisher used by the self-test and by tests."""

    def __init__(self) -> None:
        routes: dict[str, Any] = {
            "/.well-known/ard.json": MANIFEST,
            "/.well-known/agent-card.json": A2A_CARD,
            "/.well-known/mcp.json": MCP_CARD,
        }
        handler = type("H", (_Handler,), {"routes": routes})
        self.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FixturePublisher:
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def config_for(port: int, out_dir: Path) -> EnterpriseConfig:
    return EnterpriseConfig(
        tenant="selftest",
        authorized_by="AgentDossier self-test",
        ticket="SELFTEST",
        allow_cidrs=["127.0.0.0/8"],
        allow_hosts=[],
        target_hosts=["127.0.0.1"],
        ports=[port],
        probes={"ard": True, "a2a": True, "mcp_server_card": True, "mcp_handshake": False},
        limits={"requests_per_host_per_sec": 20, "concurrency": 4, "timeout_sec": 5},
        output_dir=out_dir,
    )


def run(out_dir: Path | None = None) -> dict[str, Any]:
    tmp = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="agentdossier-selftest-"))
    result: dict[str, Any] = {"ok": False, "steps": []}
    with FixturePublisher() as pub:
        cfg = config_for(pub.port, tmp)
        pf = preflight.run(cfg, resolve_dns=False)
        result["steps"].append({"step": "preflight", "ok": pf.ok, "checks": pf.as_dict()["checks"]})
        if not pf.ok:
            return result
        rep = scanner.scan(cfg, use_dns=False)
        found = {p.get("ard"): 1 for p in rep["probed"]}
        catalog = Path(rep["catalog"])
        index = json.loads((catalog / "index.json").read_text())
        names = sorted(r["name"] for r in index["records"])
        protocols = {r["name"]: r["protocols"] for r in index["records"]}
        # The ARD entry points at the A2A card, so dedup may fold the card into the entry (a2a: verified)
        # or keep it as its own record; either proves all three probes worked.
        a2a_ok = "Self-test A2A Agent" in names or any(
            p.get("a2a") == "verified" for n, p in protocols.items() if n == "Self-test Claims Intake Agent"
        )
        ok = (
            {"Self-test Claims Intake Agent", "Self-test MCP Server"} <= set(names)
            and a2a_ok
            and index["scope"] == "private"
            and index["tenant"] == "selftest"
        )
        result["steps"].append(
            {
                "step": "scan",
                "ok": ok,
                "origin": pub.origin,
                "probed": rep["probed"],
                "found": names,
                "protocols": protocols,
                "catalog": str(catalog),
                "errors": rep["errors"],
                "ard_statuses": list(found),
            }
        )
        result["ok"] = ok
        result["catalog"] = str(catalog)
    return result

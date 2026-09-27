"""FR-04: MCP adapter against spec-shaped fixtures and a local mock server (list-only handshake)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentdossier.standards import mcp
from agentdossier.util import NetPolicy
from tests.conftest import FIXTURES, load_fixture


def test_parse_sse_and_json_responses():
    sse = (FIXTURES / "mcp" / "tools_list.sse").read_text()
    msg = mcp.parse_rpc_response("text/event-stream", sse, 2)
    assert msg["result"]["tools"][0]["name"] == "get_weather"
    body = json.dumps(load_fixture("mcp", "initialize_response.json"))
    assert mcp.parse_rpc_response("application/json", body, 1)["result"]["protocolVersion"] == "2025-06-18"
    assert mcp.parse_rpc_response("application/json", body, 99) is not None  # single object is returned as-is


def test_server_card_validation_and_summary():
    card = load_fixture("mcp", "server_card.json")
    errors, warnings = mcp.validate_card(card)
    assert errors == [] and warnings == []
    s = mcp.summarize_card(card)
    assert s["remotes"][0]["url"] == "https://mcp.example.com/mcp" and s["tools"] == ["get_weather"]
    errors, _ = mcp.validate_card({"name": "x"})
    assert any("transport" in e for e in errors)


def test_forbidden_methods_are_never_sent():
    with pytest.raises(ValueError):
        mcp._rpc("http://127.0.0.1:1/mcp", "tools/call", {}, 1, None, policy=None, headers=None, timeout=1)


class _MockMCP(BaseHTTPRequestHandler):
    seen: list[str] = []

    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        msg = json.loads(self.rfile.read(length) or b"{}")
        method = msg.get("method")
        self.seen.append(method)
        assert self.headers.get("MCP-Protocol-Version") == "2025-06-18"
        if method == "initialize":
            body = json.dumps(load_fixture("mcp", "initialize_response.json")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "sess-123")
        elif method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        elif method == "tools/list":
            assert self.headers.get("Mcp-Session-Id") == "sess-123"
            body = (
                (FIXTURES / "mcp" / "tools_list.sse")
                .read_text()
                .replace('"id":2', f'"id":{msg["id"]}')
                .encode()
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
        elif method in ("resources/list", "prompts/list"):
            name = "resources_list.json" if method == "resources/list" else "prompts_list.json"
            data = load_fixture("mcp", name)
            data["id"] = msg["id"]
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self):
        self.seen.append("DELETE")
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def mock_server():
    _MockMCP.seen = []
    srv = HTTPServer(("127.0.0.1", 0), _MockMCP)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


def test_handshake_is_list_only(mock_server):
    policy = NetPolicy(mode="enterprise", allow_cidrs=["127.0.0.0/8"])
    report = mcp.handshake(mock_server, policy=policy, timeout=5)
    assert report["status"] == "verified"
    assert report["protocol_version"] == "2025-06-18"
    assert report["server_info"]["name"] == "ExampleServer"
    assert [t["name"] for t in report["tools"]] == ["get_weather"]
    assert [r["name"] for r in report["resources"]] == ["main.rs"]
    assert [p["name"] for p in report["prompts"]] == ["code_review"]
    assert report["session_id_issued"] is True
    assert _MockMCP.seen == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "resources/list",
        "prompts/list",
        "DELETE",
    ]
    assert not any(m in _MockMCP.seen for m in mcp.FORBIDDEN_METHODS)


def test_handshake_blocked_by_public_policy(mock_server):
    report = mcp.handshake(mock_server, policy=NetPolicy(), timeout=5)
    assert report["status"] == "unknown" and "blocked" in (report.get("error") or "")
    assert _MockMCP.seen == []

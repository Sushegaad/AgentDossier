"""Security: SSRF guard and scanner scope (plan section 9)."""

import socket

import pytest

from agentdossier.util import FetchBlockedError, NetPolicy, fetch


def _resolver(mapping):
    def getaddrinfo(host, port, *args, **kwargs):
        if host not in mapping:
            raise socket.gaierror("nx")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], port))]

    return getaddrinfo


def test_public_mode_blocks_private_and_metadata_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _resolver({"internal.test": "10.1.2.3", "meta.test": "169.254.169.254", "lo.test": "127.0.0.1"}),
    )
    policy = NetPolicy()
    for host in ("internal.test", "meta.test", "lo.test"):
        with pytest.raises(FetchBlockedError):
            policy.check(f"https://{host}/x")


def test_public_mode_allows_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"pub.test": "93.184.216.34"}))
    NetPolicy().check("https://pub.test/")


def test_enterprise_mode_allows_only_allowlist(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        _resolver(
            {
                "a.corp": "10.20.4.9",
                "b.corp": "10.99.0.1",
                "pub.test": "93.184.216.34",
                "named.corp": "172.16.5.5",
            }
        ),
    )
    policy = NetPolicy(mode="enterprise", allow_cidrs=["10.20.0.0/16"], allow_hosts=["named.corp"])
    policy.check("https://a.corp/")
    policy.check("https://named.corp/")
    with pytest.raises(FetchBlockedError):
        policy.check("https://b.corp/")
    with pytest.raises(FetchBlockedError):
        policy.check("https://pub.test/")


def test_non_http_scheme_is_blocked():
    with pytest.raises(FetchBlockedError):
        NetPolicy().check("file:///etc/passwd")


def test_fetch_returns_blocked_result_instead_of_raising(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _resolver({"lo.test": "127.0.0.1"}))
    r = fetch("https://lo.test/.well-known/ard.json")
    assert not r.ok and r.error.startswith("blocked")


def test_fetch_connects_to_the_vetted_address_not_a_second_lookup(monkeypatch):
    """DNS rebinding: the resolver answers public first, private second. The connection must go
    to the address that was checked, and the private answer must never be dialled."""
    answers = iter(["93.184.216.34", "10.0.0.1", "10.0.0.1"])
    seen = []

    def getaddrinfo(host, port, *a, **k):
        ip = next(answers)
        seen.append(ip)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]

    dialled = []

    def create_connection(addr, *a, **k):
        dialled.append(addr[0])
        raise OSError("no network in tests")

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    r = fetch("http://rebind.test/x", retries=0, timeout=1)
    assert not r.ok and "no network" in (r.error or "")
    assert dialled == ["93.184.216.34"] and seen[0] == "93.184.216.34"


def test_fetch_vets_every_redirect_hop(monkeypatch):
    """A public host redirecting to a private address is stopped at the hop."""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/secret")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        policy = NetPolicy(mode="enterprise", allow_cidrs=["127.0.0.0/8"])
        r = fetch(f"http://127.0.0.1:{srv.server_port}/go", policy=policy, retries=0, timeout=2)
        assert not r.ok and "outside the authorized scan scope" in (r.error or "")
        r = fetch(f"http://127.0.0.1:{srv.server_port}/go", policy=policy, follow_redirects=False, retries=0)
        assert r.status == 302
    finally:
        srv.shutdown()

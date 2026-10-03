"""Protocol claims: curated vendor documentation and self-description mark a protocol as claimed."""

from __future__ import annotations

from agentdossier.models import new_resource, protocol_block
from agentdossier.protocol_claims import apply_claims, load_curated_protocols


def _res(name, **kw):
    r = new_resource(name=name, source_system="test", url=kw.pop("url", None), vendor=kw.pop("vendor", None))
    r.update(kw)
    return r


def test_curated_claim_marks_claimed_and_keeps_probe_result(tmp_path):
    cur = tmp_path / "protocols.yaml"
    cur.write_text(
        "claims:\n"
        "  - name: Copilot Studio\n    checked_by: maintainer\n    checked_on: 2026-10-02\n"
        "    mcp:\n      evidence_url: https://learn.example/mcp\n      note: docs\n"
        "  - name: Undated\n    mcp: https://x\n"  # no checked_on -> ignored
    )
    entries = load_curated_protocols(cur)
    assert [e["name"] for e in entries] == ["Copilot Studio"]
    res = _res("Copilot Studio", url="https://example.com/x")
    res["protocols"]["mcp"] = protocol_block("not_found", checked_at="2026-10-01T00:00:00Z")
    counts = apply_claims([res], entries, self_description=False)
    assert counts == {"curated": 1, "self_description": 0}
    mcp = res["protocols"]["mcp"]
    assert mcp["status"] == "claimed" and mcp["source"] == "curated_claim"
    assert mcp["evidence_url"] == "https://learn.example/mcp" and mcp["probe"]["status"] == "not_found"
    assert res["protocols"]["a2a"]["status"] == "unknown"


def test_claim_never_outranks_verified():
    res = _res("Copilot Studio")
    res["protocols"]["mcp"] = protocol_block("verified", endpoint="https://example.com/mcp")
    apply_claims([res], [{"name": "Copilot Studio", "checked_on": "2026-10-02", "mcp": "https://docs"}])
    assert res["protocols"]["mcp"]["status"] == "verified"


def test_self_description_from_tags_and_text():
    a = _res("Thing", tags=["gradio", "mcp-server"])
    b = _res("Other", description="Implements the Agent2Agent protocol for hand-off")
    c = _res("Plain", description="A CRM assistant")
    counts = apply_claims([a, b, c], [])
    assert counts["self_description"] == 2
    assert (
        a["protocols"]["mcp"]["status"] == "claimed" and a["protocols"]["mcp"]["source"] == "self_description"
    )
    assert b["protocols"]["a2a"]["status"] == "claimed" and a["protocols"]["a2a"]["status"] == "unknown"
    assert all(p["status"] == "unknown" for p in c["protocols"].values())


def test_shipped_curated_file_loads():
    entries = load_curated_protocols()
    assert entries and all(e.get("checked_on") for e in entries)

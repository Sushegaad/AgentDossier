"""What counts as agent-related, and how a record is classified. Pure functions over records.

Test A — the affected product is on the list (config/cve_products.json): a CPE vendor:product
match, or the product's exact name in the description (whole words). Test B — the weakness is
agent-specific: an agent CWE (CWE-1427), or the description matches the vocabulary (one strong
phrase, or two distinct weak ones). A record is a candidate when either test passes; the reasons
are kept on the record so a reviewer reads *why* before deciding.
"""

from __future__ import annotations

import re
from typing import Any

# surface tags: CWE ids and description phrases that signal each
_SURFACE: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "prompt_injection": ({"CWE-1427"}, ("prompt injection", "llm prompting", "injected prompt")),
    "code_execution": (
        {"CWE-94", "CWE-95", "CWE-77", "CWE-78", "CWE-502", "CWE-1336"},
        (
            "code execution",
            "command injection",
            "arbitrary code",
            "arbitrary commands",
            "execute code",
            "template injection",
            "deserialization",
        ),
    ),
    "tool_execution": (
        set(),
        (
            "tool call",
            "tool execution",
            "mcp server",
            "model context protocol",
            "tool invocation",
            "function call",
        ),
    ),
    "exfiltration": (
        {"CWE-200", "CWE-532", "CWE-359"},
        (
            "exfiltrat",
            "information disclosure",
            "disclose information",
            "sensitive information",
            "data leak",
            "leak ",
        ),
    ),
    "credential_access": (
        {"CWE-522", "CWE-798", "CWE-312", "CWE-256"},
        ("credential", "api key", "access token", "secret"),
    ),
    "auth_bypass": (
        {"CWE-287", "CWE-288", "CWE-306", "CWE-862", "CWE-863", "CWE-639", "CWE-284"},
        (
            "authentication bypass",
            "bypass authentication",
            "without authentication",
            "unauthenticated",
            "missing authorization",
            "improper access control",
            "improper authorization",
        ),
    ),
    "supply_chain": (
        {"CWE-829", "CWE-506", "CWE-1395"},
        ("supply chain", "malicious package", "dependency confusion"),
    ),
    "privilege_escalation": (
        {"CWE-269", "CWE-250", "CWE-266"},
        ("elevation of privilege", "privilege escalation", "elevate privileges", "escalate privileges"),
    ),
    "ssrf": ({"CWE-918"}, ("server-side request forgery", "ssrf")),
    "path_traversal": ({"CWE-22", "CWE-23", "CWE-36"}, ("path traversal", "directory traversal")),
    "dos": ({"CWE-400", "CWE-770", "CWE-835"}, ("denial of service", "resource exhaustion")),
}


def _phrase_re(phrase: str) -> re.Pattern[str]:
    esc = re.escape(phrase.lower())
    # whole-word for short tokens so "llm" never matches inside another word, "agent" not "agentless"
    return re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if len(phrase) <= 6 else esc)


def _cpe_key(vendor: str, product: str) -> str:
    return f"{vendor.lower()}:{product.lower()}"


def product_match(rec: dict[str, Any], config: dict[str, Any]) -> list[tuple[dict[str, Any], str, str]]:
    """(product entry, test, term) for every listed product this record affects."""
    hits: list[tuple[dict[str, Any], str, str]] = []
    excluded = {str(e.get("cpe", "")).lower() for e in config.get("exclude_products") or []}
    rec_cpes = [_cpe_key(p["vendor"], p["product"]) for p in rec.get("products") or []]
    if any(any(c.startswith(x) for x in excluded) for c in rec_cpes):
        return []
    text = (rec.get("description") or "").lower()
    for prod in config.get("products") or []:
        matched = False
        for pat in prod.get("cpe") or []:
            pat_l = pat.lower()
            if any(c == pat_l or (pat_l.endswith(":") and c.startswith(pat_l)) for c in rec_cpes):
                hits.append((prod, "A:cpe", pat))
                matched = True
                break
        if matched:
            continue
        for name in [prod["name"], *(prod.get("names") or [])]:
            if len(name) >= 4 and _phrase_re(name).search(text):
                hits.append((prod, "A:name", name))
                break
    return hits


def vocabulary_match(rec: dict[str, Any], config: dict[str, Any]) -> list[str]:
    text = (rec.get("description") or "").lower()
    vocab = config.get("vocabulary") or {}
    strong = [t for t in vocab.get("strong") or [] if _phrase_re(t).search(text)]
    weak = [t for t in vocab.get("weak") or [] if _phrase_re(t).search(text)]
    if strong:
        return sorted(set(strong + weak))
    if len(set(weak)) >= 2:
        return sorted(set(weak))
    return []


def surface_tags(rec: dict[str, Any]) -> list[str]:
    text = (rec.get("description") or "").lower()
    cwes = set(rec.get("cwe") or [])
    out = []
    for tag, (tag_cwes, phrases) in _SURFACE.items():
        if cwes & tag_cwes or any(p in text for p in phrases):
            out.append(tag)
    if "tool_execution" in out and not any(w in text for w in ("execut", "command", "run ", "invoke")):
        out.remove("tool_execution")  # naming MCP is not enough; the weakness must run something
    return out


def classify(rec: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
    """Apply both tests. Returns the classified record, or None when neither test passes."""
    excluded = {str(e.get("cpe", "")).lower() for e in config.get("exclude_products") or []}
    rec_cpes = [_cpe_key(p["vendor"], p["product"]) for p in rec.get("products") or []]
    if any(any(c.startswith(x) for x in excluded) for c in rec_cpes):
        return None  # a retired product never lists again, whatever the description says
    tests: list[str] = []
    terms: list[str] = []
    products = product_match(rec, config)
    for prod, test, term in products:
        if test not in tests:
            tests.append(test)
        terms.append(f"{prod['id']}:{term}")
    agent_cwes = set(config.get("cwe_agent") or [])
    if set(rec.get("cwe") or []) & agent_cwes:
        tests.append("B:cwe")
        terms.extend(sorted(set(rec.get("cwe") or []) & agent_cwes))
    vocab = vocabulary_match(rec, config)
    if vocab:
        tests.append("B:vocabulary")
        terms.extend(vocab)
    if not tests:
        return None
    out = dict(rec)
    out["match"] = {"tests": tests, "terms": terms}
    # category: the listed product's, else unclassified (a Test-B-only record)
    cats = [prod["category"] for prod, _, _ in products]
    rank = ["product", "framework", "protocol", "infrastructure"]
    out["category"] = sorted(cats, key=rank.index)[0] if cats else "unclassified"
    out["surface"] = surface_tags(rec)
    # mark which listed product each affected-product row belongs to, and the agents it maps to
    by_cpe = {pat.lower(): prod for prod, test, pat in products if test == "A:cpe"}
    for row in out["products"]:
        key = _cpe_key(row["vendor"], row["product"])
        for pat, prod in by_cpe.items():
            if key == pat or (pat.endswith(":") and key.startswith(pat)):
                row["product_id"] = prod["id"]
    if not out["products"] and products:  # NVD had no CPE yet; record the name match as a product row
        for prod, test, _ in products:
            if test == "A:name":
                out["products"].append(
                    {
                        "vendor": prod["vendor"],
                        "product": prod["name"],
                        "versions_affected": None,
                        "fixed_in": None,
                        "product_id": prod["id"],
                    }
                )
    agents: list[str] = []
    for prod, _, _ in products:
        for slug in prod.get("agents") or []:
            if slug not in agents:
                agents.append(slug)
    out["related_agents"] = agents
    return out

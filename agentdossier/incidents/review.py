"""Machine review of incident candidates: the weekly refresh reads each candidate's source and
publishes what clears the bar — no human in the loop, every decision on file.

For every ``status: new`` candidate (and every ``status: placeholder`` record still waiting), the
article behind the link is fetched through the guarded client, stripped to text, and a model is
asked one structured question *against that text only*: is this a specific, real event in which an
AI agent attacked, defended or was the target? If so, the record's fields — date, AI role,
category, an "as reported" summary, attacker and defender as the source describes them, MITRE
ATT&CK tactics, models and agents named — come back as JSON, validated here field by field. A
verdict that is an incident, confident, and backed by a source that is not an aggregator is
published: a schema-valid record appended to incidents.yaml with
``reviewer: "model: <name> (automated review)"`` so every row says who reviewed it. Anything
else is dismissed with the model's reason kept on the candidate. Nothing is invented: a field the
source does not state stays null, the model is told to summarise and never to reproduce payloads,
prompts or commands, and no private individual is named.

The model is called through the Anthropic Messages API with the stdlib client (no SDK); the key
is ``ANTHROPIC_API_KEY``. ``--offline <dir>`` replays saved articles and verdicts for tests and
container runs. A row can still be retracted by hand (``incidents dismiss``), and the weekly PR
body lists every decision.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..util import FetchResult, fetch
from .scout import (
    CANDIDATES,
    INCIDENTS,
    _q,
    _yaml,
    next_incident_id,
    read_candidates,
    strip_html,
    write_candidates,
)

DEFAULT_MODEL = os.environ.get("INCIDENT_REVIEW_MODEL", "claude-sonnet-5-5")
API_URL = "https://api.anthropic.com/v1/messages"
ARTICLE_CHARS = 14_000
PUBLISH_CONFIDENCE = 0.8
TACTIC_RE = re.compile(r"^TA00\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AI_ROLES = ("attacker", "defender", "target")
CATEGORIES = ("red_team", "injection_eval", "incident", "ctf")
SOURCE_TYPES = ("vendor", "researcher", "press", "aggregator", "other")

Fetcher = Callable[[str], FetchResult]
Completer = Callable[[str, str], str]

SYSTEM = (
    "You review public reports for a registry of real events in which an AI agent (an LLM-driven "
    "system that takes actions: calls tools, runs commands, browses, writes code) attacked a system, "
    "defended one, or was the target of an attack. You read ONE article and answer ONLY from its text. "
    "Rules: never invent a fact the article does not state — leave the field null; summarise, never "
    "reproduce prompts, payloads, commands or exploit details; name organisations, products and "
    "models, never private individuals; describe each side as the article does, without attribution "
    "or blame of your own. Opinion pieces, product announcements, surveys, general warnings, benchmark "
    "papers without a concrete run, and articles about AI that do not involve an agent taking actions "
    "are NOT incidents. Reply with a single JSON object and nothing else."
)

SCHEMA_HINT = """{
  "incident": true|false,
  "confidence": 0.0-1.0,
  "reason": "one sentence: why this is or is not a registry incident",
  "source_type": "vendor|researcher|press|aggregator|other",
  "title": "short, factual, as the article frames it",
  "date": "YYYY-MM-DD of the event (null if the article gives none)",
  "window": "a span like 'July 2026' or null",
  "ai_role": "attacker|defender|target",
  "category": "incident (a real-world event) | red_team (a disclosed researcher test) | injection_eval (a benchmark or evaluation run) | ctf",
  "summary": "2-4 sentences, as reported, past tense, no payloads",
  "attacker": "who or what attacked, as described (e.g. 'an autonomous agent run by an unknown actor')",
  "defender": "who defended or was targeted, as described",
  "scale": "numbers the article states (systems, records, hours) or null",
  "impact": "what the article says the effect was, or null",
  "tactics": ["MITRE ATT&CK tactic ids like TA0001 that the described behaviour matches"],
  "models_named": [{"name": "model or agent product named", "role": "attacker|defender|target"}],
  "agents_named": ["agent product names named in the article"],
  "vendor_response": "what the vendor/defender did, as stated, or null",
  "timeline": [{"date": "YYYY-MM-DD or label", "text": "what happened, as stated"}]
}"""


@dataclass
class Verdict:
    incident: bool
    confidence: float
    reason: str
    source_type: str = "other"
    title: str | None = None
    date: str | None = None
    window: str | None = None
    ai_role: str | None = None
    category: str | None = None
    summary: str | None = None
    attacker: str | None = None
    defender: str | None = None
    scale: str | None = None
    impact: str | None = None
    tactics: list[str] = field(default_factory=list)
    models_named: list[dict[str, str]] = field(default_factory=list)
    agents_named: list[str] = field(default_factory=list)
    vendor_response: str | None = None
    timeline: list[dict[str, str]] = field(default_factory=list)

    def publishable(self) -> tuple[bool, str]:
        """The bar: an incident, confident, with a date and the fields a record needs, from a source
        that is not an aggregator."""
        if not self.incident:
            return False, self.reason or "not an incident"
        if self.confidence < PUBLISH_CONFIDENCE:
            return False, f"confidence {self.confidence:.2f} below {PUBLISH_CONFIDENCE}: {self.reason}"
        if self.source_type == "aggregator":
            return False, "source is an aggregator; needs a first-party or researcher/press report"
        missing = [
            k
            for k in ("date", "ai_role", "category", "summary", "attacker", "defender")
            if not getattr(self, k)
        ]
        if missing:
            return False, f"the article does not state: {', '.join(missing)}"
        return True, self.reason


def _str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_verdict(text: str) -> Verdict:
    """The model's JSON, validated field by field; anything malformed becomes a non-incident verdict."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return Verdict(False, 0.0, "model reply was not JSON")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return Verdict(False, 0.0, f"model reply was not valid JSON: {e.msg}")
    if not isinstance(raw, dict):
        return Verdict(False, 0.0, "model reply was not an object")
    try:
        conf = max(0.0, min(1.0, float(raw.get("confidence") or 0)))
    except (TypeError, ValueError):
        conf = 0.0
    date = _str(raw.get("date"))
    tactics = [t for t in (raw.get("tactics") or []) if isinstance(t, str) and TACTIC_RE.match(t)]
    models = [
        {"name": str(x["name"]).strip(), "role": x["role"]}
        for x in (raw.get("models_named") or [])
        if isinstance(x, dict) and x.get("name") and x.get("role") in AI_ROLES
    ]
    timeline = [
        {"date": str(x["date"]).strip(), "text": str(x["text"]).strip()}
        for x in (raw.get("timeline") or [])
        if isinstance(x, dict) and x.get("date") and x.get("text")
    ][:12]
    src = raw.get("source_type")
    return Verdict(
        incident=bool(raw.get("incident")),
        confidence=conf,
        reason=_str(raw.get("reason")) or "",
        source_type=src if src in SOURCE_TYPES else "other",
        title=_str(raw.get("title")),
        date=date if date and DATE_RE.match(date) else None,
        window=_str(raw.get("window")),
        ai_role=raw.get("ai_role") if raw.get("ai_role") in AI_ROLES else None,
        category=raw.get("category") if raw.get("category") in CATEGORIES else None,
        summary=_str(raw.get("summary")),
        attacker=_str(raw.get("attacker")),
        defender=_str(raw.get("defender")),
        scale=_str(raw.get("scale")),
        impact=_str(raw.get("impact")),
        tactics=sorted(set(tactics)),
        models_named=models[:10],
        agents_named=[str(a).strip() for a in (raw.get("agents_named") or []) if str(a).strip()][:10],
        vendor_response=_str(raw.get("vendor_response")),
        timeline=timeline,
    )


# ---- the model -------------------------------------------------------------------------------


def anthropic_completer(
    api_key: str, model: str = DEFAULT_MODEL, *, post: Callable[..., FetchResult] = fetch
) -> Completer:
    """A (system, user) -> text function over the Anthropic Messages API, through the guarded client."""
    do_fetch = post

    def _complete(system: str, user: str) -> str:
        body = json.dumps(
            {
                "model": model,
                "max_tokens": 1800,
                "temperature": 0,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        ).encode()
        r = do_fetch(
            API_URL,
            method="POST",
            data=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=90.0,
            retries=2,
        )
        if r.error or r.status != 200:
            raise RuntimeError(f"model call failed: {r.error or f'HTTP {r.status}'}: {r.body[:300]!r}")
        doc = json.loads(r.body)
        return "".join(
            part.get("text", "") for part in doc.get("content") or [] if part.get("type") == "text"
        )

    return _complete


def user_prompt(title: str, url: str, outlet: str | None, text: str) -> str:
    return (
        f"Article title: {title}\nURL: {url}\nOutlet: {outlet or 'unknown'}\n\n"
        f'Article text (may be truncated):\n"""\n{text}\n"""\n\n'
        f"Answer with one JSON object in exactly this shape:\n{SCHEMA_HINT}"
    )


def article_text(url: str, fetcher: Fetcher) -> tuple[str | None, str | None]:
    """(text, error): the page stripped to text, capped; None with a reason when it cannot be read."""
    r = fetcher(url)
    if r.error:
        return None, r.error
    if r.status != 200:
        return None, f"HTTP {r.status}"
    try:
        raw = r.body.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return None, str(e)
    # drop script/style blocks before stripping tags
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    text = strip_html(raw, limit=ARTICLE_CHARS)
    if len(text) < 300:
        return None, "page has no readable text (bot wall or empty)"
    return text, None


def offline_fetcher(directory: Path) -> Fetcher:
    """Serve saved pages from <dir>/<sha256(url)[:16]>.html (or .txt); missing → a 404 result."""
    import hashlib  # noqa: PLC0415

    def _get(url: str) -> FetchResult:
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        for ext in (".html", ".txt"):
            p = directory / f"{key}{ext}"
            if p.exists():
                return FetchResult(url, 200, {}, p.read_bytes())
        return FetchResult(url, 404, {}, b"", error=None)

    return _get


def offline_completer(directory: Path) -> Completer:
    """Replay verdicts from <dir>/verdicts.json ({url: verdict-object}); the URL is read from the prompt."""
    table = (
        json.loads((directory / "verdicts.json").read_text())
        if (directory / "verdicts.json").exists()
        else {}
    )

    def _complete(system: str, user: str) -> str:  # noqa: ARG001
        m = re.search(r"^URL: (\S+)$", user, re.M)
        url = m.group(1) if m else ""
        return json.dumps(
            table.get(url) or {"incident": False, "confidence": 0.0, "reason": "no saved verdict"}
        )

    return _complete


# ---- records ----------------------------------------------------------------------------------


def _list_q(items: list[str]) -> str:
    return "[" + ", ".join(_q(i) for i in items) + "]"


def published_block(
    new_id: str,
    v: Verdict,
    sources: list[dict[str, Any]],
    *,
    model: str,
    today: dt.date,
    related_agents: list[str] | None = None,
    cand_id: str | None = None,
) -> str:
    """A schema-valid ``status: published`` record in the file's hand format, every field from the
    verdict or null, reviewer naming the model."""
    assert v.date and v.ai_role and v.category and v.summary and v.attacker and v.defender
    title = v.title or sources[0]["title"]
    lines = [
        "",
        f"  - id: {new_id}",
        f"    status: published  # machine-reviewed {today.isoformat()}"
        + (f" from candidate {cand_id}" if cand_id else ""),
        f"    title: {_q(title)}",
        f"    date: {v.date}",
        f"    window: {_q(v.window) if v.window else 'null'}",
        f"    ai_role: {v.ai_role}",
        f"    category: {v.category}",
        "    summary: >-",
        *[f"      {line}" for line in _wrap(v.summary)],
        "    attacker:",
        f"      description: {_q(v.attacker)}",
        "    defender:",
        f"      description: {_q(v.defender)}",
        f"    scale: {_q(v.scale) if v.scale else 'null'}",
        f"    impact: {_q(v.impact) if v.impact else 'null'}",
        f"    tactics: [{', '.join(v.tactics)}]",
        "    timeline:",
    ]
    timeline = v.timeline or [{"date": v.date, "text": v.summary.split(". ")[0]}]
    lines += [
        f'      - {{ date: {_q(t["date"])}, text: {_q(t["text"])}, tier: null, source: "1" }}'
        for t in timeline
    ]
    lines += ["    lessons: []"]
    if v.models_named:
        lines += ["    models_named:"] + [
            f"      - {{ name: {_q(m['name'])}, role: {m['role']} }}" for m in v.models_named
        ]
    else:
        lines += ["    models_named: []"]
    lines += [
        f"    related_agents: {_list_q(related_agents or []) if related_agents else '[]'}",
        f"    vendor_response: {_q(v.vendor_response) if v.vendor_response else 'null'}",
        "    sources:",
    ]
    for s in sources:
        parts = [f"title: {_q(s['title'])}", f"url: {_q(s['url'])}"]
        if s.get("outlet"):
            parts.append(f"outlet: {_q(str(s['outlet']))}")
        if s.get("date"):
            parts.append(f"date: {_q(str(s['date']))}")
        lines.append("      - { " + ", ".join(parts) + " }")
    lines += [
        f"    reviewer: {_q(f'model: {model} (automated review)')}",
        f"    checked_on: {today.isoformat()}",
        "",
    ]
    return "\n".join(lines)


def _wrap(text: str, width: int = 96) -> list[str]:
    import textwrap  # noqa: PLC0415

    return textwrap.wrap(" ".join(text.split()), width=width) or [""]


def _agent_slugs(names: list[str], catalog: dict[str, str]) -> list[str]:
    """Agent names the model saw → catalog slugs, by exact (case-insensitive) name match only."""
    by_name = {n.lower(): slug for slug, n in catalog.items()}
    return sorted({by_name[n.lower()] for n in names if n.lower() in by_name})


def catalog_names(catalog_dir: Path) -> dict[str, str]:
    """slug → name from a built catalog's index.json (empty when there is none)."""
    p = catalog_dir / "index.json"
    if not p.exists():
        return {}
    doc = json.loads(p.read_text())
    return {r["slug"]: r["name"] for r in doc.get("records") or [] if r.get("slug") and r.get("name")}


def _block_span(text: str, inc_id: str) -> tuple[int, int] | None:
    """[start, end) of one record's block in incidents.yaml (from its '  - id:' line to the next)."""
    m = re.search(rf"^  - id: {re.escape(inc_id)}\n", text, re.M)
    if not m:
        return None
    nxt = re.search(r"^  - id: ", text[m.end() :], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    # include the blank line before the block, so removing it leaves the file tidy
    start = m.start()
    while start > 0 and text[start - 1] == "\n" and text[start - 2 : start] == "\n\n":
        start -= 1
    return start, end


# ---- the run ------------------------------------------------------------------------------------


@dataclass
class ReviewReport:
    model: str
    reviewed_on: str
    candidates_reviewed: int = 0
    placeholders_reviewed: int = 0
    published: list[dict[str, str]] = field(default_factory=list)
    dismissed: list[dict[str, str]] = field(default_factory=list)
    unreadable: list[dict[str, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def review(
    *,
    completer: Completer,
    fetcher: Fetcher | None = None,
    model: str = DEFAULT_MODEL,
    candidates_path: Path = CANDIDATES,
    incidents_path: Path = INCIDENTS,
    catalog_dir: Path | None = None,
    today: dt.date | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> ReviewReport:
    """Review every new candidate and every placeholder; publish or dismiss each; write both files."""
    today = today or dt.date.today()
    get = fetcher or (lambda url: fetch(url, timeout=20.0))
    report = ReviewReport(model=model, reviewed_on=today.isoformat())
    catalog = catalog_names(catalog_dir) if catalog_dir else {}
    doc = read_candidates(candidates_path)
    text = incidents_path.read_text()
    yaml = _yaml()
    inc_doc = yaml.safe_load(text) or {}
    by_cand = {c.get("promoted_to"): c for c in doc.get("candidates") or [] if c.get("promoted_to")}
    budget = limit if limit is not None else 10**9

    # 1. placeholders already in the registry: review from their own sources, in place
    for inc in list(inc_doc.get("incidents") or []):
        if inc.get("status") != "placeholder" or budget <= 0:
            continue
        budget -= 1
        report.placeholders_reviewed += 1
        sources = inc.get("sources") or []
        texts: list[str] = []
        errs: list[str] = []
        for s in sources[:3]:
            t, err = article_text(s["url"], get)
            (texts if t else errs).append(t or f"{s['url']}: {err}")
        if not texts:
            report.unreadable.append({"id": inc["id"], "why": "; ".join(errs)})
            continue
        joined = "\n\n---\n\n".join(texts)[:ARTICLE_CHARS]
        try:
            v = parse_verdict(
                completer(
                    SYSTEM, user_prompt(inc["title"], sources[0]["url"], sources[0].get("outlet"), joined)
                )
            )
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"{inc['id']}: {e}")
            continue
        ok, why = v.publishable()
        span = _block_span(text, inc["id"])
        if span is None:
            report.errors.append(f"{inc['id']}: block not found in {incidents_path.name}")
            continue
        cand = by_cand.get(inc["id"])
        if ok:
            block = published_block(
                inc["id"],
                v,
                sources,
                model=model,
                today=today,
                related_agents=_agent_slugs(v.agents_named, catalog),
                cand_id=cand["id"] if cand else None,
            )
            text = text[: span[0]] + block.rstrip("\n") + "\n" + text[span[1] :]
            report.published.append({"id": inc["id"], "title": v.title or inc["title"], "why": why})
        else:
            text = text[: span[0]] + text[span[1] :]
            if cand:
                cand["status"] = "dismissed"
                cand["note"] = f"model {model} on {today.isoformat()}: {why}"
                cand.pop("promoted_to", None)
            report.dismissed.append({"id": inc["id"], "title": inc["title"], "why": why})

    # 2. new candidates: publish straight from the candidate's link
    for cand in doc.get("candidates") or []:
        if cand.get("status") != "new" or budget <= 0:
            continue
        budget -= 1
        report.candidates_reviewed += 1
        body, err = article_text(cand["url"], get)
        if not body:
            report.unreadable.append({"id": cand["id"], "why": err or "unreadable"})
            continue
        try:
            v = parse_verdict(
                completer(SYSTEM, user_prompt(cand["title"], cand["url"], cand.get("outlet"), body))
            )
        except Exception as e:  # noqa: BLE001
            report.errors.append(f"{cand['id']}: {e}")
            continue
        ok, why = v.publishable()
        if ok:
            new_id = next_incident_id(incidents_path, today.year)
            # ids are allocated from the file as written so far
            new_id = _next_id_in(text, today.year, new_id)
            src = {
                "title": cand["title"],
                "url": cand["url"],
                "outlet": cand.get("outlet"),
                "date": cand.get("date"),
            }
            text = (
                text.rstrip("\n")
                + "\n"
                + published_block(
                    new_id,
                    v,
                    [src],
                    model=model,
                    today=today,
                    related_agents=_agent_slugs(v.agents_named, catalog),
                    cand_id=cand["id"],
                )
            )
            cand["status"] = "promoted"
            cand["promoted_to"] = new_id
            cand["note"] = f"model {model} on {today.isoformat()}: published as {new_id}"
            report.published.append({"id": new_id, "title": v.title or cand["title"], "why": why})
        else:
            cand["status"] = "dismissed"
            cand["note"] = f"model {model} on {today.isoformat()}: {why}"
            report.dismissed.append({"id": cand["id"], "title": cand["title"], "why": why})
        cand["last_seen"] = today.isoformat()

    # the file must still parse as YAML before anything is written
    parsed = yaml.safe_load(text) or {}
    ids = [i.get("id") for i in parsed.get("incidents") or []]
    if len(ids) != len(set(ids)):
        raise RuntimeError("review produced duplicate incident ids; nothing written")
    if not dry_run:
        incidents_path.write_text(text if text.endswith("\n") else text + "\n")
        doc["reviewed_on"] = today.isoformat()
        doc["reviewed_by"] = f"model: {model}"
        write_candidates(doc, candidates_path)
    return report


def _next_id_in(text: str, year: int, fallback: str) -> str:
    nums = [int(n) for n in re.findall(rf"^  - id: TR-{year}-(\d{{3}})$", text, re.M)]
    return f"TR-{year}-{max(nums) + 1:03d}" if nums else fallback

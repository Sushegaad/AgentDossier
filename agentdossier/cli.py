"""AgentDossier command-line interface.

Phase 0 commands: ``seed-check``, ``classify``, ``ard-resolve``, ``a2a-card``,
``config-check``. Later phases add ``build``, ``enterprise ...``, ``serve`` and
``mcp``. Everything here is standard-library only except ``seed-check``,
which needs openpyxl.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .util import CONFIG_DIR, ROOT, load_json


def cmd_seed_check(args: argparse.Namespace) -> int:
    from .connectors.seed_xlsx import import_seed

    result = import_seed(args.workbook, tolerance=args.tolerance)
    print(
        f"snapshot {result.snapshot_date}: {len(result.rows)} rows, {len(result.resources)} unique resources, "
        f"{len(result.source_catalog)} catalogued sources, max score error {result.max_score_error}"
    )
    for err in result.errors[:20]:
        print("  error:", err)
    if args.out:
        Path(args.out).write_text(json.dumps(list(result.resources.values()), indent=1, sort_keys=True))
        print(f"wrote {args.out}")
    return 0 if result.ok else 1


def cmd_classify(args: argparse.Namespace) -> int:
    from .classify import Classifier

    c = Classifier().classify(" ".join(args.text), category=args.category)
    print(
        json.dumps(
            {"domains": c.domains, "matched": c.matched, "taxonomy_version": c.taxonomy_version}, indent=1
        )
    )
    return 0


def cmd_ard_resolve(args: argparse.Namespace) -> int:
    from .standards.ard import resolve

    report = resolve(args.origin, consult_legacy=not args.no_legacy)
    print(json.dumps(report, indent=1, default=str))
    return 0 if report["status"] in ("verified", "not_found") else 1


def cmd_a2a_card(args: argparse.Namespace) -> int:
    from .standards.a2a import fetch_card

    report = fetch_card(args.origin)
    report.pop("card", None) if not args.raw else None
    print(json.dumps(report, indent=1, default=str))
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    from .build import BuildOptions, build

    opts = BuildOptions(
        out_dir=Path(args.out),
        cache_dir=Path(args.cache),
        sources=tuple(args.sources.split(",")),
        offline=args.offline,
        limit=args.limit,
        ard_domain_limit=args.ard_domains,
        mcp_handshake=args.mcp_handshake,
        write_review=not args.no_review,
        compliance=not args.no_compliance,
        news=not args.no_news,
        claim_domain_limit=args.claim_domains,
        news_limit=args.news_limit,
        budget_minutes=(args.budget_minutes or None),
        github_cap=args.github_cap,
        huggingface_cap=args.huggingface_cap,
        mcp_registry_cap=args.mcp_registry_cap,
    )
    result = build(opts)
    s = result.summary
    print(
        f"built {s['resources']} resources -> {args.out} (snapshot {s['snapshot_date']}, {s['score_version']})"
    )
    print("  by source:", s["by_source"])
    print("  protocols:", s["protocols"])
    for name, rep in result.reports.items():
        if rep.get("errors") or rep.get("skipped"):
            print(
                f"  {name}: {json.dumps({k: v for k, v in rep.items() if k in ('fetched', 'produced', 'skipped', 'errors', 'error_samples')})}"
            )
    return 0


def cmd_mcp_probe(args: argparse.Namespace) -> int:
    from .standards.mcp import fetch_card, handshake

    report = fetch_card(args.origin) if not args.handshake else handshake(args.origin)
    report.pop("card", None)
    print(json.dumps(report, indent=1, default=str))
    return 0


def cmd_harness(args: argparse.Namespace) -> int:
    """Run an AgentDojo prompt-injection suite against a model and record a trace (PR 3a)."""
    from .build import SITE
    from .harness import SOURCE, SUITES, record_run, run_suite
    from .harness.models import load_models
    from .traces.store import TraceStore
    from .util import now_iso

    if args.action == "list-suites":
        print(f"{SOURCE} suites:", ", ".join(SUITES))
        print("models:", ", ".join(load_models()) or "(none configured)")
        return 0

    if args.model == "mock":
        from .harness.mock import RefusingPipeline

        pipeline: object = RefusingPipeline()
        model_key = "mock-refusing"
    else:
        models = load_models()
        if args.model not in models:
            print(f"unknown model '{args.model}'; known: {', '.join(models) or 'none'}")
            return 2
        pipeline = _build_backend(models[args.model]["backend"])
        model_key = args.model

    store = TraceStore()
    suites = [args.suite] if args.suite else list(SUITES)
    wrote = []
    for suite in suites:
        result = run_suite(pipeline, suite, attack_name=args.attack)
        if result.error:
            print(f"{suite}: {result.error}")
            continue
        print(
            f"{suite}: {result.injections_succeeded}/{result.pairs} injections succeeded "
            f"(attack success rate {result.attack_success_rate})"
        )
        tid = record_run(store, result, model_key, site=SITE, date=now_iso()[:10])
        if tid:
            wrote.append(tid)
    print(f"appended {len(wrote)} bundle(s) to {store.index_path}: {', '.join(wrote) or 'none (unchanged)'}")
    return 0


def _build_backend(backend: dict[str, object]) -> object:
    """An AgentDojo pipeline for a real run. Keys come from the environment, never the repo."""
    from agentdojo.agent_pipeline import AgentPipeline

    provider = str(backend.get("provider"))
    model = str(backend.get("model"))
    config = {"llm": provider, "model": model} if provider != "local" else {"llm": "local", "model": model}
    return AgentPipeline.from_config(config)


def cmd_config_check(args: argparse.Namespace) -> int:
    """Validate config/ and schema/ files: JSON parses, profiles map to every domain, frameworks complete."""
    problems: list[str] = []
    scoring = load_json(CONFIG_DIR / "scoring.json")
    taxonomy = load_json(CONFIG_DIR / "taxonomy.json")
    for domain in taxonomy["domains"]:
        if domain not in scoring["domain_profiles"]:
            problems.append(f"scoring.json: no profile for domain '{domain}'")
    for name, profile in scoring["profiles"].items():
        missing = set(scoring["components"]) - set(profile)
        if missing:
            problems.append(f"scoring.json: profile '{name}' missing {sorted(missing)}")
    fw_dir = CONFIG_DIR / "frameworks"
    required = {
        "id",
        "name",
        "jurisdictions",
        "group",
        "sources",
        "variants",
        "expiry_rule",
        "credit",
        "wording",
        "priority",
    }
    for path in sorted(fw_dir.glob("*.json")):
        fw = load_json(path)
        missing = required - set(fw)
        if missing:
            problems.append(f"{path.name}: missing {sorted(missing)}")
        if fw.get("id") != path.stem:
            problems.append(f"{path.name}: id '{fw.get('id')}' does not match file name")
    for path in sorted((ROOT / "schema").glob("*.json")):
        try:
            load_json(path)
        except ValueError as exc:
            problems.append(f"{path.name}: {exc}")
    for p in problems:
        print("  problem:", p)
    print(
        f"config-check: {len(list(fw_dir.glob('*.json')))} frameworks, {len(taxonomy['domains'])} domains, "
        f"{len(scoring['profiles'])} profiles, {len(problems)} problems"
    )
    return 1 if problems else 0


def cmd_enterprise(args: argparse.Namespace) -> int:
    from .enterprise import preflight, scanner, selftest
    from .enterprise.config import ConfigError, load

    if args.action == "trace-selftest":
        import sqlite3

        from .enterprise.traces import best_tier, run_and_store
        from .harness.mock import RefusingPipeline
        from .storage.db import ensure_schema

        db = sqlite3.connect(":memory:")
        ensure_schema(db)
        tid = run_and_store(db, RefusingPipeline(), "slack", "selftest-agent", "mock-refusing")
        if not tid:
            print("trace-selftest: harness produced no result (is the 'harness' extra installed?)")
            return 1
        print(
            f"trace-selftest: stored {tid}; best tier for selftest-agent = {best_tier(db, 'selftest-agent')}"
        )
        return 0

    if args.action == "audit-verify":
        from .enterprise.audit import verify

        ok, entries, problem = verify(args.config)
        if ok:
            head = entries[0]
            print(
                f"ok: {len(entries)} entries, tenant {head.get('tenant')}, ticket {head.get('ticket')}, "
                f"authorized by {head.get('authorized_by')}, config {str(head.get('config_hash'))[:12]}…, "
                f"last hash {entries[-1]['hash'][:12]}…"
            )
            return 0
        print(f"FAILED after {len(entries)} good entries: {problem}", file=sys.stderr)
        return 1
    if args.action == "selftest":
        result = selftest.run(Path(args.out) if args.out else None)
        for step in result["steps"]:
            print(f"{'ok ' if step['ok'] else 'FAIL'} {step['step']}")
            if step["step"] == "preflight":
                for c in step["checks"]:
                    if c["status"] != "pass":
                        print(f"     {c['status']}: {c['message']}")
            else:
                print(f"     probed {step['origin']}: {step['probed'][0] if step['probed'] else 'nothing'}")
                print(f"     found: {', '.join(step['found']) or 'nothing'}")
                for e in step.get("errors", []):
                    print(f"     error: {e}")
        print("self-test", "passed" if result["ok"] else "FAILED", f"(catalog: {result.get('catalog')})")
        return 0 if result["ok"] else 1
    try:
        cfg = load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.action == "preflight":
        pf = preflight.run(cfg)
        for c in pf.checks:
            print(f"{c.status:4} {c.id}: {c.message}")
        print("preflight", "passed" if pf.ok else "FAILED")
        return 0 if pf.ok else 1
    pf = preflight.run(cfg)
    if not pf.ok and not args.force:
        for c in pf.checks:
            if c.status == "fail":
                print(f"fail {c.id}: {c.message}", file=sys.stderr)
        print(
            "preflight FAILED; fix the configuration or pass --force to override warnings only",
            file=sys.stderr,
        )
        return 1
    report = scanner.scan(cfg, dry_run=(args.action == "plan"), out_dir=Path(args.out) if args.out else None)
    if args.action == "plan":
        plan = report["plan"]
        print(
            f"tenant {cfg.tenant}: {len(plan['targets'])} origin(s), {len(plan['registries'])} registr{'y' if len(plan['registries']) == 1 else 'ies'}, {len(plan['refused'])} refused"
        )
        for t in plan["targets"][: args.show]:
            print(f"  probe   {t['origin']}  ({t['kind']}{' via ' + t['via'] if t.get('via') else ''})")
        if len(plan["targets"]) > args.show:
            print(f"  ... {len(plan['targets']) - args.show} more")
        for r in plan["refused"][: args.show]:
            print(f"  refuse  {r['origin']}: {r['reason']}")
        for w in plan["warnings"]:
            print(f"  warning {w}")
        return 0
    print(
        f"scanned {len(report['probed'])} origin(s)/registr(ies) for {cfg.tenant}: {report['resources']} resource(s) -> {report['catalog']}"
    )
    for e in report["errors"][:10]:
        print("  error:", e)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    if args.catalog:
        os.environ["AGENTDOSSIER_CATALOG_DIR"] = args.catalog
    if args.enterprise_config:
        os.environ["AGENTDOSSIER_ENTERPRISE_CONFIG"] = args.enterprise_config
    os.environ["AGENTDOSSIER_BIND_HOST"] = args.host  # auth_mode=none is refused off loopback
    if args.dev:
        os.environ["AGENTDOSSIER_DEV"] = "1"
        os.environ.setdefault("AGENTDOSSIER_AUTH_MODE", "none")
    try:
        import uvicorn

        from .server.app import create_app
    except ImportError:
        print("the server needs the 'server' extra: uv sync --extra server", file=sys.stderr)
        return 2
    try:
        app = create_app()
    except RuntimeError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    trusted = os.environ.get("AGENTDOSSIER_TRUSTED_PROXIES", "")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
        proxy_headers=bool(trusted),
        forwarded_allow_ips=trusted or None,
    )
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    try:
        from .server.mcp_server import main as mcp_main
    except ImportError:
        print("the MCP wrapper needs the 'mcp' extra: uv sync --extra mcp", file=sys.stderr)
        return 2
    mcp_main(args.catalog)
    return 0


def cmd_incidents(args: argparse.Namespace) -> int:
    """Weekly upkeep of the incident registry: scout feeds for candidates, promote or dismiss one."""
    from pathlib import Path  # noqa: PLC0415

    from .incidents import scout as sc  # noqa: PLC0415

    cand_path = Path(args.candidates)
    if args.action == "scout":
        config = sc.load_sources(Path(args.sources))
        if args.since_days is not None:
            config["since_days"] = args.since_days
        # --offline: a directory of <source_id>.xml files stands in for the network (tests, dry runs)
        fetcher = sc.offline_fetcher(Path(args.offline), config) if args.offline else None
        doc, report = sc.scout(
            config,
            sc.read_candidates(cand_path),
            fetcher=fetcher,
            known_urls=sc.incident_source_urls(Path(args.incidents)),
        )
        sc.write_candidates(doc, cand_path)
        new = sum(1 for c in doc["candidates"] if c.get("status") == "new")
        for sid, rep in report.sources.items():
            flag = f"  ERROR {rep['error']}" if rep.get("error") else ""
            print(f"  {sid:18} items {rep['items']:4}  matched {rep['matched']:3}{flag}")
        print(
            f"incidents scout: {report.items} items, {report.matched} matched, {report.added} new candidates, "
            f"{report.kept} seen again, {report.already_incident} already incidents, {report.cve_advisories} CVE advisories (→ cves), {report.pruned} pruned "
            f"→ {new} awaiting review in {cand_path}"
        )
        return 0
    if args.action == "draft":
        if not args.id:
            print("draft needs a candidate id (see the candidates file)", file=sys.stderr)
            return 2
        try:
            new_id = sc.promote(
                args.id, candidates_path=cand_path, incidents_path=Path(args.incidents), new_id=args.as_id
            )
        except KeyError:
            print(f"no candidate {args.id}", file=sys.stderr)
            return 2
        print(
            f"drafted {new_id} as a placeholder in {args.incidents} — complete it, then set status: published"
        )
        return 0
    if args.action == "dismiss":
        if not args.id:
            print("dismiss needs a candidate id", file=sys.stderr)
            return 2
        try:
            sc.dismiss(args.id, args.note, candidates_path=cand_path)
        except KeyError:
            print(f"no candidate {args.id}", file=sys.stderr)
            return 2
        print(f"dismissed {args.id}")
        return 0
    if args.action == "recheck":
        from .incidents import recheck as rc  # noqa: PLC0415

        incidents = rc.load_incidents(Path(args.incidents))
        result = rc.recheck(incidents)
        rc.write_report(result, Path(args.report))
        s = result["summary"]
        for iid in result["needs_attention"]:
            for line in result["incidents"][iid]:
                if line["status"] in ("gone", "moved", "error"):
                    extra = (
                        f" → {line['final_url']}" if line.get("final_url") else f" ({line.get('error', '')})"
                    )
                    print(f"  {iid} {line['status']:10} HTTP {line['http']:3} {line['url']}{extra}")
        print(
            f"incidents recheck: {result['incidents_checked']} incidents, {result['sources_checked']} sources — "
            f"ok {s['ok']}, moved {s['moved']}, gone {s['gone']}, unverified {s['unverified']}, error {s['error']} "
            f"→ {args.report}"
        )
        return 0
    return 2


def cmd_cves(args: argparse.Namespace) -> int:
    """The CVE registry: update from the official records, or record a person's decision."""
    import datetime as dt  # noqa: PLC0415
    import os  # noqa: PLC0415
    import random  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from .cves import build as cb  # noqa: PLC0415
    from .cves import nvd  # noqa: PLC0415

    if args.action == "plan":
        cfg = cb.load_config(Path(args.config))
        for u in nvd.backfill_queries(cfg):
            print(u)
        return 0
    if args.action == "update":
        cfg = cb.load_config(Path(args.config))
        fetcher = nvd.offline_fetcher(Path(args.offline)) if args.offline else None
        slugs: set[str] | None = None
        cat = Path(args.catalog) / "index.json"
        if cat.exists():
            slugs = {r["slug"] for r in json.loads(cat.read_text()).get("records", [])}
        doc, state, report = cb.update(
            config=cfg,
            fetcher=fetcher,
            api_key=os.environ.get("NVD_API_KEY"),
            backfill=args.backfill,
            catalog_slugs=slugs,
            existing=cb.read_index(Path(args.out) / "index.json"),
            state={} if args.backfill else cb.read_state(Path(args.out) / "state.json"),
        )
        problems = cb.validate(doc["records"])
        for pr in problems[:20]:
            print("  schema:", pr)
        if problems:
            print(f"cves update: {len(problems)} schema problem(s); nothing written", file=sys.stderr)
            return 1
        cb.write(doc, state, out_dir=Path(args.out))
        c = doc["counts"]
        for e in report["errors"][:10]:
            print("  error:", e)
        print(
            f"cves update ({report['mode']}): {report['queries']} queries, {report['fetched']} records fetched, "
            f"{len(report['new'])} new, {report['changed']} changed, {len(report['kev_new'])} newly in KEV, "
            f"{len(report['rejected'])} rejected → {c['total']} listed ({c['included']} included, {c['candidate']} candidates, "
            f"{c['excluded']} excluded, {c['kev']} in KEV, {c['unscored']} unscored) in {args.out}/index.json"
        )
        return 0
    if args.action == "show":
        if not args.id:
            print("show needs a CVE id", file=sys.stderr)
            return 2
        rec = next(
            (r for r in cb.read_index(Path(args.out) / "index.json")["records"] if r["id"] == args.id), None
        )
        if not rec:
            print(f"{args.id} is not in the registry", file=sys.stderr)
            return 2
        print(json.dumps(rec, indent=1))
        return 0
    if args.action in ("include", "exclude"):
        if not args.id:
            print(f"{args.action} needs a CVE id", file=sys.stderr)
            return 2
        cb.set_status(
            args.id,
            "included" if args.action == "include" else "excluded",
            args.note,
            reviewer=args.reviewer,
            today=dt.date.today(),
        )
        print(
            f"{args.id}: {args.action}d in {cb.OVERRIDES} — re-run `cves update --offline`/the refresh to apply"
        )
        return 0
    if args.action == "spot-check":
        recs = [
            r for r in cb.read_index(Path(args.out) / "index.json")["records"] if r["status"] != "excluded"
        ]
        random.seed(dt.date.today().isoformat())
        for r in random.sample(recs, min(args.sample, len(recs))):
            sev = f"{r['cvss']['severity']} {r['cvss']['score']}" if r.get("cvss") else "unscored"
            print(
                f"- [ ] {r['id']} · {sev} · {r['category']} · {', '.join(r['match']['tests'])} · {r['description'][:90]}"
            )
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentdossier", description="AgentDossier: an evidence dossier for every AI agent."
    )
    parser.add_argument("--version", action="version", version=f"agentdossier {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("seed-check", help="import the seed workbook and verify every score reproduces")
    p.add_argument("workbook")
    p.add_argument("--tolerance", type=float, default=0.1)
    p.add_argument("--out", help="write imported resources as JSON")
    p.set_defaults(func=cmd_seed_check)

    p = sub.add_parser("classify", help="classify free text into domains")
    p.add_argument("text", nargs="+")
    p.add_argument("--category")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("ard-resolve", help="resolve ARD entries for an origin (https://host)")
    p.add_argument("origin")
    p.add_argument("--no-legacy", action="store_true")
    p.set_defaults(func=cmd_ard_resolve)

    p = sub.add_parser("a2a-card", help="fetch and validate an A2A Agent Card for an origin")
    p.add_argument("origin")
    p.add_argument("--raw", action="store_true", help="include the full card")
    p.set_defaults(func=cmd_a2a_card)

    p = sub.add_parser("build", help="build the static catalog from the seed workbook and live sources")
    p.add_argument("--out", default=str(ROOT / "data" / "catalog"))
    p.add_argument("--cache", default=str(ROOT / "build" / "snapshots"))
    p.add_argument("--sources", default="seed,marketplaces,mcp_registry,huggingface,github,ard_web")
    p.add_argument("--offline", action="store_true", help="seed and curated sources only; no network")
    p.add_argument("--limit", type=int, help="cap discovered resources per source (development runs)")
    p.add_argument("--ard-domains", type=int, help="cap the number of publisher domains inspected")
    p.add_argument(
        "--mcp-handshake", action="store_true", help="enable the list-only MCP handshake (public build: off)"
    )
    p.add_argument(
        "--no-review", action="store_true", help="do not append near-duplicates to data/review/matches.yaml"
    )
    p.add_argument(
        "--no-compliance", action="store_true", help="skip compliance evidence (registries, curated, claims)"
    )
    p.add_argument("--no-news", action="store_true", help="skip news, community and NVD checks")
    p.add_argument("--claim-domains", type=int, help="cap the number of vendor domains crawled for claims")
    p.add_argument("--news-limit", type=int, help="cap the number of resources checked for news and CVEs")
    p.add_argument(
        "--budget-minutes",
        type=float,
        default=150.0,
        help="wall-clock budget; later stages skip remaining items when it runs out (0 = unlimited)",
    )
    p.add_argument(
        "--github-cap", type=int, default=300, help="most-starred GitHub repositories kept per run"
    )
    p.add_argument("--huggingface-cap", type=int, default=150)
    p.add_argument("--mcp-registry-cap", type=int, default=300)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser(
        "mcp-probe", help="fetch an MCP server card (or run the list-only handshake with --handshake)"
    )
    p.add_argument("origin", help="https://host for a card, or the MCP endpoint URL with --handshake")
    p.add_argument("--handshake", action="store_true")
    p.set_defaults(func=cmd_mcp_probe)

    p = sub.add_parser(
        "harness", help="run a published prompt-injection benchmark against a model and record a trace"
    )
    p.add_argument(
        "action",
        choices=["run", "list-suites"],
        help="run: benchmark and record; list-suites: show suites and models",
    )
    p.add_argument(
        "--model",
        default="mock",
        help="model key from data/traces/harness/models.yaml, or 'mock' (no model/network)",
    )
    p.add_argument("--suite", help="one AgentDojo suite (default: all)")
    p.add_argument("--attack", default="ignore_previous", help="AgentDojo attack name")
    p.set_defaults(func=cmd_harness)

    p = sub.add_parser("config-check", help="validate config/ and schema/ files")
    p.set_defaults(func=cmd_config_check)

    p = sub.add_parser("enterprise", help="authorized private-network scan (self-hosted edition)")
    p.add_argument(
        "action",
        choices=["preflight", "plan", "scan", "selftest", "trace-selftest", "audit-verify"],
        help="preflight: check the config; plan: dry run (nothing fetched); scan: probe and build; selftest: loopback end-to-end check; audit-verify: re-check a scan's audit.jsonl chain",
    )
    p.add_argument(
        "config",
        nargs="?",
        help="enterprise.json (audit-verify: the audit.jsonl to check; not needed for selftest)",
    )
    p.add_argument("--out", help="output directory (default: config output_dir)")
    p.add_argument("--force", action="store_true", help="scan even when preflight reports failures")
    p.add_argument("--show", type=int, default=20, help="plan: how many targets to print")
    p.set_defaults(func=cmd_enterprise)

    p = sub.add_parser(
        "serve", help="run the self-hosted server (ARD REST API, /qualify, scan control, web UI)"
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--catalog", help="catalog directory (default: AGENTDOSSIER_CATALOG_DIR or data/catalog)")
    p.add_argument("--enterprise-config", help="enterprise.json to enable scans and the schedule")
    p.add_argument(
        "--dev",
        action="store_true",
        help="local development: no authentication, loopback only (sets AGENTDOSSIER_DEV=1)",
    )
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="expose the registry to agents over MCP (stdio)")
    p.add_argument("--catalog", default=str(ROOT / "data" / "catalog"))
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser(
        "incidents", help="weekly upkeep of the incident registry (candidates from public feeds)"
    )
    p.add_argument(
        "action",
        choices=["scout", "draft", "dismiss", "recheck"],
        help="scout: read the feeds and update the candidates file; draft: scaffold a placeholder incident from a candidate; dismiss: drop a candidate for good; recheck: re-fetch every published incident's sources and record which still answer",
    )
    p.add_argument("id", nargs="?", help="candidate id (draft, dismiss)")
    p.add_argument("--sources", default=str(CONFIG_DIR / "trace_sources.json"))
    p.add_argument("--candidates", default=str(ROOT / "data" / "curated" / "incident_candidates.yaml"))
    p.add_argument("--incidents", default=str(ROOT / "data" / "curated" / "incidents.yaml"))
    p.add_argument("--since-days", type=int, default=None, help="scout: ignore items older than this")
    p.add_argument(
        "--offline", help="scout: read <source_id>.xml files from this directory instead of the network"
    )
    p.add_argument("--as-id", help="draft: the incident id to assign (default: next TR-<year>-NNN)")
    p.add_argument("--note", help="dismiss: why (kept in the candidates file)")
    p.add_argument(
        "--report",
        default=str(ROOT / "data" / "curated" / "incident_source_check.json"),
        help="recheck: where to write the report",
    )
    p.set_defaults(func=cmd_incidents)

    p = sub.add_parser("cves", help="the CVE registry: official CVEs related to AI agents (data/cves/)")
    p.add_argument(
        "action",
        choices=["update", "plan", "show", "include", "exclude", "spot-check"],
        help="update: read NVD/KEV and rebuild the index; plan: print the backfill queries; show: one record; include/exclude: record a decision in the overrides file; spot-check: a random sample to review",
    )
    p.add_argument("id", nargs="?", help="CVE id (show, include, exclude)")
    p.add_argument("--config", default=str(CONFIG_DIR / "cve_products.json"))
    p.add_argument("--out", default=str(ROOT / "data" / "cves"))
    p.add_argument(
        "--catalog",
        default=str(ROOT / "data" / "catalog"),
        help="catalog dir, to keep only agent slugs that exist",
    )
    p.add_argument(
        "--backfill",
        action="store_true",
        help="update: run the targeted backfill queries instead of the window since the last run",
    )
    p.add_argument(
        "--offline", help="update: replay saved responses from this directory (kev.json + NVD *.json)"
    )
    p.add_argument("--note", help="include/exclude: why")
    p.add_argument("--reviewer", help="include/exclude: your name; also sets checked_on")
    p.add_argument("--sample", type=int, default=50, help="spot-check: how many")
    p.set_defaults(func=cmd_cves)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

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
    try:
        import uvicorn

        from .server.app import create_app
    except ImportError:
        print("the server needs the 'server' extra: uv sync --extra server", file=sys.stderr)
        return 2
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    try:
        from .server.mcp_server import main as mcp_main
    except ImportError:
        print("the MCP wrapper needs the 'mcp' extra: uv sync --extra mcp", file=sys.stderr)
        return 2
    mcp_main(args.catalog)
    return 0


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
    p.add_argument("--github-cap", type=int, default=300, help="most-starred GitHub repositories kept per run")
    p.add_argument("--huggingface-cap", type=int, default=150)
    p.add_argument("--mcp-registry-cap", type=int, default=300)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser(
        "mcp-probe", help="fetch an MCP server card (or run the list-only handshake with --handshake)"
    )
    p.add_argument("origin", help="https://host for a card, or the MCP endpoint URL with --handshake")
    p.add_argument("--handshake", action="store_true")
    p.set_defaults(func=cmd_mcp_probe)

    p = sub.add_parser("config-check", help="validate config/ and schema/ files")
    p.set_defaults(func=cmd_config_check)

    p = sub.add_parser("enterprise", help="authorized private-network scan (self-hosted edition)")
    p.add_argument(
        "action",
        choices=["preflight", "plan", "scan", "selftest"],
        help="preflight: check the config; plan: dry run (nothing fetched); scan: probe and build; selftest: loopback end-to-end check",
    )
    p.add_argument("config", nargs="?", help="enterprise.json (not needed for selftest)")
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
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="expose the registry to agents over MCP (stdio)")
    p.add_argument("--catalog", default=str(ROOT / "data" / "catalog"))
    p.set_defaults(func=cmd_mcp)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

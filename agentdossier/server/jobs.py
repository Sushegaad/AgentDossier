"""Background work: the authorized scan, the evidence-expiry job, and the scheduler."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from .deps import Deps
from .notify import catalog_diff, evidence_expiring, expiry_text, scan_text

log = logging.getLogger("agentdossier.server")


def run_scan(d: Deps, trigger: str, user: str = "system") -> dict[str, Any]:
    cfg = d.state["config"]
    if cfg is None:
        raise HTTPException(400, "no enterprise configuration (set AGENTDOSSIER_ENTERPRISE_CONFIG)")
    if not d.state["scan_lock"].acquire(blocking=False):
        raise HTTPException(409, "a scan is already running")
    scan_id = d.store.start_scan(trigger)
    d.store.audit(user, "scan.start", f"trigger={trigger} tenant={cfg.tenant} ticket={cfg.ticket}")

    def work() -> None:
        from ..enterprise import preflight, scanner  # noqa: PLC0415

        try:
            pf = preflight.run(cfg)
            if not pf.ok:
                d.store.finish_scan(scan_id, "preflight_failed", pf.as_dict())
                failed = [c for c in pf.as_dict().get("checks", []) if c.get("status") == "fail"]
                d.notifier.send(
                    "scan.failed",
                    f"scan #{scan_id} stopped at preflight",
                    "Preflight failed:\n" + "\n".join(f"  {c.get('id')}: {c.get('message')}" for c in failed),
                    {"scanId": scan_id, "preflight": pf.as_dict()},
                )
                return
            before = list(d.catalog.records)
            report = scanner.scan(cfg)
            d.catalog.path = Path(report["catalog"])
            n = d.catalog.reload()
            d.store.finish_scan(scan_id, "done", report, resources=n)
            d.store.audit(user, "scan.done", f"resources={n}")
            diff = catalog_diff(before, d.catalog.records)
            summary = {
                k: v
                for k, v in report.items()
                if k in ("tenant", "ticket", "resources", "errors", "finished")
            }
            d.notifier.send(
                "scan.done",
                f"scan #{scan_id} done: {n} resources",
                scan_text(report, diff, d.settings.site),
                {"scanId": scan_id, "report": summary, "diff": diff},
            )
            if diff["added"] or diff["removed"] or diff["changed"]:
                d.notifier.send(
                    "catalog.changed",
                    f"catalog changed: +{len(diff['added'])} -{len(diff['removed'])} ~{len(diff['changed'])}",
                    scan_text(report, diff, d.settings.site),
                    {"scanId": scan_id, "diff": diff},
                )
        except Exception as exc:  # noqa: BLE001
            log.exception("scan failed")
            d.store.finish_scan(scan_id, "error", {"error": f"{type(exc).__name__}: {exc}"})
            d.notifier.send(
                "scan.failed",
                f"scan #{scan_id} failed",
                f"{type(exc).__name__}: {exc}",
                {"scanId": scan_id},
            )
        finally:
            d.state["scan_lock"].release()

    threading.Thread(target=work, daemon=True, name=f"scan-{scan_id}").start()
    return {"scanId": scan_id, "status": "running"}


def run_expiry(d: Deps, trigger: str = "schedule") -> dict[str, Any]:
    """Daily job: warn about compliance evidence that expires or is due for a recheck."""
    full = [d.catalog.resource(r["id"]) or r for r in d.catalog.records]
    items = evidence_expiring(full, days=d.settings.notify.expiry_warning_days)
    d.store.audit("system", "evidence.expiry", f"trigger={trigger} items={len(items)}")
    deliveries: list[dict[str, Any]] = []
    if items:
        deliveries = d.notifier.send(
            "evidence.expiring",
            f"{len(items)} compliance record(s) expiring or due for recheck",
            expiry_text(items, d.settings.site),
            {"items": items},
        )
    return {"items": items, "deliveries": deliveries}


def start_scheduler(d: Deps) -> None:
    """Register the scan schedule and the daily expiry job (APScheduler, in-process)."""
    cfg = d.state["config"]
    jobs: list[tuple[str, str, Any]] = []
    if cfg is not None and cfg.schedule:
        jobs.append(("scan", cfg.schedule, lambda: run_scan(d, "schedule")))
    if d.settings.expiry_cron and d.notifier.channels:
        jobs.append(("evidence_expiry", d.settings.expiry_cron, lambda: run_expiry(d, "schedule")))
    if jobs and d.settings.start_scheduler:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler  # noqa: PLC0415
            from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

            sched = BackgroundScheduler(timezone="UTC")
            for job_id, cron, fn in jobs:
                sched.add_job(fn, CronTrigger.from_crontab(cron), id=job_id, replace_existing=True)
            sched.start()
            d.state["scheduler"] = sched
        except ImportError:
            log.warning("apscheduler not installed; schedule ignored")
    d.state["jobs"] = [{"id": j, "cron": c} for j, c, _ in jobs]

"""Composition root: CLI, diagnostics, discovery and bounded worker runs."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from .adapters import OpenAIAnalyzer, PublicInspector, SMTPSender
from .demos import save_atomic
from .domain import BusinessError
from .models import Job, Lead, Message, Order
from .outreach import Outreach
from .portfolio import Portfolio
from .settings import ROOT, Settings
from .store import Store
from .workflow import Worker


def discovery(settings, store, query: str, limit: int, seeds: str = "") -> dict:
    if seeds:
        rows = json.loads(Path(seeds).read_text(encoding="utf-8"))
        if not isinstance(rows, list) or len(rows) > 1000:
            raise BusinessError("Seed file must be a JSON list of at most 1000 records")
        source = "seed_file"
    else:
        if not settings.google_key:
            return {"status": "blocked", "code": "GOOGLE_PLACES_API_KEY_missing", "discovered": 0}
        from google_places import search_places

        rows = search_places(settings.google_key, query, page_size=limit)
        source = "google_places"
    created, errors, skipped_closed = 0, 0, 0
    for place in rows[:limit]:
        if place.get("business_status") and place["business_status"] != "OPERATIONAL":
            skipped_closed += 1
            continue
        try:
            _, new = store.add_lead(place)
            created += int(new)
        except BusinessError:
            errors += 1
    return {
        "status": "completed",
        "source": source,
        "discovered": min(len(rows), limit),
        "created": created,
        "invalid": errors,
        "closed": skipped_closed,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SynAirgy Lead Engine v2")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    discover = sub.add_parser("discover")
    discover.add_argument("--query", default=os.getenv("LEAD_QUERY") or "")
    discover.add_argument("--limit", type=int, default=int(os.getenv("LEAD_LIMIT") or "20"))
    discover.add_argument("--seeds", default="")
    worker = sub.add_parser("worker")
    worker.add_argument("--max-jobs", type=int, default=100)
    worker.add_argument("--loop", action="store_true")
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    sub.add_parser("send")
    sub.add_parser("status")
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    sub.add_parser("reconcile-sends")
    sub.add_parser("market-research")
    sub.add_parser("portfolio-report")
    sub.add_parser("portfolio-plan")
    portfolio_tick = sub.add_parser("portfolio-tick")
    portfolio_tick.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    if args.command == "doctor":
        print(json.dumps(settings.readiness()))
        return 0
    store = Store(settings.database_url)
    runner = Worker(store, settings, inspector=PublicInspector(), analyzer=OpenAIAnalyzer(settings.openai_key, settings.model))
    outreach = Outreach(store, settings, SMTPSender(settings))
    portfolio = Portfolio(store, settings)
    report = {"status": "starting"}
    try:
        if args.command == "discover":
            if not args.query and not args.seeds:
                raise BusinessError("Use portfolio-tick for automatic sector selection, or supply an explicit --query/--seeds")
            limit = max(1, min(args.limit, 1000 if args.seeds else 20))
            report = discovery(settings, store, args.query, limit, args.seeds)
        elif args.command == "market-research":
            report = portfolio.research()
        elif args.command == "portfolio-report":
            report = {"status": "completed", **portfolio.report()}
        elif args.command == "portfolio-plan":
            report = {"status": "completed", **portfolio.plan().model_dump()}
        elif args.command == "portfolio-tick":
            report = portfolio.tick(args.limit) if settings.portfolio_enabled else {"status": "disabled"}
        elif args.command == "worker":
            while True:
                report = {"status": "completed", "jobs": runner.run(args.max_jobs)}
                if report["jobs"].get("blocked"):
                    report["status"] = "blocked"
                    break
                if report["jobs"].get("failed"):
                    report["status"] = "failed"
                    break
                if not args.loop:
                    break
                time.sleep(5)
        elif args.command == "send":
            report = {"status": outreach.send_one()}
        elif args.command == "reconcile-sends":
            outreach.mark_stale_sends_for_review()
            report = {"status": "needs_review", "automatic_resend": False}
        elif args.command == "retry":
            store.retry_job(args.job_id)
            report = {"status": "queued"}
        elif args.command == "status":
            report = {
                "status": "ok",
                "counts": {
                    name: len(store.all(model, 10000))
                    for name, model in [("leads", Lead), ("jobs", Job), ("messages", Message), ("orders", Order)]
                },
                "readiness": settings.readiness(),
            }
        elif args.command == "serve":
            import uvicorn

            from .api import create_app

            if len(settings.admin_token) < 32:
                raise BusinessError("ADMIN_TOKEN must contain at least 32 characters")
            uvicorn.run(create_app(settings, store), host=args.host, port=args.port, access_log=False)
            return 0
    except Exception as exc:
        report = {"status": "failed", "code": str(exc) if isinstance(exc, BusinessError) else type(exc).__name__}
    out = Path(os.getenv("OUTPUT_PATH", ROOT / "out" / "summary.json"))
    save_atomic(out, json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
    return 2 if report.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    sys.exit(main())

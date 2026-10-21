"""Resumable stage machine. Job result, next job, and CRM state commit together."""

from __future__ import annotations

import logging
import zipfile

from sqlmodel import select

from .demos import render, save_atomic
from .domain import BusinessError, Stage, email_address, normalize_analysis
from .models import Activity, Lead, Message, Order
from .ports import ProviderFailure

logger = logging.getLogger("synairgy.worker")


class Worker:
    def __init__(self, store, settings, *, inspector, analyzer):
        self.store, self.settings = store, settings
        self.inspector, self.analyzer = inspector, analyzer

    def tick(self) -> str:
        job = self.store.claim()
        if not job:
            return "idle"
        lead = self.store.get(Lead, job.lead_id)
        try:
            if lead is None or (lead.suppressed and job.kind != "fulfill"):
                self.store.finish(job, lambda s, item: None)
                return "cancelled"
            handler = getattr(self, f"stage_{job.kind}", None)
            if handler is None:
                raise BusinessError("Unknown stage")
            handler(job, lead)
            logger.info("job_done id=%s kind=%s", job.id, job.kind)
            return "done"
        except ProviderFailure as exc:
            self.store.fail(job, exc.code, permanent=exc.permanent, blocked=exc.blocked)
            return "blocked" if exc.blocked else "failed"
        except BusinessError as exc:
            self.store.fail(job, str(exc), permanent=True)
            return "failed"
        except Exception as exc:
            self.store.fail(job, f"stage_error:{type(exc).__name__}")
            return "failed"

    def run(self, max_jobs: int = 100) -> dict:
        counts: dict[str, int] = {}
        for _ in range(max(1, min(max_jobs, 1000))):
            outcome = self.tick()
            if outcome == "idle":
                break
            counts[outcome] = counts.get(outcome, 0) + 1
            if outcome == "blocked":
                break
        return counts

    def stage_inspect(self, job, lead):
        site = self.inspector.inspect(lead.place)

        def commit(s, current):
            current.site = site
            # A scraped mailto doesn't verify ownership or recipient identity.
            if not current.email and site.get("email"):
                try:
                    current.email = email_address(site["email"])
                except BusinessError:
                    pass
            s.add(current)
            self.store.enqueue(s, current.id, "analyze")

        self.store.finish(job, commit)

    def stage_analyze(self, job, lead):
        with self.store.transaction() as s:
            self.store.reserve(s, "ai_calls", self.settings.max_ai_calls)
        analysis = normalize_analysis(self.analyzer.analyze(lead.place, lead.site))
        from ai_analyzer import normalize_score
        from catalog import OFFER_CATALOG

        analysis["score"] = normalize_score(analysis, lead.place, lead.site)
        analysis["price_eur"] = OFFER_CATALOG[analysis["recommended_offer"]]

        def commit(s, current):
            current.analysis = analysis
            target = (
                Stage.QUALIFIED
                if analysis["score"] >= self.settings.lead_threshold
                else (Stage.REVIEW if analysis["score"] >= self.settings.review_threshold else Stage.SKIP)
            )
            self.store.move(s, current, target)
            s.add(current)
            if target == Stage.QUALIFIED and analysis["recommended_offer"] == "Landing":
                self.store.enqueue(s, current.id, "demo")
            elif target == Stage.QUALIFIED:
                s.add(Activity(lead_id=current.id, kind="manual_offer_required", detail={"offer": analysis["recommended_offer"]}))

        self.store.finish(job, commit)

    def stage_demo(self, job, lead):
        save_atomic(self.settings.data_dir / "demos" / f"{lead.id}.html", render(lead))

        def commit(s, current):
            self.store.move(s, current, Stage.DEMO_READY)
            self.store.enqueue(s, current.id, "draft")

        self.store.finish(job, commit)

    def stage_draft(self, job, lead):
        def commit(s, current):
            key = f"{current.id}:outreach:0"
            if s.exec(select(Message).where(Message.dedupe_key == key)).first():
                return
            if not current.email:
                s.add(Activity(lead_id=current.id, kind="contact_missing"))
                return
            link = f"{self.settings.public_url}/preview/{current.preview_token}"
            body = f"Guten Tag,\n\nfür {current.company} haben wir ein privates Website-Konzept vorbereitet.\n{link}\n\nDas Konzept ist unverbindlich. Wenn es für Sie interessant ist, antworten Sie einfach auf diese Nachricht.\n\nSynAirgy — KI-gestützter digitaler Service\n{self.settings.sender_address}\n"
            msg = Message(
                lead_id=current.id,
                dedupe_key=key,
                recipient=current.email,
                subject=f"Website-Konzept für {current.company}"[:180],
                body=body,
                approved=self.settings.auto_approve and current.contact_verified,
            )
            s.add(msg)
            s.add(Activity(lead_id=current.id, kind="draft_created", detail={"message_id": msg.id}))

        self.store.finish(job, commit)

    def stage_fulfill(self, job, lead):
        order = self.store.get(Order, job.payload.get("order_id"))
        if not order or order.status not in {"paid", "delivery_ready"}:
            raise BusinessError("Confirmed payment required for fulfillment")
        if order.offer != "Landing":
            raise BusinessError("Offer requires manual fulfillment")
        folder = self.settings.data_dir / "deliveries" / order.id
        folder.mkdir(parents=True, exist_ok=True)
        archive = folder / "website.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("index.html", render(lead, concept=False))
            z.writestr(
                "DELIVERY.md",
                "Website package for customer review. Domain/DNS, approved content, legal pages and public deployment remain pending. This package is not evidence of a published website.\n",
            )

        def commit(s, current):
            stored = s.get(Order, order.id)
            if stored.status != "paid":
                return
            stored.status, stored.delivery_path = "delivery_ready", str(archive)
            s.add(stored)
            self.store.move(s, current, Stage.DELIVERY_READY)
            s.add(Activity(lead_id=current.id, kind="package_created", detail={"order_id": order.id, "public_deployment": False}))

        self.store.finish(job, commit)

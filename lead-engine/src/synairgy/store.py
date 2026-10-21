"""Single-host durable store and transactional outbox, isolated from providers.

Short BEGIN IMMEDIATE transactions serialize SQLite writes. No network calls run
inside them. External effects are at-least-once unless the provider supports an
idempotency key; ambiguous SMTP sends require reconciliation, never auto-retry.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from .domain import BusinessError, Stage, backoff, email_address, identity, transition
from .models import Activity, DailyCounter, Job, Lead, Message, SchemaVersion, Suppression, uid


class Store:
    def __init__(self, database_url: str):
        if not database_url.startswith("sqlite:///"):
            raise ValueError("This store supports single-host SQLite only")
        if database_url != "sqlite:///:memory:":
            Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 30})
        SQLModel.metadata.create_all(self.engine)
        with self.transaction() as s:
            versions = s.exec(select(SchemaVersion)).all()
            if versions and max(v.version for v in versions) != 1:
                raise RuntimeError("Unsupported database schema; migration required")
            if not versions:
                s.add(SchemaVersion(version=1))

    @contextmanager
    def transaction(self):
        with Session(self.engine, expire_on_commit=False) as session:
            session.exec(text("BEGIN IMMEDIATE"))
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def get(self, model, key):
        with Session(self.engine) as s:
            return s.get(model, key)

    def all(self, model, limit: int = 100):
        with Session(self.engine) as s:
            return list(s.exec(select(model).limit(limit)).all())

    @staticmethod
    def enqueue(s: Session, lead_id: str, kind: str, *, key: str | None = None, payload: dict | None = None, due_at: float | None = None):
        key = key or f"{lead_id}:{kind}:v1"
        existing = s.exec(select(Job).where(Job.dedupe_key == key)).first()
        if existing:
            return existing
        job = Job(lead_id=lead_id, kind=kind, dedupe_key=key, payload=payload or {}, due_at=due_at if due_at is not None else time.time())
        s.add(job)
        return job

    @staticmethod
    def move(s: Session, lead: Lead, target: str):
        transition(lead.stage, target)
        if lead.stage != target:
            s.add(Activity(lead_id=lead.id, kind="stage_changed", detail={"from": lead.stage, "to": str(target)}))
            lead.stage = target
            s.add(lead)

    def add_lead(self, place: dict, *, verified_contact: bool = False) -> tuple[Lead, bool]:
        key = identity(place)
        email = email_address(place["email"]) if place.get("email") else ""
        with self.transaction() as s:
            found = s.exec(select(Lead).where(Lead.identity_key == key)).first()
            if found:
                return found, False
            suppressed = bool(email and s.get(Suppression, email))
            lead = Lead(
                identity_key=key,
                company=str(place["name"])[:300],
                place=place,
                email=email,
                contact_verified=bool(verified_contact and email),
                suppressed=suppressed,
                stage=Stage.SUPPRESSED if suppressed else Stage.NEW,
            )
            s.add(lead)
            s.flush()
            if not suppressed:
                self.enqueue(s, lead.id, "inspect")
            s.add(Activity(lead_id=lead.id, kind="lead_created"))
            return lead, True

    def claim(self, now: float | None = None) -> Job | None:
        now = time.time() if now is None else now
        with self.transaction() as s:
            job = s.exec(
                select(Job)
                .where(((Job.status == "pending") & (Job.due_at <= now)) | ((Job.status == "running") & (Job.lease_until < now)))
                .order_by(Job.due_at)
                .limit(1)
            ).first()
            if not job:
                return None
            job.status = "running"
            job.attempts += 1
            job.lease_token = uid()
            job.lease_until = now + 300
            s.add(job)
            return job

    def finish(self, job: Job, apply_result):
        with self.transaction() as s:
            current = s.get(Job, job.id)
            if not current or current.status != "running" or current.lease_token != job.lease_token:
                raise BusinessError("Stale job lease")
            lead = s.get(Lead, job.lead_id)
            if lead is None:
                raise BusinessError("Missing lead")
            if job.kind != "fulfill" and (lead.suppressed or lead.stage in {Stage.LOST, Stage.SKIP}):
                current.status = "cancelled"
            else:
                apply_result(s, lead)
                current.status = "done"
            current.lease_until = 0
            s.add(current)

    def fail(self, job: Job, code: str, *, permanent: bool = False, blocked: bool = False):
        with self.transaction() as s:
            current = s.get(Job, job.id)
            if not current or current.lease_token != job.lease_token:
                return
            current.status = "blocked" if blocked else ("dead" if permanent or current.attempts >= 4 else "pending")
            current.error = code[:100]
            current.due_at = time.time() + backoff(current.attempts)
            current.lease_until = 0
            s.add(current)
            s.add(
                Activity(
                    lead_id=job.lead_id,
                    kind="job_failed",
                    detail={"job": job.id, "stage": job.kind, "code": code, "status": current.status},
                )
            )

    def retry_job(self, job_id: str):
        with self.transaction() as s:
            job = s.get(Job, job_id)
            if not job or job.status not in {"blocked", "dead"}:
                raise BusinessError("Only blocked/dead jobs can be retried")
            job.status, job.attempts, job.due_at, job.error = "pending", 0, time.time(), ""
            s.add(job)

    @staticmethod
    def reserve(s: Session, category: str, limit: int):
        day = datetime.now(timezone.utc).date().isoformat()
        key = f"{category}:{day}"
        counter = s.get(DailyCounter, key) or DailyCounter(id=key)
        if counter.count >= limit:
            raise BusinessError(f"Daily {category} budget exhausted")
        counter.count += 1
        s.add(counter)

    def suppress(self, email: str, reason: str = "opt_out"):
        email = email_address(email)
        with self.transaction() as s:
            if not s.get(Suppression, email):
                s.add(Suppression(email=email, reason=reason[:100]))
            for lead in s.exec(select(Lead).where(Lead.email == email)).all():
                lead.suppressed = True
                if lead.stage not in {Stage.PAID, Stage.DELIVERY_READY, Stage.FULFILLED}:
                    self.move(s, lead, Stage.SUPPRESSED)
                s.add(lead)
                s.add(Activity(lead_id=lead.id, kind="contact_suppressed"))
                for msg in s.exec(select(Message).where(Message.lead_id == lead.id, Message.status.in_(["draft", "approved"]))):
                    msg.status = "cancelled"
                    s.add(msg)

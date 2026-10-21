"""Transactional email outbox; a reply or objection cancels follow-ups."""

from __future__ import annotations

import time

from sqlmodel import select

from .domain import BusinessError, Stage, contactable, email_address
from .models import Activity, Lead, Message, Suppression
from .ports import ProviderFailure


class Outreach:
    def __init__(self, store, settings, sender):
        self.store, self.settings, self.sender = store, settings, sender

    def verify_contact(self, lead_id: str, email: str):
        email = email_address(email)
        with self.store.transaction() as s:
            lead = s.get(Lead, lead_id)
            if not lead or email != lead.email or s.get(Suppression, email):
                raise BusinessError("Contact doesn't match lead or is suppressed")
            lead.contact_verified = True
            s.add(lead)
            s.add(Activity(lead_id=lead.id, kind="contact_verified"))

    def approve(self, message_id: str):
        with self.store.transaction() as s:
            msg = s.get(Message, message_id)
            lead = s.get(Lead, msg.lead_id) if msg else None
            if not msg or msg.status != "draft" or not lead or not lead.contact_verified:
                raise BusinessError("Verified recipient and draft required")
            if not contactable(lead.stage, lead.suppressed, lead.replied_at is not None):
                raise BusinessError("Contact paused")
            msg.approved = True
            s.add(msg)

    def record_reply(self, lead_id: str, sender: str, *, interested: bool = False):
        sender = email_address(sender)
        with self.store.transaction() as s:
            lead = s.get(Lead, lead_id)
            if not lead or sender != lead.email:
                raise BusinessError("Reply sender does not match verified recipient")
            lead.replied_at = time.time()
            if interested and not lead.suppressed and lead.stage in {Stage.DEMO_READY, Stage.CONTACTED}:
                self.store.move(s, lead, Stage.INTERESTED)
            s.add(lead)
            for msg in s.exec(select(Message).where(Message.lead_id == lead.id, Message.status == "draft")):
                msg.status = "cancelled"
                s.add(msg)
            s.add(Activity(lead_id=lead.id, kind="reply_received", detail={"interested": interested}))

    def send_one(self, now: float | None = None) -> str:
        if not self.settings.outreach_enabled:
            return "disabled"
        if not self.settings.readiness()["outreach"]["ready"]:
            raise ProviderFailure("outreach_configuration_missing", blocked=True)
        now = time.time() if now is None else now
        with self.store.transaction() as s:
            msg = s.exec(
                select(Message)
                .where(Message.status == "draft", Message.approved.is_(True), Message.due_at <= now)
                .order_by(Message.due_at)
                .limit(1)
            ).first()
            if not msg:
                return "idle"
            lead = s.get(Lead, msg.lead_id)
            if (
                not lead
                or not lead.contact_verified
                or msg.recipient != lead.email
                or s.get(Suppression, msg.recipient)
                or not contactable(lead.stage, lead.suppressed, lead.replied_at is not None)
            ):
                msg.status = "cancelled"
                s.add(msg)
                return "cancelled"
            self.store.reserve(s, "outreach", self.settings.daily_limit)
            msg.status = "sending"
            s.add(msg)
        unsubscribe = f"{self.settings.public_url}/unsubscribe/{msg.unsubscribe_token}"
        body = msg.body + f"\nKeine weiteren Nachrichten: {unsubscribe}\n"
        try:
            self.sender.send(recipient=msg.recipient, subject=msg.subject, body=body, message_id=msg.id, unsubscribe_url=unsubscribe)
        except Exception:
            with self.store.transaction() as s:
                current = s.get(Message, msg.id)
                current.status, current.error = "needs_review", "delivery_outcome_unknown"
                s.add(current)
            return "needs_review"
        with self.store.transaction() as s:
            current, lead = s.get(Message, msg.id), s.get(Lead, msg.lead_id)
            current.status, current.sent_at = "sent", now
            s.add(current)
            s.add(Activity(lead_id=lead.id, kind="email_sent", detail={"message_id": msg.id, "sequence": msg.sequence}))
            if lead.stage == Stage.DEMO_READY and not lead.suppressed:
                self.store.move(s, lead, Stage.CONTACTED)
            if msg.sequence < 2 and contactable(lead.stage, lead.suppressed, lead.replied_at is not None):
                sequence = msg.sequence + 1
                key = f"{lead.id}:outreach:{sequence}"
                if not s.exec(select(Message).where(Message.dedupe_key == key)).first():
                    s.add(
                        Message(
                            lead_id=lead.id,
                            dedupe_key=key,
                            recipient=msg.recipient,
                            subject=msg.subject,
                            body="Kurze Nachfrage zu unserem unverbindlichen Konzept:\n\n" + msg.body,
                            approved=True,
                            sequence=sequence,
                            due_at=now + (7 if sequence == 1 else 23) * 86400,
                        )
                    )
        return "sent"

    def mark_stale_sends_for_review(self):
        # Explicit recovery command. Never blindly resend a pre-crash 'sending'.
        with self.store.transaction() as s:
            for msg in s.exec(select(Message).where(Message.status == "sending")):
                msg.status, msg.error = "needs_review", "process_interrupted"
                s.add(msg)

"""One-time Checkout; signed webhook events are the sole payment authority.

Catalog prices are server-owned; model output cannot set a charge amount.
Recurring billing is deliberately not claimed by this adapter.
"""

from __future__ import annotations

import hashlib

from sqlmodel import select

from catalog import OFFER_CATALOG

from .domain import BusinessError, Stage
from .models import Activity, Attribution, Lead, MoneyEntry, Order, WebhookReceipt
from .ports import ProviderFailure


class Billing:
    def __init__(self, store, settings, client=None):
        self.store, self.settings = store, settings
        self.client = client

    def _client(self):
        if self.client is None:
            import stripe

            key = self.settings.stripe_key
            if not key or ("_live_" in key) != self.settings.stripe_live:
                raise ProviderFailure("stripe_key_mode_mismatch_or_missing", blocked=True)
            self.client = stripe.StripeClient(key, stripe_version="2026-08-26.dahlia", max_network_retries=2)
        return self.client

    def checkout(self, lead_id: str, request_key: str) -> Order:
        if not request_key or len(request_key) > 120:
            raise BusinessError("Valid idempotency request key required")
        with self.store.transaction() as s:
            order = s.exec(select(Order).where(Order.request_key == request_key)).first()
            if order and order.lead_id != lead_id:
                raise BusinessError("Idempotency key already belongs to another lead")
            if order and order.session_id:
                return order
            lead = s.get(Lead, lead_id)
            if not lead or lead.suppressed or lead.stage not in {Stage.INTERESTED, Stage.OFFERED}:
                raise BusinessError("Interested customer required before checkout")
            if lead.analysis.get("recommended_offer") != "Landing":
                raise BusinessError("This offer requires manual scope and fulfillment")
            if not order:
                active = s.exec(
                    select(Order).where(Order.lead_id == lead_id, Order.status.in_(["pending", "paid", "delivery_ready"]))
                ).first()
                if active:
                    raise BusinessError("An order already exists for this lead")
                order = Order(lead_id=lead_id, request_key=request_key, amount_cents=OFFER_CATALOG["Landing"] * 100)
                s.add(order)
                self.store.move(s, lead, Stage.OFFERED)
        suffix = "".join(chr(97 + x % 26) for x in hashlib.sha256(order.id.encode()).digest()[:8])
        params = {
            "mode": "payment",
            "client_reference_id": order.id,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": order.currency,
                        "unit_amount": order.amount_cents,
                        "product_data": {"name": "SynAirgy Landing — individuelles Website-Paket"},
                    },
                }
            ],
            "integration_identifier": f"synairgy-lead-engine-{suffix}",
            "success_url": self.settings.public_url + "/payment/received",
            "cancel_url": self.settings.public_url + "/payment/cancelled",
        }
        # No automatic_tax without confirmed registration. No payment_method_types.
        result = self._client().v1.checkout.sessions.create(params, options={"idempotency_key": f"synairgy:{order.id}"})
        session_id, checkout_url = str(result.id), str(result.url)
        if not session_id.startswith("cs_") or not checkout_url.startswith("https://checkout.stripe.com/"):
            raise ProviderFailure("invalid_checkout_response", permanent=True)
        with self.store.transaction() as s:
            current = s.get(Order, order.id)
            if current.session_id and current.session_id != session_id:
                raise BusinessError("Conflicting checkout session")
            current.session_id, current.checkout_url = session_id, checkout_url
            s.add(current)
            s.add(Activity(lead_id=lead_id, kind="checkout_created", detail={"order_id": order.id}))
            return current

    def verify_event(self, payload: bytes, signature: str):
        if not self.settings.stripe_webhook_secret:
            raise ProviderFailure("stripe_webhook_secret_missing", blocked=True)
        import stripe

        try:
            event = stripe.Webhook.construct_event(payload, signature, self.settings.stripe_webhook_secret)
        except (ValueError, stripe.SignatureVerificationError):
            raise BusinessError("Invalid webhook signature") from None
        return event.to_dict()

    def receive(self, event: dict) -> str:
        if bool(event.get("livemode")) != self.settings.stripe_live:
            raise BusinessError("Webhook mode mismatch")
        kind = event.get("type")
        if kind not in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
            "checkout.session.async_payment_failed",
            "checkout.session.expired",
        }:
            return "ignored"
        event_id = event.get("id", "")
        obj = event.get("data", {}).get("object", {})
        if not event_id or not obj.get("id"):
            raise BusinessError("Malformed webhook")
        with self.store.transaction() as s:
            if s.get(WebhookReceipt, event_id):
                return "duplicate"
            order = s.exec(select(Order).where(Order.session_id == obj["id"])).first()
            if not order and obj.get("client_reference_id"):
                # Explicit race-recovery fallback if the event beats session-save.
                order = s.get(Order, obj["client_reference_id"])
                if order and order.session_id not in {None, obj["id"]}:
                    raise BusinessError("Conflicting session reference")
            if not order:
                return "unrelated"
            if obj.get("currency") != order.currency or obj.get("amount_total") != order.amount_cents:
                raise BusinessError("Payment amount/currency mismatch")
            order.session_id = obj["id"]
            result = "pending"
            if kind in {"checkout.session.async_payment_failed", "checkout.session.expired"}:
                if order.status == "pending":
                    order.status = "failed"
                result = order.status
            elif obj.get("payment_status") == "paid":
                if order.status not in {"paid", "delivery_ready"}:
                    order.status = "paid"
                    lead = s.get(Lead, order.lead_id)
                    self.store.move(s, lead, Stage.PAID)
                    self.store.enqueue(s, lead.id, "fulfill", key=f"order:{order.id}:fulfill", payload={"order_id": order.id})
                    s.add(Activity(lead_id=lead.id, kind="payment_confirmed", detail={"order_id": order.id, "event_id": event_id}))
                    attribution = s.get(Attribution, lead.id)
                    if attribution:
                        s.add(MoneyEntry(
                            request_key=f"payment:{order.id}", campaign_id=attribution.campaign_id,
                            lead_id=lead.id, order_id=order.id, kind="revenue", amount_cents=order.amount_cents,
                            currency=order.currency, detail="Verified Stripe payment; taxes/fees/costs require accounting.",
                        ))
                result = "paid"
            s.add(order)
            s.add(WebhookReceipt(event_id=event_id))
            return result

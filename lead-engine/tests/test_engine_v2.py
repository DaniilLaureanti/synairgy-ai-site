from __future__ import annotations

import hashlib
import hmac
import json
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from synairgy.api import create_app
from synairgy.billing import Billing
from synairgy.demos import render
from synairgy.domain import BusinessError, Stage, backoff, email_address, identity, transition
from synairgy.models import Activity, Job, Lead, Message, Order
from synairgy.outreach import Outreach
from synairgy.ports import ProviderFailure
from synairgy.safe_http import get_public, public_target
from synairgy.settings import Settings
from synairgy.store import Store
from synairgy.workflow import Worker

PLACE = {
    "name": "DEMO Testbetrieb",
    "website": "https://company.example",
    "address": "Demo-Str. 1",
    "email": "office@company.example",
    "business_status": "OPERATIONAL",
}
ANALYSIS = {
    "problem": "Contact flow can be clearer",
    "evidence": ["No contact form in inspected HTML"],
    "recommended_offer": "Landing",
    "score_components": {"business_quality": 20, "pain_strength": 29, "synairgy_fit": 25, "contactability": 15, "evidence_confidence": 10},
    "opening": "Guten Tag",
    "call_script": "Privates Konzept",
}


class Inspector:
    def inspect(self, place):
        return {
            "reachable": True,
            "title": "DEMO Testbetrieb",
            "meta_description": "Demo description",
            "email": place.get("email", ""),
            "signals": {"has_contact_form": False},
            "text": "Test",
        }


class Analyzer:
    def __init__(self, error=None, offer="Landing"):
        self.calls, self.error, self.offer = 0, error, offer

    def analyze(self, place, site):
        self.calls += 1
        if self.error:
            raise self.error
        return {**ANALYSIS, "recommended_offer": self.offer, "price_eur": 1, "score": 1000}


class Sender:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise TimeoutError("ambiguous SMTP delivery")
        return kwargs["message_id"]


class StripeClient:
    def __init__(self):
        self.calls = []
        self.v1 = SimpleNamespace(checkout=SimpleNamespace(sessions=self))

    def create(self, params, options=None):
        self.calls.append((params, options))
        return SimpleNamespace(id="cs_test_demo", url="https://checkout.stripe.com/c/pay/cs_test_demo")


@pytest.fixture
def rig(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        admin_token="a" * 40,
        public_url="https://engine.example",
        outreach_enabled=True,
        smtp_host="smtp.example",
        sender_email="mail@synairgy.example",
        sender_address="DEMO postal address",
        stripe_webhook_secret="test-webhook-signing-secret",
    )
    store = Store(settings.database_url)
    analyzer, sender, stripe = Analyzer(), Sender(), StripeClient()
    worker = Worker(store, settings, inspector=Inspector(), analyzer=analyzer)
    outreach, billing = Outreach(store, settings, sender), Billing(store, settings, stripe)
    app = create_app(settings, store, worker=worker, outreach=outreach, billing=billing)
    return SimpleNamespace(
        settings=settings,
        store=store,
        worker=worker,
        outreach=outreach,
        billing=billing,
        analyzer=analyzer,
        sender=sender,
        stripe=stripe,
        client=TestClient(app),
        headers={"Authorization": "Bearer " + settings.admin_token},
    )


def prepared(rig, verified=True):
    lead, _ = rig.store.add_lead(dict(PLACE), verified_contact=verified)
    assert rig.worker.run() == {"done": 4}
    return rig.store.get(Lead, lead.id)


def interested(rig):
    lead = prepared(rig)
    rig.outreach.record_reply(lead.id, lead.email, interested=True)
    return rig.store.get(Lead, lead.id)


def event(order, *, event_id="evt_test", kind="checkout.session.completed", paid=True, amount=None, live=False):
    return {
        "id": event_id,
        "object": "event",
        "type": kind,
        "livemode": live,
        "data": {
            "object": {
                "id": order.session_id,
                "object": "checkout.session",
                "client_reference_id": order.id,
                "currency": "eur",
                "amount_total": order.amount_cents if amount is None else amount,
                "payment_status": "paid" if paid else "unpaid",
            }
        },
    }


def signed(rig, ev):
    payload = json.dumps(ev).encode()
    ts = int(time.time())
    digest = hmac.new(rig.settings.stripe_webhook_secret.encode(), str(ts).encode() + b"." + payload, hashlib.sha256).hexdigest()
    return payload, f"t={ts},v1={digest}"


def test_full_flow_with_signed_payment_and_private_delivery(rig):
    lead = prepared(rig)
    msg = rig.store.all(Message)[0]
    rig.outreach.approve(msg.id)
    assert rig.outreach.send_one() == "sent"
    rig.outreach.record_reply(lead.id, lead.email, interested=True)
    order = rig.billing.checkout(lead.id, "request-1")
    payload, signature = signed(rig, event(order))
    assert rig.client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": signature}).json()["result"] == "paid"
    assert rig.worker.tick() == "done"
    current = rig.store.get(Lead, lead.id)
    assert current.stage == Stage.DELIVERY_READY  # Not a false public deployment.
    response = rig.client.get(f"/delivery/{current.preview_token}/{order.id}")
    assert response.status_code == 200 and response.content.startswith(b"PK")
    assert len(rig.sender.calls) == 1


def test_dedupe_survives_reopen(rig):
    one, _ = rig.store.add_lead(dict(PLACE))
    other = Store(rig.settings.database_url)
    two, created = other.add_lead(dict(PLACE))
    assert not created and one.id == two.id
    assert len(other.all(Job)) == 1


def test_concurrent_claim_only_one_owner(rig):
    rig.store.add_lead(dict(PLACE))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: rig.store.claim(), range(2)))
    assert sum(item is not None for item in results) == 1


def test_stale_worker_cannot_commit(rig):
    rig.store.add_lead(dict(PLACE))
    first = rig.store.claim(now=10000000000)
    second = rig.store.claim(now=10000000301)
    assert second.id == first.id and second.lease_token != first.lease_token
    with pytest.raises(BusinessError, match="Stale"):
        rig.store.finish(first, lambda session, lead: None)
    rig.store.finish(second, lambda session, lead: None)


def test_result_and_next_job_rollback_together(rig):
    lead, _ = rig.store.add_lead(dict(PLACE))
    job = rig.store.claim()

    def bad_commit(s, current):
        current.company = "must not persist"
        s.add(current)
        rig.store.enqueue(s, current.id, "demo")
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        rig.store.finish(job, bad_commit)
    assert rig.store.get(Lead, lead.id).company == PLACE["name"]
    assert len(rig.store.all(Job)) == 1


def test_quota_error_blocks_without_retry_loop(rig):
    rig.worker.analyzer = Analyzer(ProviderFailure("openai_credit_balance_exhausted", blocked=True))
    rig.store.add_lead(dict(PLACE))
    assert rig.worker.run() == {"done": 1, "blocked": 1}
    assert rig.worker.run() == {}
    blocked = next(x for x in rig.store.all(Job) if x.status == "blocked")
    assert blocked.attempts == 1


def test_transient_retry_is_delayed_and_bounded(rig):
    rig.store.add_lead(dict(PLACE))
    for i in range(4):
        job = rig.store.claim(now=time.time() + 100000 * (i + 1))
        rig.store.fail(job, "temporary")
    assert rig.store.all(Job)[0].status == "dead"


def test_model_cannot_set_price(rig):
    lead = prepared(rig)
    assert lead.analysis["price_eur"] == 1490
    assert lead.analysis["score"] == 99


def test_manual_services_are_not_sold_as_automated(rig):
    rig.worker.analyzer = Analyzer(offer="Image Film")
    lead, _ = rig.store.add_lead(dict(PLACE))
    assert rig.worker.run() == {"done": 2}
    assert rig.store.get(Lead, lead.id).stage == Stage.QUALIFIED
    assert rig.store.all(Message) == []
    assert any(x.kind == "manual_offer_required" for x in rig.store.all(Activity))


def test_no_email_is_not_a_fake_successful_outreach(rig):
    no_email = {k: v for k, v in PLACE.items() if k != "email"}
    rig.store.add_lead(no_email)
    rig.worker.run()
    assert rig.store.all(Message) == []
    assert any(x.kind == "contact_missing" for x in rig.store.all(Activity))


def test_contact_must_be_verified(rig):
    lead = prepared(rig, verified=False)
    msg = rig.store.all(Message)[0]
    with pytest.raises(BusinessError):
        rig.outreach.approve(msg.id)
    rig.outreach.verify_contact(lead.id, lead.email)
    rig.outreach.approve(msg.id)
    assert rig.outreach.send_one() == "sent"


def test_default_outreach_disabled_even_with_approved_message(rig):
    prepared(rig)
    msg = rig.store.all(Message)[0]
    rig.outreach.approve(msg.id)
    disabled = Outreach(rig.store, replace(rig.settings, outreach_enabled=False), rig.sender)
    assert disabled.send_one() == "disabled"
    assert rig.sender.calls == []


def test_reply_stops_followup_chain(rig):
    lead = prepared(rig)
    rig.outreach.approve(rig.store.all(Message)[0].id)
    assert rig.outreach.send_one() == "sent"
    rig.outreach.record_reply(lead.id, lead.email)
    assert rig.outreach.send_one(now=time.time() + 40 * 86400) == "idle"
    assert len(rig.sender.calls) == 1


def test_followup_limit_is_two(rig):
    prepared(rig)
    rig.outreach.approve(rig.store.all(Message)[0].id)
    for days in [0, 8, 32]:
        assert rig.outreach.send_one(now=time.time() + days * 86400) == "sent"
    assert rig.outreach.send_one(now=time.time() + 100 * 86400) == "idle"
    assert len(rig.store.all(Message)) == 3


def test_smtp_uncertainty_never_auto_resends(rig):
    prepared(rig)
    rig.sender.fail = True
    rig.outreach.approve(rig.store.all(Message)[0].id)
    assert rig.outreach.send_one() == "needs_review"
    assert rig.outreach.send_one(now=time.time() + 100000) == "idle"
    assert len(rig.sender.calls) == 1


def test_daily_budget_not_bypassed(rig):
    prepared(rig)
    rig.outreach.approve(rig.store.all(Message)[0].id)
    rig.outreach.settings = replace(rig.settings, daily_limit=1)
    assert rig.outreach.send_one() == "sent"
    with pytest.raises(BusinessError, match="budget"):
        rig.outreach.send_one(now=time.time() + 8 * 86400)
    assert len(rig.sender.calls) == 1


def test_suppression_prevents_future_leads_and_messages(rig):
    rig.store.suppress(PLACE["email"])
    lead, _ = rig.store.add_lead(dict(PLACE), verified_contact=True)
    assert lead.suppressed and lead.stage == Stage.SUPPRESSED
    assert rig.store.all(Job) == []


def test_unsubscribe_get_does_not_mutate_but_post_does(rig):
    lead = prepared(rig)
    msg = rig.store.all(Message)[0]
    url = "/unsubscribe/" + msg.unsubscribe_token
    assert rig.client.get(url).status_code == 200
    assert not rig.store.get(Lead, lead.id).suppressed
    assert rig.client.post(url).status_code == 200
    assert rig.client.post(url).status_code == 200
    assert rig.store.get(Lead, lead.id).suppressed


def test_checkout_idempotent_and_server_priced(rig):
    lead = interested(rig)
    first = rig.billing.checkout(lead.id, "request-1")
    second = rig.billing.checkout(lead.id, "request-1")
    assert first.id == second.id and len(rig.stripe.calls) == 1
    params, options = rig.stripe.calls[0]
    assert params["line_items"][0]["price_data"]["unit_amount"] == 149000
    assert "payment_method_types" not in params and "automatic_tax" not in params
    assert options["idempotency_key"] == "synairgy:" + first.id
    assert len(params["integration_identifier"].rsplit("-", 1)[1]) == 8


def test_uninterested_customer_cannot_create_checkout(rig):
    lead = prepared(rig)
    with pytest.raises(BusinessError):
        rig.billing.checkout(lead.id, "request-1")
    assert rig.stripe.calls == []


def test_unpaid_completed_waits_for_async_success(rig):
    order = rig.billing.checkout(interested(rig).id, "request-1")
    assert rig.billing.receive(event(order, paid=False)) == "pending"
    assert not any(x.kind == "fulfill" for x in rig.store.all(Job))
    assert rig.billing.receive(event(order, event_id="evt_async", kind="checkout.session.async_payment_succeeded")) == "paid"
    assert sum(x.kind == "fulfill" for x in rig.store.all(Job)) == 1


def test_duplicate_webhooks_do_not_duplicate_fulfillment(rig):
    order = rig.billing.checkout(interested(rig).id, "request-1")
    assert rig.billing.receive(event(order)) == "paid"
    assert rig.billing.receive(event(order)) == "duplicate"
    rig.billing.receive(event(order, event_id="evt_second"))
    assert sum(x.kind == "fulfill" for x in rig.store.all(Job)) == 1


@pytest.mark.parametrize("override", [{"amount": 1}, {"live": True}])
def test_payment_mismatch_does_not_grant_delivery(rig, override):
    order = rig.billing.checkout(interested(rig).id, "request-1")
    with pytest.raises(BusinessError):
        rig.billing.receive(event(order, **override))
    assert rig.store.get(Order, order.id).status == "pending"


def test_invalid_signature_does_not_grant_delivery(rig):
    response = rig.client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "bad"})
    assert response.status_code == 400
    assert rig.store.all(Order) == []


def test_success_page_never_marks_paid(rig):
    order = rig.billing.checkout(interested(rig).id, "request-1")
    assert rig.client.get("/payment/received").status_code == 200
    assert rig.store.get(Order, order.id).status == "pending"


def test_suppressed_paying_customer_still_gets_contractual_delivery(rig):
    lead = interested(rig)
    order = rig.billing.checkout(lead.id, "request-1")
    rig.store.suppress(lead.email)
    rig.billing.receive(event(order))
    assert rig.worker.tick() == "done"
    assert rig.store.get(Lead, lead.id).stage == Stage.DELIVERY_READY


def test_api_private_by_default(rig):
    assert rig.client.get("/healthz").status_code == 200
    assert rig.client.get("/api/leads").status_code == 401
    assert rig.client.get("/api/leads", headers=rig.headers).status_code == 200
    assert rig.client.get("/docs").status_code == 404
    assert rig.client.get("/openapi.json").status_code == 404


def test_preview_capability_is_required(rig):
    lead = prepared(rig)
    assert rig.client.get("/preview/" + lead.id).status_code == 404
    response = rig.client.get("/preview/" + lead.preview_token)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "noindex" in response.headers["x-robots-tag"]
    assert "default-src 'none'" in response.headers["content-security-policy"]


def test_render_escapes_untrusted_data(rig):
    lead = prepared(rig)
    lead.company = '<script>alert("x")</script>'
    assert "<script>" not in render(lead)
    assert "&lt;script&gt;" in render(lead)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"])
def test_private_network_fetch_is_rejected(address):
    with patch("socket.getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]):
        with pytest.raises(ValueError, match="non_public"):
            public_target("https://company.example")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:password@example.com/", "http://example.com:22"])
def test_invalid_targets_rejected(url):
    with pytest.raises(ValueError):
        public_target(url)


def test_redirect_to_private_address_rejected_before_second_request():
    response = SimpleNamespace(status=302, headers={"Location": "http://127.0.0.1"}, close=lambda: None)
    pool = SimpleNamespace(request=lambda *a, **kw: response, close=lambda: None)

    def resolution(host, *args, **kwargs):
        addr = "127.0.0.1" if host == "127.0.0.1" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 80))]

    with patch("socket.getaddrinfo", side_effect=resolution), patch("urllib3.HTTPConnectionPool", return_value=pool):
        with pytest.raises(ValueError, match="non_public"):
            get_public("http://company.example")


@pytest.mark.parametrize("value", ["a@b.example\r\nBcc:x@y.example", "invalid", "a@b.example,c@d.example"])
def test_invalid_email_rejected(value):
    with pytest.raises(BusinessError):
        email_address(value)


def test_invalid_transition_rejected():
    with pytest.raises(BusinessError):
        transition(Stage.NEW, Stage.FULFILLED)


def test_identity_and_backoff_are_stable():
    assert identity(PLACE) == identity(dict(PLACE))
    assert backoff(1) == 30 and backoff(1000) <= 3600

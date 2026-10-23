from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from test_engine_v2 import PLACE, Analyzer, Inspector, Sender, StripeClient, event, prepared, signed

from synairgy.api import create_app
from synairgy.billing import Billing
from synairgy.cli import discovery
from synairgy.console import TZ
from synairgy.domain import BusinessError
from synairgy.models import Activity, Lead, Message, Order, SchemaVersion, TelegramAction, TelegramDelivery
from synairgy.outreach import Outreach
from synairgy.portfolio import Portfolio
from synairgy.settings import Settings
from synairgy.store import Store
from synairgy.telegram import TelegramClient, TelegramConsole, TelegramFailure, TelegramRunner, pair, resolve_owner, setup
from synairgy.workflow import Worker


class FakeTelegram:
    def __init__(self):
        self.calls, self.updates, self.failure = [], [], None

    def call(self, method, payload):
        self.calls.append((method, payload))
        if self.failure:
            error, self.failure = self.failure, None
            raise error
        if method == "getUpdates":
            return [u for u in self.updates if u["update_id"] >= payload["offset"]]
        if method == "getMe":
            return {"id": 123456, "username": "SyntheticSynAirgyBot"}
        if method == "getWebhookInfo":
            return {"url": ""}
        return True


@pytest.fixture
def bot(tmp_path):
    settings = Settings(data_dir=tmp_path, telegram_enabled=False, telegram_token="123456:" + "A" * 32,
                        telegram_owner_id=7654321, admin_token="x" * 40, public_url="https://engine.example",
                        outreach_enabled=True, smtp_host="smtp.example", sender_email="mail@synairgy.example",
                        sender_address="Synthetic address", stripe_webhook_secret="synthetic-signing-secret")
    store = Store(settings.database_url)
    client, sender = FakeTelegram(), Sender()
    portfolio = Portfolio(store, settings)
    console = TelegramConsole(store, settings, portfolio, client)
    rig = SimpleNamespace(settings=settings, store=store, portfolio=portfolio, console=console, telegram=client,
                          sender=sender, outreach=Outreach(store, settings, sender))
    rig.worker = Worker(store, settings, inspector=Inspector(), analyzer=Analyzer())
    rig.billing = Billing(store, settings, StripeClient())
    rig.client = TestClient(create_app(settings, store, worker=rig.worker, outreach=rig.outreach, billing=rig.billing, portfolio=portfolio))
    rig.headers = {"Authorization": "Bearer " + settings.admin_token}
    return rig


def incoming(bot, number, text="/start", *, owner=None, chat=None, chat_type="private"):
    owner = bot.settings.telegram_owner_id if owner is None else owner
    return {"update_id": number, "message": {"message_id": number, "from": {"id": owner, "is_bot": False},
            "chat": {"id": owner if chat is None else chat, "type": chat_type}, "text": text}}


def callback(bot, number, data, **kwargs):
    message = incoming(bot, number, **kwargs)["message"]
    return {"update_id": number, "callback_query": {"id": str(number), "from": message["from"], "message": message, "data": data}}


def confirm(bot, target="outreach", paused=True, number=10, now=None):
    bot.console.accept(callback(bot, number, f"pause:{target}:{int(paused)}"), now=now)
    pending = bot.store.all(TelegramAction)[-1]
    bot.console.accept(callback(bot, number + 1, f"confirm:{pending.id}"), now=now)
    return pending


def test_unknown_users_groups_and_forged_chats_cannot_read_or_control(bot):
    values = [incoming(bot, 1, owner=99), incoming(bot, 2, chat=-99, chat_type="group"),
              callback(bot, 3, "pause:outreach:1", owner=99, chat=bot.settings.telegram_owner_id),
              callback(bot, 4, "money", chat=-99, chat_type="supergroup")]
    assert [bot.console.accept(v) for v in values] == ["ignored"] * 4
    assert not bot.store.all(TelegramDelivery) and not bot.store.all(TelegramAction)
    assert bot.console.accept({"update_id": True}) == "invalid"


def test_menu_views_work_without_live_ai_mail_or_payments(bot):
    with patch("requests.sessions.Session.request", side_effect=AssertionError("live service called")):
        for number, command in enumerate(["/start", "/help", "/status", "/markets", "/leads", "/money", "/issues", "/controls", "/report", "/weekly"], 1):
            assert bot.console.accept(incoming(bot, number, command)) == "accepted"
    rows = bot.store.all(TelegramDelivery)
    assert len(rows) == 10 and all(len(r.payload["text"]) <= 3900 for r in rows)
    assert "Компаний в CRM: 0" in rows[0].payload["text"]
    assert "Прибыль не рассчитана" in rows[5].payload["text"]
    assert not bot.store.all(Lead) and not bot.store.all(Message)


def test_duplicate_updates_commit_one_response_even_concurrently(bot):
    value = incoming(bot, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: bot.console.accept(value), range(2)))
    assert sorted(outcomes) == ["accepted", "duplicate"]
    assert len(bot.store.all(TelegramDelivery)) == 1


def test_command_failure_rolls_back_receipt_offset_and_effects(bot):
    with patch.object(bot.console, "route", side_effect=RuntimeError("synthetic crash")), pytest.raises(RuntimeError):
        bot.console.accept(incoming(bot, 1))
    with Session(bot.store.engine) as s:
        assert bot.store.control_value(s, bot.console.offset_key) == {}
    assert bot.console.accept(incoming(bot, 1)) == "accepted"


def test_pause_requires_confirmation_survives_restart_and_cannot_replay(bot):
    bot.console.accept(callback(bot, 1, "pause:outreach:1"))
    assert not bot.store.paused("outreach")
    action = bot.store.all(TelegramAction)[0]
    bot.console.accept(callback(bot, 2, f"confirm:{action.id}"))
    assert Store(bot.settings.database_url).paused("outreach")
    bot.store.set_paused("outreach", False)
    bot.console.accept(callback(bot, 3, f"confirm:{action.id}"))
    assert not bot.store.paused("outreach")


def test_expired_and_stale_confirmations_do_not_override_newer_decisions(bot):
    now = time.time()
    bot.console.accept(callback(bot, 1, "pause:outreach:1"), now=now)
    action = bot.store.all(TelegramAction)[0]
    bot.console.accept(callback(bot, 2, f"confirm:{action.id}"), now=now + 601)
    assert not bot.store.paused("outreach")
    bot.console.accept(callback(bot, 3, "pause:outreach:1"), now=now + 602)
    action = bot.store.all(TelegramAction)[-1]
    bot.store.set_paused("outreach", False)
    bot.console.accept(callback(bot, 4, f"confirm:{action.id}"), now=now + 603)
    assert not bot.store.paused("outreach")


def test_pause_blocks_real_sender_and_search_without_spending_budget(bot):
    lead = prepared(bot)
    msg = bot.store.all(Message)[0]
    bot.outreach.approve(msg.id)
    confirm(bot)
    assert bot.outreach.send_one() == "paused" and bot.sender.calls == []
    confirm(bot, target="acquisition", number=20)
    with patch("google_places.search_places", side_effect=AssertionError("search called")):
        assert discovery(bot.settings, bot.store, "test", 1)["status"] == "paused"
        assert bot.portfolio.tick()["status"] == "paused"
        assert bot.portfolio.research()["status"] == "paused"
    confirm(bot, paused=False, number=30)
    disabled = Outreach(bot.store, replace(bot.settings, outreach_enabled=False), bot.sender)
    assert disabled.send_one() == "disabled" and bot.sender.calls == []
    assert bot.store.get(Lead, lead.id).stage == "DEMO_READY"


def test_payment_webhook_and_fulfillment_continue_while_both_lanes_paused(bot):
    lead = prepared(bot)
    bot.outreach.record_reply(lead.id, lead.email, interested=True)
    order = bot.billing.checkout(lead.id, "pause-test")
    confirm(bot)
    confirm(bot, target="acquisition", number=20)
    payload, signature = signed(bot, event(order))
    assert bot.client.post("/webhooks/stripe", content=payload, headers={"Stripe-Signature": signature}).status_code == 200
    assert bot.worker.run() == {"done": 1}
    assert bot.store.get(Order, order.id).status == "delivery_ready"


def test_controls_api_is_authenticated_strict_and_shared_with_bot(bot):
    assert bot.client.get("/api/controls").status_code == 401
    assert bot.client.post("/api/controls/pause", json={"target": "outreach", "paused": True}).status_code == 401
    assert bot.client.post("/api/controls/pause", json={"target": "outreach", "paused": "yes"}, headers=bot.headers).status_code == 422
    response = bot.client.post("/api/controls/pause", json={"target": "acquisition", "paused": True}, headers=bot.headers)
    assert response.json()["acquisition"]["paused"] and bot.store.paused("acquisition")


def test_untrusted_company_data_is_escaped_and_leads_are_paginated(bot):
    for n in range(7):
        bot.store.add_lead({"name": "<b>" + "&" * 290, "address": f"Synthetic {n}"})
    for number, data in [(1, "leads:0"), (2, "leads:1")]:
        bot.console.accept(callback(bot, number, data))
    rows = [r for r in bot.store.all(TelegramDelivery) if r.method == "sendMessage"]
    assert len(rows[0].payload["reply_markup"]["inline_keyboard"]) == 10
    assert "&lt;b&gt;" in rows[0].payload["text"] and "<b>&" not in rows[0].payload["text"]
    assert all(len(row.payload["text"]) < 3900 for row in rows)


def test_reports_alerts_and_offset_survive_restart_without_duplicate_enqueues(bot):
    now = datetime(2026, 10, 26, 19, 5, tzinfo=TZ).timestamp()
    bot.console.accept(incoming(bot, 1), now=now - 10)
    lead, _ = bot.store.add_lead(PLACE)
    with bot.store.transaction() as s:
        s.add(Activity(lead_id=lead.id, kind="payment_confirmed", created_at=now - 5))
        s.add(Activity(lead_id=lead.id, kind="package_created", created_at=now - 4))
    bot.console.periodic(now=now)
    count = len(bot.store.all(TelegramDelivery))
    reopened = Store(bot.settings.database_url)
    other = TelegramConsole(reopened, bot.settings, Portfolio(reopened, bot.settings), bot.telegram)
    other.periodic(now=now + 1)
    assert len(reopened.all(TelegramDelivery)) == count == 5  # start, day, week, two events
    text = "\n".join(row.payload["text"] for row in reopened.all(TelegramDelivery))
    assert "19.10–25.10.2026" in text and "ещё не считается опубликованным" in text
    with Session(reopened.engine) as s:
        assert reopened.control_value(s, other.offset_key)["next"] == 2


def test_no_scheduled_messages_before_owner_starts_or_before_report_hour(bot):
    now = datetime(2026, 10, 23, 18, tzinfo=TZ).timestamp()
    bot.console.periodic(now=now)
    assert bot.store.all(TelegramDelivery) == []
    bot.console.accept(incoming(bot, 1), now=now)
    bot.console.periodic(now=now)
    assert len(bot.store.all(TelegramDelivery)) == 1


def test_weekly_report_uses_berlin_calendar_boundaries_across_dst(bot):
    start = datetime(2026, 10, 19, tzinfo=TZ).timestamp()
    end = datetime(2026, 10, 26, tzinfo=TZ).timestamp()
    with bot.store.transaction() as s:
        for n, timestamp in enumerate([start - 1, start, end - 1, end]):
            s.add(Lead(identity_key=f"period-{n}", company="Synthetic", created_at=timestamp))
        view = bot.console.views.report(s, now=end + 36000, weekly=True)
    assert "Новых компаний: 2" in view.text and "19.10–25.10.2026" in view.text


def test_telegram_retry_after_and_permanent_failures_do_not_touch_commercial_state(bot):
    now = time.time()
    bot.console.accept(incoming(bot, 1), now=now)
    bot.telegram.failure = TelegramFailure("telegram_http_429", retry_after=60)
    assert bot.console.flush_one(now=now) == "pending"
    assert bot.console.flush_one(now=now + 59) == "throttled"
    assert bot.console.flush_one(now=now + 60) == "sent"
    bot.console.accept(incoming(bot, 2), now=now + 61)
    bot.telegram.failure = TelegramFailure("telegram_http_403", permanent=True)
    assert bot.console.flush_one(now=now + 61) == "failed"
    assert not bot.store.paused("outreach") and not bot.store.all(Lead)


def test_transport_never_exposes_secret_url_and_refuses_redirects():
    token = "123456:" + "B" * 32
    session = SimpleNamespace(post=lambda *a, **kw: (_ for _ in ()).throw(requests.Timeout(f"https://api.telegram.org/bot{token}")))
    with pytest.raises(TelegramFailure) as error:
        TelegramClient(token, session).call("getMe", {})
    assert token not in str(error.value) and "https" not in str(error.value)
    session = SimpleNamespace(post=lambda *a, **kw: SimpleNamespace(status_code=302))
    with pytest.raises(TelegramFailure, match="redirect_refused"):
        TelegramClient(token, session).call("getMe", {})


def test_one_poller_and_durable_offset_across_runner_restarts(bot):
    one, two = TelegramRunner(bot.console), TelegramRunner(bot.console)
    assert one.acquire(1000) and not two.acquire(1001) and two.acquire(1181)
    two.release()
    bot.telegram.updates = [incoming(bot, 100), incoming(bot, 101)]
    assert one.once()["status"] == "ok"
    one.release()
    assert two.once()["updates"] == 0
    two.release()
    sent = [c for c in bot.telegram.calls if c[0] == "sendMessage"]
    assert len(sent) == 2


def test_v2_migration_and_backup_restore_keep_records_and_add_controls(tmp_path):
    path = tmp_path / "v2.sqlite3"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine, tables=[SchemaVersion.__table__, Lead.__table__])
    with Session(engine) as s:
        s.add(SchemaVersion(version=2))
        s.add(Lead(identity_key="existing", id="old", company="Existing customer"))
        s.commit()
    with sqlite3.connect(path) as source, sqlite3.connect(tmp_path / "backup.sqlite3") as target:
        source.backup(target)
    store = Store(f"sqlite:///{path}")
    store.set_paused("outreach", True)
    assert store.get(SchemaVersion, 3) and store.get(Lead, "old").company == "Existing customer"
    assert Store(f"sqlite:///{path}").paused("outreach")
    restored = Store(f"sqlite:///{tmp_path / 'backup.sqlite3'}")
    assert restored.get(Lead, "old") and not restored.paused("outreach")


def test_setup_checks_dedicated_bot_and_lifespan_stops_poller(bot):
    assert setup(bot.console)["live_message_sent"] is False
    assert [x[0] for x in bot.telegram.calls] == ["getMe", "getWebhookInfo", "setMyCommands"]
    started = threading.Event()
    fake = SimpleNamespace(stop=threading.Event())
    def run():
        started.set()
        fake.stop.wait()
    fake.run = run
    app = create_app(replace(bot.settings, telegram_enabled=True), bot.store, telegram_runner=fake)
    with TestClient(app) as client:
        assert started.wait(1) and client.get("/healthz").status_code == 200
    assert fake.stop.is_set()


def test_pairing_binds_only_private_challenge_holder_and_is_not_overwritten(bot):
    settings = replace(bot.settings, telegram_enabled=True, telegram_owner_id=0)
    bot.telegram.updates = [incoming(bot, 1, owner=99), incoming(bot, 2, "/start fixture-challenge", owner=99, chat=-1, chat_type="group"),
                            incoming(bot, 3, "/start fixture-challenge")]
    with patch("synairgy.telegram.secrets.token_urlsafe", return_value="fixture-challenge"):
        result = pair(settings, bot.store, client=bot.telegram, announce=lambda _: None)
    assert result["owner_id"] == bot.settings.telegram_owner_id
    assert resolve_owner(settings, Store(bot.settings.database_url)).telegram_owner_id == result["owner_id"]
    with pytest.raises(BusinessError, match="already configured"):
        pair(settings, bot.store, client=bot.telegram, announce=lambda _: None)


def test_global_rate_limit_is_shared_by_all_pending_deliveries(bot):
    now = time.time()
    bot.console.accept(incoming(bot, 1), now=now)
    bot.console.accept(incoming(bot, 2), now=now)
    bot.telegram.failure = TelegramFailure("telegram_http_429", retry_after=90)
    assert bot.console.flush_one(now=now) == "pending"
    assert bot.console.flush_one(now=now + 1) == "throttled"
    assert len(bot.telegram.calls) == 1


def test_expired_delivery_lease_cannot_overwrite_recovered_delivery(bot):
    now = time.time()
    bot.console.accept(incoming(bot, 1), now=now)
    entered, resume = threading.Event(), threading.Event()
    class SlowTelegram:
        calls = 0
        def call(self, method, payload):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                assert resume.wait(5)
                raise TelegramFailure("telegram_transport_failure")
            return True
    bot.console.client = SlowTelegram()
    with ThreadPoolExecutor(max_workers=1) as pool:
        stale = pool.submit(bot.console.flush_one, now=now)
        assert entered.wait(2)
        assert bot.console.flush_one(now=now + 121) == "sent"
        resume.set()
        assert stale.result() == "stale"
    assert bot.store.all(TelegramDelivery)[0].status == "sent"


def test_scheduled_acquisition_pause_keeps_existing_outreach_running(bot, monkeypatch, capsys):
    from urllib.parse import urlsplit

    from synairgy.schedule import main

    prepared(bot)
    bot.outreach.approve(bot.store.all(Message)[0].id)
    bot.store.set_paused("acquisition", True)
    monkeypatch.setenv("LEAD_ENGINE_URL", "https://engine.example")
    monkeypatch.setenv("LEAD_ENGINE_ADMIN_TOKEN", bot.settings.admin_token)
    monkeypatch.setenv("DRY_RUN", "0")
    monkeypatch.setenv("LEAD_QUERY", "")
    paths = []
    def call(method, url, **kwargs):
        path = urlsplit(url).path
        paths.append(path)
        return bot.client.request(method, path, headers=kwargs["headers"], json=kwargs.get("json"))
    monkeypatch.setattr("synairgy.schedule.requests.request", call)
    assert main() == 0
    assert len(bot.sender.calls) == 1 and "/api/discover" not in paths and "/api/portfolio/tick" not in paths
    assert '"status": "paused"' in capsys.readouterr().out


def test_expired_poller_cannot_commit_commands_or_advance_offset(bot):
    now = time.time()
    old, new = TelegramRunner(bot.console), TelegramRunner(bot.console)
    assert old.acquire(now) and new.acquire(now + 181)
    update = incoming(bot, 77)
    assert bot.console.accept(update, now=now + 182, poller_token=old.lease_token) == "stale"
    with Session(bot.store.engine) as s:
        assert bot.store.control_value(s, bot.console.offset_key) == {}
    assert bot.console.accept(update, now=now + 182, poller_token=new.lease_token) == "accepted"

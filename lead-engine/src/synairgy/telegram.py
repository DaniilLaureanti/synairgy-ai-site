"""Owner-only Telegram control, durable commands/outbox, bounded long polling.

No model, prospecting, SMTP or Stripe calls are initiated by menu navigation.
Only explicit pause/resume confirmations mutate the commercial controls.
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
import time
from dataclasses import replace
from datetime import datetime

import requests
from sqlmodel import Session, select

from .console import TZ, Console, View, button, esc, euro
from .domain import BusinessError
from .models import Activity, ControlState, Lead, Message, Order, PortfolioRun, TelegramAction, TelegramDelivery, TelegramUpdate, uid

logger = logging.getLogger(__name__)

COMMANDS = [
    {"command": command, "description": description}
    for command, description in [
        ("start", "Открыть пульт"), ("help", "Помощь"), ("status", "Обзор системы"),
        ("markets", "Отрасли и результаты"), ("leads", "Компании и превью"), ("money", "Оплаты и расходы"),
        ("issues", "Нужно решение"), ("controls", "Пауза поиска и отправки"),
        ("report", "Итоги сегодня"), ("weekly", "Прошлая неделя"),
    ]
]


class TelegramFailure(Exception):
    def __init__(self, code, *, retry_after=30, permanent=False):
        super().__init__(code)
        self.code, self.retry_after, self.permanent = code, max(1, min(int(retry_after), 3600)), permanent


class TelegramClient:
    def __init__(self, token, session=None):
        self._token, self._session = token, session or requests.Session()

    def call(self, method, payload):
        if method not in {"getMe", "getWebhookInfo", "getUpdates", "setMyCommands", "sendMessage", "answerCallbackQuery"}:
            raise TelegramFailure("telegram_method_not_allowed", permanent=True)
        try:
            response = self._session.post(
                f"https://api.telegram.org/bot{self._token}/{method}", json=payload,
                timeout=(5, 10 + int(payload.get("timeout", 0))), allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise TelegramFailure("telegram_redirect_refused", permanent=True)
            data = response.json()
        except (requests.RequestException, ValueError):
            # requests exception strings/URLs contain the bot token. Never expose them.
            raise TelegramFailure("telegram_transport_failure") from None
        if not isinstance(data, dict):
            raise TelegramFailure("telegram_invalid_response")
        if response.status_code != 200 or data.get("ok") is not True:
            code = data.get("error_code", response.status_code)
            code = code if type(code) is int else response.status_code
            parameters = data.get("parameters")
            retry = parameters.get("retry_after", 30) if isinstance(parameters, dict) else 30
            retry = retry if type(retry) is int else 30
            raise TelegramFailure(f"telegram_http_{code}", retry_after=retry, permanent=code in {400, 401, 403, 404})
        return data.get("result")


class TelegramConsole:
    def __init__(self, store, settings, portfolio, client=None):
        if not settings.telegram_token or not settings.telegram_owner_id:
            raise BusinessError("Telegram requires a bot token and a positive owner ID")
        self.store, self.settings = store, settings
        self.bot_id, self.owner_id = settings.telegram_token.split(":", 1)[0], settings.telegram_owner_id
        self.namespace = f"telegram:{self.bot_id}:{self.owner_id}"
        self.offset_key = f"telegram:{self.bot_id}:offset"
        self.client = client or TelegramClient(settings.telegram_token)
        self.views = Console(store, settings, portfolio)

    def queue(self, s, key, payload, *, method="sendMessage", now=None):
        key = f"{self.namespace}:{key}"
        if not s.exec(select(TelegramDelivery).where(TelegramDelivery.dedupe_key == key)).first():
            s.add(TelegramDelivery(dedupe_key=key, bot_id=self.bot_id, owner_id=self.owner_id,
                                   method=method, payload=payload, due_at=time.time() if now is None else now))

    def _authorized(self, update):
        callback = update.get("callback_query")
        value = callback if isinstance(callback, dict) else update.get("message")
        if not isinstance(value, dict):
            return None
        message = value.get("message") if callback else value
        if not isinstance(message, dict):
            return None
        sender, chat = value.get("from", {}), message.get("chat", {})
        if sender.get("id") != self.owner_id or sender.get("is_bot") or chat.get("id") != self.owner_id or chat.get("type") != "private":
            return None
        return callback, message

    def accept(self, update, *, now=None, poller_token=None):
        now = time.time() if now is None else now
        if not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < 0:
            return "invalid"
        update_id = update["update_id"]
        receipt = f"{self.bot_id}:{update_id}"
        with self.store.transaction() as s:
            if poller_token is not None:
                lease = self.store.control_value(s, f"telegram:{self.bot_id}:poller")
                if lease.get("token") != poller_token or lease.get("until", 0) < now:
                    return "stale"
            if s.get(TelegramUpdate, receipt):
                return "duplicate"
            # Only the durable receipt/offset is retained; no raw chat content is stored.
            s.add(TelegramUpdate(key=receipt, update_id=update_id, created_at=now))
            offset = self.store.control_value(s, self.offset_key).get("next", 0)
            self.store.put_control(s, self.offset_key, {"next": max(offset, update_id + 1)})
            incoming = self._authorized(update)
            if incoming is None:
                return "ignored"
            callback, message = incoming
            started = f"{self.namespace}:started"
            if not self.store.control_value(s, started):
                self.store.put_control(s, started, {"at": now})
                self.store.put_control(s, f"{self.namespace}:events", {"at": now, "id": ""})
            if callback:
                data, callback_id = callback.get("data", ""), callback.get("id", "")
                if not isinstance(data, str) or len(data.encode()) > 64 or not isinstance(callback_id, str) or not 1 <= len(callback_id) <= 128:
                    return "invalid"
                self.queue(s, f"ack:{update_id}", {"callback_query_id": callback_id}, method="answerCallbackQuery", now=now)
                action = data
            else:
                text = message.get("text", "")
                action = text.split()[0].split("@")[0].lstrip("/") if isinstance(text, str) and text.startswith("/") and len(text) <= 256 else "help"
                action = "leads:0" if action == "leads" else action
            view = self.route(s, action, now=now)
            self.queue(s, f"reply:{update_id}", view.payload(self.owner_id), now=now)
        return "accepted"

    def route(self, s, action, *, now):
        if action in {"start", "status"}:
            return self.views.status(s)
        if action in {"help", "settings"}:
            return View("<b>SynAirgy · Личный пульт</b>\n\n"
                        "Обзор, отрасли, компании, оплаты и исключения — кнопками ниже. /controls — паузы.\n"
                        "Бот не запускает поиск или письма при открытии меню. Общие лимиты остаются в силе.\n"
                        "Входящая почта и публикация клиентских сайтов ещё подключаются отдельно.")
        if action == "controls":
            return self.views.controls(s)
        if action == "money":
            return self.views.money(s)
        if action == "markets":
            return self.views.markets()
        if action == "issues":
            return self.views.issues(s)
        if action in {"report", "weekly"}:
            return self.views.report(s, now=now, weekly=action == "weekly")
        if re.fullmatch(r"leads:[0-9]{1,4}", action):
            return self.views.leads(s, int(action.split(":")[1]))
        if re.fullmatch(r"lead:[a-f0-9]{32}", action):
            return self.views.lead(s, action.split(":")[1])
        if re.fullmatch(r"pause:(acquisition|outreach):[01]", action):
            _, target, paused = action.split(":")
            state = s.get(ControlState, f"pause:{target}")
            pending = TelegramAction(owner_id=self.owner_id, target=target, paused=paused == "1", expires_at=now + 600,
                                     expected_revision=state.revision if state else 0)
            s.add(pending)
            name = "отправки" if target == "outreach" else "поиска"
            verb = "Включить паузу" if pending.paused else "Снять паузу"
            return View(f"<b>{verb} {name}?</b>\nКнопка действует 10 минут. "
                        "Уже выполняющиеся операции могут завершиться; обработка оплат продолжится.",
                        [[button("Подтвердить", f"confirm:{pending.id}"), button("Отмена", "controls")]])
        if re.fullmatch(r"confirm:[a-f0-9]{32}", action):
            pending = s.get(TelegramAction, action.split(":")[1])
            if not pending or pending.owner_id != self.owner_id or pending.consumed or pending.expires_at < now:
                return View("Кнопка устарела или уже использована. Откройте управление заново.")
            state = s.get(ControlState, f"pause:{pending.target}")
            if (state.revision if state else 0) != pending.expected_revision:
                pending.consumed = True
                s.add(pending)
                return View("Состояние уже изменилось. Откройте управление заново.")
            self.store.set_paused(pending.target, pending.paused, session=s, actor=f"telegram:{self.owner_id}")
            pending.consumed = True
            s.add(pending)
            s.flush()
            return self.views.controls(s)
        return View("Команда не поддерживается. Используйте меню или /help.")

    def periodic(self, *, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as s:
            if not self.store.control_value(s, f"{self.namespace}:started"):
                return
            local = datetime.fromtimestamp(now, TZ)
            if local.hour >= self.settings.telegram_report_hour:
                self.queue(s, f"daily:{local.date()}", self.views.report(s, now=now).payload(self.owner_id), now=now)
            if local.weekday() == 0 and local.hour >= 9:
                year, week, _ = local.isocalendar()
                self.queue(s, f"weekly:{year}:{week}", self.views.report(s, now=now, weekly=True).payload(self.owner_id), now=now)
            cursor_key = f"{self.namespace}:events"
            cursor = self.store.control_value(s, cursor_key, {"at": now, "id": ""})
            events = list(s.exec(select(Activity).where(
                ((Activity.created_at > cursor["at"]) | ((Activity.created_at == cursor["at"]) & (Activity.id > cursor["id"]))),
                Activity.created_at <= now,
            ).order_by(Activity.created_at, Activity.id).limit(100)).all())
            for event in events:
                text = self.event_text(s, event)
                if text:
                    self.queue(s, f"event:{event.id}", View(text).payload(self.owner_id), now=now)
            if events:
                self.store.put_control(s, cursor_key, {"at": events[-1].created_at, "id": events[-1].id})
            for message in s.exec(select(Message).where(Message.status == "needs_review").limit(50)).all():
                lead = s.get(Lead, message.lead_id)
                text = f"<b>⚠️ Неопределённый исход отправки</b>\n{esc(lead.company if lead else 'Компания', 100)}\nАвтоповтор не выполняется. Проверьте исход отправки."
                self.queue(s, f"message-review:{message.id}", View(text).payload(self.owner_id), now=now)
            for run in s.exec(select(PortfolioRun).where(PortfolioRun.status.in_(["blocked", "failed"])).limit(50)).all():
                text = f"<b>⚠️ Исследование/поиск требует внимания</b>\n{esc(run.status, 20)} · {esc(run.error or run.result.get('code', ''), 80)}"
                self.queue(s, f"run-issue:{run.key}:{run.status}", View(text).payload(self.owner_id), now=now)

    @staticmethod
    def event_text(s, event):
        names = {"payment_confirmed": "💶 Оплата подтверждена", "package_created": "📦 Пакет сайта готов",
                 "reply_received": "💬 Зафиксирован ответ клиента", "job_failed": "⚠️ Ошибка задания"}
        if event.kind not in names:
            return ""
        if event.kind == "job_failed" and event.detail.get("status") not in {"blocked", "dead"}:
            return ""
        lead = s.get(Lead, event.lead_id)
        lines = [f"<b>{names[event.kind]}</b>", esc(lead.company if lead else "Системное событие", 100)]
        if event.kind == "payment_confirmed":
            order = s.get(Order, event.detail.get("order_id", ""))
            if order:
                lines.append(f"{euro(order.amount_cents)} · {esc(order.offer, 60)}")
        if event.kind == "package_created":
            lines.append("ZIP для проверки. Клиентский сайт ещё не считается опубликованным.")
        if event.kind == "job_failed":
            lines.append(f"{esc(event.detail.get('stage', ''), 40)} · {esc(event.detail.get('code', ''), 80)}")
        return "\n".join(lines)

    def flush_one(self, *, now=None):
        now = time.time() if now is None else now
        with self.store.transaction() as s:
            if self.store.control_value(s, f"telegram:{self.bot_id}:send_backoff").get("until", 0) > now:
                return "throttled"
            row = s.exec(select(TelegramDelivery).where(
                TelegramDelivery.bot_id == self.bot_id, TelegramDelivery.owner_id == self.owner_id,
                ((TelegramDelivery.status == "pending") & (TelegramDelivery.due_at <= now))
                | ((TelegramDelivery.status == "sending") & (TelegramDelivery.lease_until < now)),
            ).order_by(TelegramDelivery.created_at, TelegramDelivery.id).limit(1)).first()
            if not row:
                return "idle"
            if row.attempts >= 5:
                row.status, row.error = "failed", "telegram_attempts_exhausted"
                s.add(row)
                return "failed"
            if row.method not in {"sendMessage", "answerCallbackQuery"} or (row.method == "sendMessage" and row.payload.get("chat_id") != self.owner_id):
                row.status, row.error = "failed", "telegram_invalid_delivery"
                s.add(row)
                return "failed"
            row.status, row.lease_until, row.lease_token = "sending", now + 120, uid()
            row.attempts += 1
            s.add(row)
        failure = None
        try:
            self.client.call(row.method, row.payload)
        except TelegramFailure as exc:
            failure = exc
        except Exception:  # noqa: BLE001 - never log token-bearing provider exceptions
            failure = TelegramFailure("telegram_transport_failure")
        with self.store.transaction() as s:
            current = s.get(TelegramDelivery, row.id)
            if current.status != "sending" or current.lease_token != row.lease_token:
                return "stale"
            current.lease_until = 0
            if failure:
                current.error = failure.code
                current.status = "failed" if failure.permanent or current.attempts >= 5 else "pending"
                current.due_at = now + max(failure.retry_after, 2 ** current.attempts)
                if failure.code == "telegram_http_429":
                    self.store.put_control(s, f"telegram:{self.bot_id}:send_backoff", {"until": current.due_at})
            else:
                current.status, current.error = "sent", ""
            s.add(current)
            return current.status


class TelegramRunner:
    """One leased poller per bot/database. No webhook, public URL or Render needed."""

    def __init__(self, console):
        self.console, self.store = console, console.store
        self.lease_key = f"telegram:{console.bot_id}:poller"
        self.lease_token, self.stop = uid(), threading.Event()

    def acquire(self, now):
        with self.store.transaction() as s:
            lease = self.store.control_value(s, self.lease_key)
            if lease.get("until", 0) > now and lease.get("token") != self.lease_token:
                return False
            self.store.put_control(s, self.lease_key, {"token": self.lease_token, "until": now + 180})
            return True

    def once(self, *, timeout=0):
        if not self.acquire(time.time()):
            return {"status": "another_poller_active"}
        try:
            with Session(self.store.engine) as s:
                offset = self.store.control_value(s, self.console.offset_key).get("next", 0)
            updates = self.console.client.call("getUpdates", {"offset": offset, "limit": 50, "timeout": timeout,
                                                               "allowed_updates": ["message", "callback_query"]})
            if not isinstance(updates, list):
                raise TelegramFailure("telegram_invalid_updates")
            if not self.acquire(time.time()):
                return {"status": "another_poller_active"}
            for update in updates[:50]:
                if self.console.accept(update, poller_token=self.lease_token) == "stale":
                    return {"status": "another_poller_active"}
            self.console.periodic()
            outcomes = []
            for _ in range(10):
                if not self.acquire(time.time()):
                    break
                outcome = self.console.flush_one()
                if outcome == "idle":
                    break
                outcomes.append(outcome)
                if outcome in {"pending", "failed", "throttled"}:
                    break
            result = {"status": "ok", "updates": len(updates), "deliveries": outcomes}
        except TelegramFailure as exc:
            result = {"status": "blocked" if exc.permanent else "retry", "code": exc.code, "retry_after": exc.retry_after}
        with self.store.transaction() as s:
            self.store.put_control(s, f"{self.console.namespace}:health", {**result, "at": time.time()})
        return result

    def release(self):
        with self.store.transaction() as s:
            lease = self.store.control_value(s, self.lease_key)
            if lease.get("token") == self.lease_token:
                self.store.put_control(s, self.lease_key, {"token": self.lease_token, "until": 0})

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    result = self.once(timeout=25)
                except Exception:  # noqa: BLE001 - isolate the background loop; log no secret-bearing traceback
                    logger.error("telegram_loop_failed code=internal_error")
                    result = {"status": "retry", "retry_after": 30}
                delay = 1 if result["status"] == "ok" else max(5, result.get("retry_after", 30))
                self.stop.wait(delay)
        finally:
            self.release()


def setup(console):
    identity = console.client.call("getMe", {})
    webhook = console.client.call("getWebhookInfo", {})
    if webhook.get("url"):
        raise BusinessError("Telegram webhook is active; use a dedicated bot or explicitly remove its webhook first")
    console.client.call("setMyCommands", {"commands": COMMANDS})
    return {"status": "configured", "bot_username": identity.get("username"), "owner_id": console.owner_id,
            "live_message_sent": False}


def resolve_owner(settings, store):
    """An explicit environment owner wins; otherwise use a locally paired owner."""
    if settings.telegram_owner_id or not settings.telegram_token:
        return settings
    with Session(store.engine) as s:
        value = store.control_value(s, f"telegram:{settings.telegram_token.split(':', 1)[0]}:owner")
    owner = value.get("id", 0)
    return replace(settings, telegram_owner_id=owner) if type(owner) is int and owner > 0 else settings


def pair(settings, store, *, client=None, announce=print, timeout=300):
    """Bind the person who opens a short-lived random deep link, never first visitor."""
    if not settings.telegram_token or not settings.telegram_enabled:
        raise BusinessError("Configure TELEGRAM_BOT_TOKEN and TELEGRAM_ENABLED=1 first")
    if resolve_owner(settings, store).telegram_owner_id:
        raise BusinessError("Owner is already configured; pairing will not replace it")
    client = client or TelegramClient(settings.telegram_token)
    identity, webhook = client.call("getMe", {}), client.call("getWebhookInfo", {})
    username = identity.get("username", "")
    if webhook.get("url") or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        raise BusinessError("Pairing needs a dedicated bot with no active webhook")
    bot_id, lease_token = settings.telegram_token.split(":", 1)[0], uid()
    lease_key = f"telegram:{bot_id}:poller"
    challenge, deadline, offset = secrets.token_urlsafe(24), time.monotonic() + timeout, 0
    with store.transaction() as s:
        if store.control_value(s, lease_key).get("until", 0) > time.time():
            raise BusinessError("Stop the active Telegram poller before pairing")
        store.put_control(s, lease_key, {"token": lease_token, "until": time.time() + 180})
        offset = store.control_value(s, f"telegram:{bot_id}:offset").get("next", 0)
    try:
        announce(f"Open this private one-time link within 5 minutes and press Start: https://t.me/{username}?start={challenge}")
        while time.monotonic() < deadline:
            with store.transaction() as s:
                lease = store.control_value(s, lease_key)
                if lease.get("token") != lease_token:
                    raise BusinessError("Pairing lease lost")
                store.put_control(s, lease_key, {"token": lease_token, "until": time.time() + 180})
            updates = client.call("getUpdates", {"offset": offset, "limit": 50, "timeout": 20, "allowed_updates": ["message"]})
            if not isinstance(updates, list):
                raise TelegramFailure("telegram_invalid_updates")
            for update in updates[:50]:
                if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                    continue
                offset = max(offset, update["update_id"] + 1)
                message = update.get("message", {})
                sender, chat = message.get("from", {}), message.get("chat", {})
                owner = sender.get("id")
                if (message.get("text") != f"/start {challenge}" or type(owner) is not int or owner <= 0
                        or sender.get("is_bot") or chat.get("type") != "private" or chat.get("id") != owner):
                    continue
                with store.transaction() as s:
                    if store.control_value(s, f"telegram:{bot_id}:owner"):
                        raise BusinessError("Owner was already paired")
                    store.put_control(s, f"telegram:{bot_id}:owner", {"id": owner})
                    store.put_control(s, f"telegram:{bot_id}:offset", {"next": offset})
                from .portfolio import Portfolio

                paired = replace(settings, telegram_owner_id=owner)
                TelegramConsole(store, paired, Portfolio(store, paired), client).accept(update)
                return {"status": "paired", "owner_id": owner, "bot_username": username, "live_message_sent": False}
        raise BusinessError("Pairing expired; run the command again for a new link")
    finally:
        with store.transaction() as s:
            if store.control_value(s, lease_key).get("token") == lease_token:
                store.put_control(s, lease_key, {"token": lease_token, "until": 0})

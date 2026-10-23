"""Read-only Russian owner views. CRM records are data, never bot instructions."""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Activity, AllocationPlan, Job, Lead, Message, MoneyEntry, Order, PortfolioRun, TelegramDelivery

TZ = ZoneInfo("Europe/Berlin")


def esc(value, limit=180):
    parts, size = [], 0
    for char in str(value)[:limit]:
        piece = html.escape(char)
        if size + len(piece) > limit:
            break
        parts.append(piece)
        size += len(piece)
    return "".join(parts)


def euro(cents):
    return f"€{cents / 100:,.2f}".replace(",", " ")


def button(text, action):
    return {"text": text, "callback_data": action}


MENU = [
    [button("📊 Обзор", "status"), button("🧭 Отрасли", "markets")],
    [button("🏢 Лиды", "leads:0"), button("💶 Деньги", "money")],
    [button("⚠️ Нужно решение", "issues"), button("⏯ Управление", "controls")],
    [button("📅 Сегодня", "report"), button("🗓 Прошлая неделя", "weekly")],
]


@dataclass
class View:
    text: str
    keyboard: list = field(default_factory=lambda: MENU)

    def payload(self, owner_id):
        # Compose bounded views before HTML escaping. Never truncate mid-tag.
        if len(self.text) > 3900:
            raise ValueError("Telegram view exceeds message limit")
        return {"chat_id": owner_id, "text": self.text, "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True}, "reply_markup": {"inline_keyboard": self.keyboard}}


class Console:
    def __init__(self, store, settings, portfolio):
        self.store, self.settings, self.portfolio = store, settings, portfolio

    @staticmethod
    def count(s, model, *conditions):
        return s.exec(select(func.count()).select_from(model).where(*conditions)).one()

    def status(self, s):
        ready = self.settings.readiness()
        yes = lambda value: "настроено" if value else "не настроено"
        text = ["<b>SynAirgy · Обзор</b>",
                f"Компаний в CRM: {self.count(s, Lead)}",
                f"Черновиков: {self.count(s, Message, Message.status == 'draft')}",
                f"Первичных писем принято SMTP: {self.count(s, Message, Message.status == 'sent', Message.sequence == 0)}",
                f"Заказов с оплатой: {self.count(s, Order, Order.status.in_(['paid', 'delivery_ready']))}", "",
                f"Поиск: {'пауза' if self.store.paused('acquisition', session=s) else 'разрешён'}",
                (f"Отправка: {'пауза' if self.store.paused('outreach', session=s) else 'без паузы'}; "
                 f"общий флаг {'включён' if self.settings.outreach_enabled else 'выключен'}"),
                f"AI: {yes(bool(self.settings.openai_key))}; Places: {yes(bool(self.settings.google_key))}",
                f"Почта: {yes(ready['outreach']['ready'])}; Stripe: {yes(ready['billing']['ready'])}",
                f"Платежи: {'LIVE' if self.settings.stripe_live else 'sandbox'}", "",
                "Наличие настроек не доказывает баланс и доступность сервиса."]
        return View("\n".join(text))

    def controls(self, s):
        rows = []
        for target, name in [("outreach", "отправки"), ("acquisition", "поиска")]:
            paused = self.store.paused(target, session=s)
            rows.append([button(f"{'▶️ Снять паузу' if paused else '⏸ Пауза'} {name}", f"pause:{target}:{int(not paused)}")])
        text = ("<b>Управление</b>\n\nПаузы сохраняются после перезапуска. Уже выполняющийся запрос или письмо может завершиться. "
                "Приём платежей, сохранение событий и исполнение оплаченного заказа продолжаются.\n\n"
                "Снятие паузы не включает OUTREACH_ENABLED и не отменяет лимиты, проверку получателя или согласование черновика.")
        return View(text, rows + [[button("📊 Обзор", "status")]])

    def leads(self, s, page=0):
        page = max(0, min(page, 2000))
        rows = list(s.exec(select(Lead).order_by(Lead.created_at.desc(), Lead.id).offset(page * 5).limit(6)).all())
        text, keys = [f"<b>Компании · страница {page + 1}</b>"], []
        for lead in rows[:5]:
            text.append(f"• {esc(lead.company, 70)} — {esc(lead.stage, 25)}")
            keys.append([button(str(lead.company)[:45], f"lead:{lead.id}")])
        if not rows:
            text.append("Компаний пока нет. Подключение бота само по себе поиск не запускает.")
        nav = ([button("←", f"leads:{page - 1}")] if page else [])
        if len(rows) > 5 and page < 2000:
            nav.append(button("→", f"leads:{page + 1}"))
        if nav:
            keys.append(nav)
        return View("\n".join(text), keys + MENU)

    def lead(self, s, key):
        lead = s.get(Lead, key)
        if not lead:
            return View("Компания не найдена.")
        lines = [f"<b>{esc(lead.company, 100)}</b>", f"Стадия: {esc(lead.stage, 35)}",
                 f"Оффер: {esc(lead.analysis.get('recommended_offer') or 'ещё не определён', 60)}",
                 f"Проблема: {esc(lead.analysis.get('problem') or 'ещё не исследована', 280)}",
                 f"Оценка: {esc(lead.analysis.get('score', 'нет'), 10)}",
                 f"Контакт проверен: {'да' if lead.contact_verified else 'нет'}",
                 f"Ответ получен: {'да' if lead.replied_at else 'нет'}",
                 f"Запрет контакта: {'да' if lead.suppressed else 'нет'}"]
        keys = []
        if lead.stage not in {"NEW", "INSPECTED", "QUALIFIED", "SKIP"} and self.settings.public_url.startswith("https://"):
            keys.append([{"text": "Приватное превью", "url": f"{self.settings.public_url}/preview/{lead.preview_token}"}])
        elif not self.settings.public_url.startswith("https://"):
            lines.append("Публичный HTTPS-адрес превью пока не настроен.")
        return View("\n".join(lines), keys + [[button("🏢 Компании", "leads:0")]])

    def money(self, s):
        gross = s.exec(select(func.coalesce(func.sum(Order.amount_cents), 0)).where(Order.status.in_(["paid", "delivery_ready"]))).one()
        sums = dict(s.exec(select(MoneyEntry.kind, func.sum(MoneyEntry.amount_cents)).group_by(MoneyEntry.kind)).all())
        costs = sum(v for k, v in sums.items() if k not in {"revenue", "refund", "chargeback"})
        reductions = sums.get("refund", 0) + sums.get("chargeback", 0)
        return View("\n".join(["<b>Деньги · всё время</b>", f"Подтверждённые оплаты, брутто: {euro(gross)}",
                               f"Записанные расходы и налоги: {euro(costs)}", f"Записанные возвраты и споры: {euro(reductions)}", "",
                               "Прибыль не рассчитана: полный учёт всех расходов компании не автоматизирован.",
                               "Записанные нулевые расходы не означают нулевую себестоимость.",
                               "По отраслям подтверждённый contribution доступен только для проверенных зрелых когорт."]))

    def markets(self):
        report = self.portfolio.report()
        lines = ["<b>Отрасли · исследование и результаты</b>"]
        for key, market in list(report["markets"].items())[:6]:
            m = report["performance"].get(key, {})
            contribution = m.get("verified_contribution_cents")
            lines += [f"\n<b>{esc(market['name'], 55)}</b>",
                      f"Гипотеза: {market['hypothesis_score']}; зрелых контактов: {m.get('mature_contacts', 0)}; оплативших: {m.get('paid_leads', 0)}",
                      f"Contribution зрелой когорты: {euro(contribution) if contribution is not None else 'не подтверждён'}"]
        if not report["markets"]:
            lines.append("Свежих подходящих исследований пока нет. Это не доказательство отсутствия спроса.")
        with Session(self.store.engine) as s:
            plan = s.exec(select(AllocationPlan).order_by(AllocationPlan.created_at.desc()).limit(1)).first()
        if plan:
            lines.append(f"\nПоследний план: {esc(plan.mode, 35)}. Доли относятся к новым компаниям.")
            for allocation in plan.allocations[:8]:
                market_id = allocation.get("market_id")
                name = report["markets"].get(market_id, {}).get("name") or market_id or "Резерв"
                lines.append(f"• {esc(name, 45)}: {round(allocation.get('share', 0) * 100)}%")
        lines.append("\nДо победителей — пилот; затем 70% победителям, 30% экспериментам. Срок зрелости — 30 дней.")
        return View("\n".join(lines))

    def issues(self, s):
        lines = ["<b>Нужно решение</b>"]
        jobs = list(s.exec(select(Job).where(Job.status.in_(["blocked", "dead"])).order_by(Job.due_at.desc()).limit(5)).all())
        for job in jobs:
            lines.append(f"• Задание {esc(job.kind, 30)}: {esc(job.status, 20)} / {esc(job.error, 75)}")
        messages = self.count(s, Message, Message.status.in_(["needs_review", "sending"]))
        if messages:
            lines.append(f"• Писем с неопределённым исходом/в отправке: {messages}. Автоповтор отключён.")
        runs = list(s.exec(select(PortfolioRun).where(PortfolioRun.status.in_(["blocked", "failed"])).limit(3)).all())
        for run in runs:
            lines.append(f"• Исследование/поиск: {esc(run.status, 20)} / {esc(run.error or run.result.get('code', ''), 75)}")
        failed = self.count(s, TelegramDelivery, TelegramDelivery.status == "failed")
        if failed:
            lines.append(f"• Не доставлено Telegram-уведомлений: {failed}.")
        if len(lines) == 1:
            lines.append("Зафиксированных проблем этого типа нет.")
        lines.append("\nВходящие письма, публикация сайтов и учёт затрат ещё требуют отдельного подключения.")
        return View("\n".join(lines))

    def report(self, s, *, now=None, weekly=False):
        now = time.time() if now is None else now
        local = datetime.fromtimestamp(now, TZ)
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
        label = f"Сегодня · {local:%d.%m.%Y}, до {local:%H:%M} Berlin"
        if weekly:
            end_date = start - timedelta(days=start.weekday())
            start = end_date - timedelta(days=7)
            end = end_date.timestamp()
            label = f"Прошлая неделя · {start:%d.%m}–{end_date - timedelta(days=1):%d.%m.%Y}"
        since = start.timestamp()
        new = self.count(s, Lead, Lead.created_at >= since, Lead.created_at < end)
        initial = self.count(s, Message, Message.status == "sent", Message.sequence == 0, Message.sent_at >= since, Message.sent_at < end)
        follow = self.count(s, Message, Message.status == "sent", Message.sequence > 0, Message.sent_at >= since, Message.sent_at < end)
        replies = s.exec(select(func.count(func.distinct(Activity.lead_id))).where(
            Activity.kind == "reply_received", Activity.created_at >= since, Activity.created_at < end)).one()
        paid = self.count(s, Activity, Activity.kind == "payment_confirmed", Activity.created_at >= since, Activity.created_at < end)
        return View("\n".join([f"<b>{label}</b>", f"Новых компаний: {new}", f"Первичных писем принято SMTP: {initial}",
                               f"Повторных писем принято SMTP: {follow}", f"Компаний с ответом: {replies}", f"Подтверждений оплаты: {paid}", "",
                               "SMTP-принятие не подтверждает прочтение. Прибыль — после полного учёта расходов."]))

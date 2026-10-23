"""Private control API and capability-scoped previews. Not a public CRM."""

from __future__ import annotations

import secrets
import threading
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from .adapters import OpenAIAnalyzer, PublicInspector, SMTPSender
from .billing import Billing
from .domain import BusinessError
from .models import Activity, AllocationPlan, Campaign, Job, Lead, Market, Message, MoneyEntry, Order, PortfolioRun, uid
from .outreach import Outreach
from .portfolio import Portfolio
from .ports import ProviderFailure
from .research import ResearchReport
from .settings import Settings
from .store import Store
from .workflow import Worker


class LeadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=300)
    website: str = Field(default="", max_length=2000)
    address: str = Field(default="", max_length=1000)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=120)
    verified_contact: bool = False
    campaign_id: str = Field(default="", max_length=64)


class ContactInput(BaseModel):
    email: str = Field(max_length=254)


class ReplyInput(ContactInput):
    interested: bool = False


class CheckoutInput(BaseModel):
    request_key: str = Field(min_length=1, max_length=120)


class DiscoveryInput(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    limit: int = Field(default=20, ge=1, le=20)


class PortfolioBatch(BaseModel):
    limit: int = Field(default=20, ge=1, le=20)


class MoneyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_id: str = Field(min_length=1, max_length=64)
    kind: Literal["acquisition_cost", "delivery_cost", "fee", "tax", "refund", "chargeback"]
    amount_cents: int = Field(ge=0, le=100_000_000, strict=True)
    request_key: str = Field(min_length=1, max_length=160)
    lead_id: str = Field(default="", max_length=64)
    order_id: str = Field(default="", max_length=64)
    detail: str = Field(default="", max_length=1000)


class AccountingConfirmation(BaseModel):
    complete: Literal[True]


class PortfolioRetry(BaseModel):
    key: str = Field(min_length=1, max_length=200)


class PauseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["acquisition", "outreach"]
    paused: bool = Field(strict=True)


def create_app(settings: Settings | None = None, store: Store | None = None, *, worker=None, outreach=None, billing=None, portfolio=None, telegram_runner=None) -> FastAPI:
    settings = settings or Settings()
    store = store or Store(settings.database_url)
    from .telegram import resolve_owner

    settings = resolve_owner(settings, store)
    worker = worker or Worker(store, settings, inspector=PublicInspector(), analyzer=OpenAIAnalyzer(settings.openai_key, settings.model))
    outreach = outreach or Outreach(store, settings, SMTPSender(settings))
    billing = billing or Billing(store, settings)
    portfolio = portfolio or Portfolio(store, settings)
    @asynccontextmanager
    async def lifespan(app):
        poller, thread = telegram_runner, None
        if settings.telegram_enabled and settings.telegram_token and settings.telegram_owner_id:
            if poller is None:
                from .telegram import TelegramConsole, TelegramRunner

                poller = TelegramRunner(TelegramConsole(store, settings, portfolio))
            poller.stop.clear()
            thread = threading.Thread(target=poller.run, name="synairgy-telegram", daemon=True)
            thread.start()
        app.state.telegram_runner = poller
        try:
            yield
        finally:
            if thread:
                poller.stop.set()
                thread.join(timeout=5)

    app = FastAPI(title="SynAirgy Lead Engine", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    def admin(authorization: str = Header(default="")):
        expected = settings.admin_token
        if len(expected) < 32:
            raise HTTPException(503, "Admin access is not configured")
        if not secrets.compare_digest(authorization, f"Bearer {expected}"):
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(BusinessError)
    async def business_error(request, exc):
        return JSONResponse(status_code=409, content={"error": str(exc)})

    @app.exception_handler(ProviderFailure)
    async def provider_error(request, exc):
        return JSONResponse(status_code=503, content={"error": exc.code})

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "2.0.0"}

    @app.get("/api/readiness", dependencies=[Depends(admin)])
    def readiness():
        return {**settings.readiness(), "controls": store.controls()}

    @app.get("/api/controls", dependencies=[Depends(admin)])
    def controls():
        return store.controls()

    @app.post("/api/controls/pause", dependencies=[Depends(admin)])
    def pause(value: PauseInput):
        store.set_paused(value.target, value.paused)
        return store.controls()

    for route, model in [
        ("leads", Lead), ("messages", Message), ("jobs", Job), ("orders", Order), ("activity", Activity),
        ("portfolio/markets", Market), ("portfolio/plans", AllocationPlan), ("portfolio/campaigns", Campaign),
        ("portfolio/money", MoneyEntry), ("portfolio/runs", PortfolioRun),
    ]:

        def make_reader(target):
            def reader(limit: int = Query(100, ge=1, le=500)):
                return [row.model_dump() for row in store.all(target, limit)]

            return reader

        app.add_api_route(f"/api/{route}", make_reader(model), methods=["GET"], dependencies=[Depends(admin)])

    @app.post("/api/leads", dependencies=[Depends(admin)])
    def add_lead(value: LeadInput):
        lead, created = store.add_lead(
            value.model_dump(exclude={"verified_contact", "campaign_id"}),
            verified_contact=value.verified_contact, campaign_id=value.campaign_id,
        )
        return {"id": lead.id, "created": created}

    @app.post("/api/worker/tick", dependencies=[Depends(admin)])
    def tick():
        return {"result": worker.tick()}

    @app.post("/api/discover", dependencies=[Depends(admin)])
    def discover(value: DiscoveryInput):
        from .cli import discovery

        return discovery(settings, store, value.query, value.limit)

    @app.get("/api/portfolio/report", dependencies=[Depends(admin)])
    def portfolio_report():
        return portfolio.report()

    @app.post("/api/portfolio/research", dependencies=[Depends(admin)])
    def market_research():
        return portfolio.research()

    @app.post("/api/portfolio/evidence", dependencies=[Depends(admin)])
    def evidence_import(value: ResearchReport):
        portfolio.ingest(value, f"import:{uid()}")
        return {"status": "imported", "markets": len(value.candidates)}

    @app.post("/api/portfolio/plan", dependencies=[Depends(admin)])
    def allocation_plan():
        return portfolio.plan().model_dump()

    @app.post("/api/portfolio/tick", dependencies=[Depends(admin)])
    def portfolio_tick(value: PortfolioBatch):
        return portfolio.tick(value.limit) if settings.portfolio_enabled else {"status": "disabled"}

    @app.post("/api/portfolio/money", dependencies=[Depends(admin)])
    def money_import(value: MoneyInput):
        values = value.model_dump()
        return portfolio.record_money(**values).model_dump()

    @app.post("/api/portfolio/campaigns/{campaign_id}/verify-costs", dependencies=[Depends(admin)])
    def verify_accounting(campaign_id: str, value: AccountingConfirmation):
        portfolio.verify_costs(campaign_id)
        return {"status": "costs_verified"}

    @app.post("/api/portfolio/retry", dependencies=[Depends(admin)])
    def retry_portfolio(value: PortfolioRetry):
        portfolio.retry(value.key)
        return {"status": "pending"}

    @app.post("/api/outreach/tick", dependencies=[Depends(admin)])
    def send():
        return {"result": outreach.send_one()}

    @app.post("/api/leads/{lead_id}/verify-contact", dependencies=[Depends(admin)])
    def verify_contact(lead_id: str, value: ContactInput):
        outreach.verify_contact(lead_id, value.email)
        return {"ok": True}

    @app.post("/api/messages/{message_id}/approve", dependencies=[Depends(admin)])
    def approve(message_id: str):
        outreach.approve(message_id)
        return {"ok": True}

    @app.post("/api/leads/{lead_id}/reply", dependencies=[Depends(admin)])
    def reply(lead_id: str, value: ReplyInput):
        # Authenticated adapter/owner must verify the original email's sender.
        outreach.record_reply(lead_id, value.email, interested=value.interested)
        return {"ok": True}

    @app.post("/api/suppress", dependencies=[Depends(admin)])
    def suppress(value: ContactInput):
        store.suppress(value.email)
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/retry", dependencies=[Depends(admin)])
    def retry(job_id: str):
        store.retry_job(job_id)
        return {"ok": True}

    @app.post("/api/leads/{lead_id}/checkout", dependencies=[Depends(admin)])
    def checkout(lead_id: str, value: CheckoutInput):
        order = billing.checkout(lead_id, value.request_key)
        return {"order_id": order.id, "url": order.checkout_url}

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request, stripe_signature: str = Header(default="")):
        payload = bytearray()
        async for chunk in request.stream():
            payload.extend(chunk)
            if len(payload) > 1_000_000:
                raise HTTPException(413, "Payload too large")
        try:
            event = billing.verify_event(bytes(payload), stripe_signature)
        except BusinessError:
            raise HTTPException(400, "Invalid webhook") from None
        return {"result": billing.receive(event)}

    def by_token(token: str) -> Lead:
        if len(token) != 64:
            raise HTTPException(404)
        with Session(store.engine) as s:
            lead = s.exec(select(Lead).where(Lead.preview_token == token)).first()
            if not lead:
                raise HTTPException(404)
            return lead

    private_headers = {
        "X-Robots-Tag": "noindex, nofollow",
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }

    @app.get("/preview/{token}")
    def preview(token: str):
        lead = by_token(token)
        path = settings.data_dir / "demos" / f"{lead.id}.html"
        if not path.is_file():
            raise HTTPException(404)
        headers = dict(
            private_headers,
            **{
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
            },
        )
        return FileResponse(path, media_type="text/html", headers=headers)

    @app.get("/delivery/{token}/{order_id}")
    def download(token: str, order_id: str):
        lead = by_token(token)
        order = store.get(Order, order_id)
        if not order or order.lead_id != lead.id or order.status != "delivery_ready":
            raise HTTPException(404)
        path = settings.data_dir / "deliveries" / order.id / "website.zip"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, filename="website.zip", media_type="application/zip", headers=private_headers)

    def message_by_token(token: str):
        if len(token) != 64:
            raise HTTPException(404)
        with Session(store.engine) as s:
            msg = s.exec(select(Message).where(Message.unsubscribe_token == token)).first()
            if not msg:
                raise HTTPException(404)
            return msg

    @app.get("/unsubscribe/{token}")
    def unsubscribe_form(token: str):
        message_by_token(token)
        return HTMLResponse(
            '<!doctype html><html lang="de"><meta charset="utf-8"><title>Keine weiteren Nachrichten</title><form method="post"><button>Keine weiteren Nachrichten senden</button></form></html>',
            headers=private_headers,
        )

    @app.post("/unsubscribe/{token}")
    def unsubscribe(token: str):
        msg = message_by_token(token)
        store.suppress(msg.recipient)
        return HTMLResponse("Keine weiteren Nachrichten. Ihre Auswahl wurde gespeichert.", headers=private_headers)

    @app.get("/payment/received")
    def payment_received():
        return HTMLResponse("Zahlungsstatus wird serverseitig geprüft. Diese Seite bestätigt keine Zahlung.", headers=private_headers)

    @app.get("/payment/cancelled")
    def payment_cancelled():
        return HTMLResponse("Vorgang abgebrochen. Es wurde kein Auftrag durch diese Seite freigeschaltet.", headers=private_headers)

    return app

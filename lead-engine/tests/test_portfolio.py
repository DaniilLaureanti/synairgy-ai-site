from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from synairgy.api import create_app
from synairgy.billing import Billing
from synairgy.domain import BusinessError
from synairgy.models import (
    AllocationPlan,
    Attribution,
    Campaign,
    Lead,
    Market,
    MarketStudy,
    Message,
    MoneyEntry,
    Order,
    SchemaVersion,
)
from synairgy.portfolio import DAY, TZ, Portfolio, PortfolioPolicy, apportion, period
from synairgy.ports import ProviderFailure
from synairgy.research import ResearchReport, WebMarketResearcher
from synairgy.settings import Settings
from synairgy.store import Store


def research_report(now, keys=("dental", "renovation", "automotive"), score=70):
    today = datetime.fromtimestamp(now, TZ).date().isoformat()
    return ResearchReport.model_validate(
        {
            "sources": ["https://statistics.example/sector-report"],
            "candidates": [
                {
                    "key": key,
                    "name": key,
                    "query": f"{key} Hamburg",
                    "evidence": [
                        {
                            "dimension": dimension,
                            "score": score,
                            "confidence": 0.7,
                            "claim": "Synthetic research hypothesis, not market data",
                            "url": "https://statistics.example/sector-report",
                            "as_of": today,
                            "geography": "Hamburg",
                            "sample_size": 20,
                        }
                        for dimension in ["demand", "budget", "digital_gap", "delivery_fit"]
                    ],
                }
                for key in keys
            ],
        }
    )


class Researcher:
    def __init__(self, report):
        self.report, self.calls, self.error = report, 0, None

    def research(self, *args):
        self.calls += 1
        if self.error:
            raise self.error
        return self.report


@pytest.fixture
def portfolio(tmp_path):
    now = time.time()
    settings = Settings(data_dir=tmp_path, admin_token="a" * 40, portfolio_enabled=True)
    store = Store(settings.database_url)
    researcher = Researcher(research_report(now))

    def finder(query, limit):
        key = query.split()[0]
        return [{"name": f"{key} company {i}", "website": f"https://{key}-{i}.example", "address": "Hamburg"} for i in range(limit)]

    service = Portfolio(store, settings, researcher=researcher, finder=finder)
    return SimpleNamespace(now=now, settings=settings, store=store, researcher=researcher, service=service)


def history(p, market_id="dental", contacts=30, paid=2, *, age=40, costs=50000):
    """Synthetic sent cohorts and confirmed payment ingestion, with no live I/O."""
    if not p.store.get(Market, market_id):
        p.service.ingest(research_report(p.now), "synthetic", now=p.now)
    plan_id = f"history-{market_id}"
    campaign = Campaign(plan_id=plan_id, market_id=market_id, lane="explore", created_at=p.now - 60 * DAY)
    with p.store.transaction() as s:
        s.add(AllocationPlan(id=plan_id, mode="pilot", created_at=campaign.created_at))
        s.add(campaign)
    leads, orders = [], []
    for i in range(contacts):
        lead, _ = p.store.add_lead(
            {
                "name": f"{market_id} old {i}",
                "website": f"https://old-{market_id}-{i}.example",
                "email": f"office@old-{market_id}-{i}.example",
            },
            campaign_id=campaign.id,
        )
        with p.store.transaction() as s:
            item = s.get(Lead, lead.id)
            item.stage = "OFFERED"
            s.add(item)
            s.add(
                Message(
                    lead_id=lead.id,
                    recipient=lead.email,
                    subject="Synthetic",
                    body="Synthetic",
                    dedupe_key=f"synthetic:{lead.id}",
                    sequence=0,
                    status="sent",
                    sent_at=p.now - age * DAY,
                )
            )
            if i < paid:
                order = Order(lead_id=lead.id, request_key=f"synthetic:{lead.id}", amount_cents=149000, session_id=f"cs_test_{lead.id}")
                s.add(order)
                orders.append(order)
        leads.append(lead)
    billing = Billing(p.store, p.settings)
    for order in orders:
        event = {
            "id": f"evt_{order.id}",
            "type": "checkout.session.completed",
            "livemode": False,
            "data": {"object": {"id": order.session_id, "currency": "eur", "amount_total": 149000, "payment_status": "paid"}},
        }
        assert billing.receive(event) == "paid"
        assert billing.receive(event) == "duplicate"
    p.service.record_money(campaign.id, "acquisition_cost", costs, f"costs:{campaign.id}")
    return campaign, leads, orders


def test_research_then_diversified_pilot_is_idempotent(portfolio):
    p = portfolio
    first = p.service.tick(20)
    assert first["status"] == "completed" and first["mode"] == "pilot" and first["created"] == 20
    assert len(first["sectors"]) == 3
    assert all(s["lane"] == "explore" for s in first["sectors"])
    assert p.service.tick(20)["cached"] is True
    assert p.researcher.calls == 1
    assert len(p.store.all(Attribution)) == len(p.store.all(Lead)) == 20
    assert sum(s["quota"] for s in first["sectors"]) == 20


def test_winner_gets_70_percent_and_other_markets_keep_30(portfolio):
    p = portfolio
    p.service.ingest(research_report(p.now), "synthetic", now=p.now)
    campaign, _, _ = history(p)
    p.service.verify_costs(campaign.id)
    plan = p.service.plan()
    assert plan.mode == "70_30"
    quotas = apportion(20, plan.allocations)
    assert sum(q for a, q in zip(plan.allocations, quotas) if a["lane"] == "exploit") == 14
    assert sum(q for a, q in zip(plan.allocations, quotas) if a["lane"] == "explore") == 6
    assert {a["market_id"] for a in plan.allocations if a["lane"] == "explore"} == {"renovation", "automotive"}
    assert plan.snapshot["performance"]["dental"]["verified_contribution_cents"] == 248000
    assert p.service.plan().id == plan.id


def test_actual_acquisition_follows_the_winner_and_experiment_quotas(portfolio):
    p = portfolio
    campaign, _, _ = history(p)
    p.service.verify_costs(campaign.id)
    result = p.service.tick(20)
    assert result["mode"] == "70_30" and result["created"] == 20
    assert sum(s["created"] for s in result["sectors"] if s["lane"] == "exploit") == 14
    assert sum(s["created"] for s in result["sectors"] if s["lane"] == "explore") == 6


def test_partial_intake_recovery_does_not_consume_quota_twice(portfolio):
    p = portfolio
    original, calls = p.service.finder, []

    def interrupted(query, limit):
        calls.append(query)
        if len(calls) == 2:
            raise TimeoutError("Synthetic interrupted discovery")
        return original(query, limit)

    p.service.finder = interrupted
    first = p.service.tick(20)
    assert first["status"] == "failed" and 0 < len(p.store.all(Attribution)) < 20
    p.service.retry(first["run_key"])
    p.service.finder = original
    assert p.service.tick(20)["status"] == "completed"
    assert len(p.store.all(Attribution)) == 20
    assert p.researcher.calls == 1


def test_hype_and_revenue_without_accounted_costs_never_make_winner(portfolio):
    p = portfolio
    p.service.ingest(research_report(p.now, score=100), "synthetic", now=p.now)
    history(p, contacts=50, paid=5)
    report = p.service.report()
    assert report["performance"]["dental"]["gross_revenue_cents"] == 745000
    assert report["performance"]["dental"]["verified_contribution_cents"] is None
    assert p.service.plan().mode == "pilot"


@pytest.mark.parametrize("contacts,paid,age,costs", [(10, 2, 40, 1000), (30, 1, 40, 1000), (30, 2, 2, 1000), (30, 2, 40, 400000)])
def test_small_young_or_unprofitable_cohorts_are_not_winners(portfolio, contacts, paid, age, costs):
    p = portfolio
    campaign, _, _ = history(p, contacts=contacts, paid=paid, age=age, costs=costs)
    p.service.verify_costs(campaign.id)
    assert p.service.plan().mode == "pilot"


def test_refunds_costs_and_delayed_entries_reduce_real_result(portfolio):
    p = portfolio
    campaign, leads, orders = history(p)
    p.service.verify_costs(campaign.id)
    assert p.service.report()["performance"]["dental"]["winner_eligible"]
    p.service.record_money(campaign.id, "refund", 149000, "refund-1", lead_id=leads[0].id, order_id=orders[0].id)
    metrics = p.service.report()["performance"]["dental"]
    assert metrics["paid_leads"] == 1 and metrics["recorded_contribution_cents"] == 99000
    assert not metrics["costs_verified"] and not metrics["winner_eligible"]
    p.service.verify_costs(campaign.id)
    assert p.service.report()["performance"]["dental"]["verified_contribution_cents"] == 99000


def test_duplicate_payments_and_rediscovered_companies_do_not_reassign_profit(portfolio):
    p = portfolio
    campaign, leads, orders = history(p)
    assert len(p.store.all(MoneyEntry)) == 3  # two paid orders plus acquisition cost
    p.service.verify_costs(campaign.id)
    new_plan = p.service.plan()
    other_campaign = next(a["campaign_id"] for a in new_plan.allocations if a["market_id"] == "automotive")
    lead, created = p.store.add_lead(leads[0].place, campaign_id=other_campaign)
    assert not created and lead.id == leads[0].id
    assert p.store.get(Attribution, lead.id).campaign_id == campaign.id
    assert p.service.report()["performance"]["automotive"]["gross_revenue_cents"] == 0


def test_money_idempotency_and_cross_market_attribution(portfolio):
    p = portfolio
    campaign, leads, _ = history(p)
    one = p.service.record_money(campaign.id, "fee", 100, "fee-one", lead_id=leads[0].id)
    assert p.service.record_money(campaign.id, "fee", 100, "fee-one", lead_id=leads[0].id).id == one.id
    with pytest.raises(BusinessError, match="Conflicting"):
        p.service.record_money(campaign.id, "fee", 200, "fee-one", lead_id=leads[0].id)
    with pytest.raises(BusinessError, match="Only verified"):
        p.service.record_money(campaign.id, "revenue", 999999, "fake-revenue")
    with pytest.raises(BusinessError, match="attribution"):
        p.service.record_money(campaign.id, "delivery_cost", 100, "bad-cost", lead_id="unrelated")


def test_missing_stale_future_and_unretrieved_evidence_cannot_launch_campaign(portfolio):
    p = portfolio
    with pytest.raises(BusinessError, match="At least two"):
        p.service.plan()
    report = research_report(p.now)
    report.candidates[0].evidence[0].url = "https://invented.example/report"
    with pytest.raises(BusinessError, match="retrieved"):
        p.service.ingest(report, "bad-source")
    assert p.store.all(MarketStudy) == []
    report = research_report(p.now + 2 * DAY)
    with pytest.raises(BusinessError, match="nonfuture"):
        p.service.ingest(report, "future", now=p.now)
    p.service.ingest(research_report(p.now - 100 * DAY), "old", now=p.now)
    with pytest.raises(BusinessError, match="At least two"):
        p.service.plan()


def test_service_complaints_without_website_gap_are_insufficient(portfolio):
    p = portfolio
    report = research_report(p.now)
    for candidate in report.candidates:
        for evidence in candidate.evidence:
            if evidence.dimension == "digital_gap":
                evidence.dimension = "service_gap"
    p.service.ingest(report, "service-only")
    with pytest.raises(BusinessError, match="At least two"):
        p.service.plan()


def test_demand_and_money_without_supported_delivery_fit_do_not_qualify(portfolio):
    p = portfolio
    report = research_report(p.now, score=100)
    for candidate in report.candidates:
        for evidence in candidate.evidence:
            if evidence.dimension == "delivery_fit":
                evidence.score = 0
    p.service.ingest(report, "bad-fit")
    with pytest.raises(BusinessError, match="At least two"):
        p.service.plan()


def test_blocked_research_is_not_retried_until_explicit_recovery(portfolio):
    p = portfolio
    p.researcher.error = ProviderFailure("openai_credit_balance_exhausted", blocked=True)
    first = p.service.research()
    assert first["status"] == "blocked"
    assert p.service.research()["cached"] and p.researcher.calls == 1
    p.researcher.error = None
    p.service.retry(first["run_key"])
    assert p.service.research()["status"] == "completed" and p.researcher.calls == 2


def test_concurrent_research_claim_has_one_owner(portfolio):
    p = portfolio
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: p.service._claim("same-research", "research", p.now), range(3)))
    assert sum(result is not None for result in results) == 1


def test_stale_research_worker_cannot_commit_evidence(portfolio):
    p = portfolio
    first = p.service._claim("fenced-research", "research", p.now)
    second = p.service._claim("fenced-research", "research", p.now + 601)
    with pytest.raises(BusinessError, match="Stale"):
        p.service._finish(first, {"status": "completed"}, apply=lambda s: s.add(Market(id="bad", name="Bad", city="Hamburg", query="Bad")))
    assert p.store.get(Market, "bad") is None
    assert p.service._finish(second, {"status": "completed"})["status"] == "completed"


def test_weekly_snapshot_is_immutable_and_next_period_rebalances(portfolio):
    p = portfolio
    p.service.ingest(research_report(p.now), "synthetic", now=p.now)
    first = p.service.plan()
    campaign, _, _ = history(p)
    p.service.verify_costs(campaign.id)
    assert p.service.plan().mode == first.mode == "pilot"
    second = p.service.plan(p.now + 8 * DAY)
    assert second.mode == "70_30" and second.id != first.id
    assert p.store.get(AllocationPlan, first.id).mode == "pilot"


def test_monthly_periods_and_berlin_week_boundary():
    before = datetime(2026, 10, 25, 23, 30, tzinfo=TZ).timestamp()
    after = datetime(2026, 10, 26, 0, 30, tzinfo=TZ).timestamp()
    assert period(before) != period(after)
    assert period(before, "monthly") == period(after, "monthly") == "2026-10"
    assert PortfolioPolicy(cadence="monthly").cadence == "monthly"


def test_authenticated_api_and_read_only_reporting(portfolio):
    p = portfolio
    app = create_app(p.settings, p.store, portfolio=p.service)
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {p.settings.admin_token}"}
    assert client.get("/api/portfolio/report").status_code == 401
    assert client.get("/api/portfolio/report", headers=headers).status_code == 200
    assert p.store.all(Market) == []  # GET does not initialize or call providers
    assert client.post("/api/portfolio/evidence", json=research_report(p.now).model_dump(mode="json"), headers=headers).status_code == 200
    assert client.post("/api/portfolio/plan", headers=headers).json()["mode"] == "pilot"
    assert client.post("/api/discover", json={"limit": 20}, headers=headers).status_code == 422
    assert client.post("/api/portfolio/tick", json={"limit": 21}, headers=headers).status_code == 422


def test_search_is_forced_bounded_and_extraction_cannot_invent_provenance(portfolio):
    p = portfolio
    reserved, calls = [], []
    report = research_report(p.now)
    search_response = {
        "status": "completed",
        "output": [
            {"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": report.sources[0]}]}},
            {"type": "message", "content": [{"type": "output_text", "text": "Synthetic market research."}]},
        ],
    }
    extraction_response = {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"candidates": [c.model_dump(mode="json") for c in report.candidates]}),
                    }
                ],
            }
        ],
    }

    def post(*args, **kwargs):
        calls.append(kwargs["json"])
        data = search_response if len(calls) == 1 else extraction_response
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: data)

    researcher = WebMarketResearcher(Settings(openai_key="synthetic-test-key"), lambda: reserved.append(1))
    with patch("synairgy.research.requests.post", side_effect=post):
        result = researcher.research("Hamburg", [], "2026-10-21")
    assert len(calls) == len(reserved) == 2
    assert calls[0]["tool_choice"] == "required" and calls[0]["max_tool_calls"] == 6
    assert calls[0]["include"] == ["web_search_call.action.sources"]
    assert result.sources == report.sources and calls[1]["text"]["format"]["strict"]
    p.service.ingest(result, "extraction")


def test_v1_migration_and_sqlite_backup_restore_preserve_leads(tmp_path):
    path = tmp_path / "old.sqlite3"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine, tables=[SchemaVersion.__table__, Lead.__table__])
    with Session(engine) as s:
        s.add(SchemaVersion(version=1))
        s.add(Lead(id="legacy", identity_key="legacy-id", company="Existing customer"))
        s.commit()
    with sqlite3.connect(path) as source, sqlite3.connect(tmp_path / "backup.sqlite3") as target:
        source.backup(target)
    migrated = Store(f"sqlite:///{path}")
    assert migrated.get(Lead, "legacy").company == "Existing customer"
    assert migrated.get(SchemaVersion, 2) is not None and migrated.all(Market) == []
    with sqlite3.connect(tmp_path / "backup.sqlite3") as source, sqlite3.connect(tmp_path / "restored.sqlite3") as target:
        source.backup(target)
    restored = Store(f"sqlite:///{tmp_path / 'restored.sqlite3'}")
    assert restored.get(Lead, "legacy").company == "Existing customer"


def test_unknown_schema_is_rejected_without_creating_new_tables(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unknown.sqlite3'}")
    SchemaVersion.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO schemaversion(version) VALUES(99)"))
    with pytest.raises(RuntimeError, match="Unsupported"):
        Store(str(engine.url))
    assert inspect(engine).get_table_names() == ["schemaversion"]


def test_failed_additive_migration_rolls_back_ddl_and_version(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration-failure.sqlite3'}")
    SchemaVersion.__table__.create(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO schemaversion(version) VALUES(1)"))

    def fail_after_ddl(conn):
        conn.exec_driver_sql("CREATE TABLE partial_migration(id INTEGER)")
        raise RuntimeError("Synthetic migration failure")

    with patch.object(SQLModel.metadata, "create_all", side_effect=fail_after_ddl):
        with pytest.raises(RuntimeError, match="Synthetic"):
            Store(str(engine.url))
    assert inspect(engine).get_table_names() == ["schemaversion"]
    with Session(engine) as s:
        assert s.get(SchemaVersion, 1) is not None

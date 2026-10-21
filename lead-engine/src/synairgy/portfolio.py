"""Market research -> diversified trials -> weekly, profit-based 70/30 allocation.

Capacity is NEW companies admitted to the existing pipeline, not SMTP attempts or
guaranteed spend. Actual sending retains the shared daily cap and contact checks.
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from .domain import BusinessError
from .models import (
    Activity,
    AllocationPlan,
    Attribution,
    Campaign,
    Market,
    MarketStudy,
    Message,
    MoneyEntry,
    Order,
    PortfolioRun,
    uid,
)
from .ports import ProviderFailure
from .research import ResearchReport, WebMarketResearcher, source_url
from .settings import defaults

DAY = 86400
TZ = ZoneInfo("Europe/Berlin")
WEIGHTS = {"demand": 0.25, "trend": 0.10, "budget": 0.25, "digital_gap": 0.20, "service_gap": 0.05, "delivery_fit": 0.15}


class PortfolioPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cadence: str = Field(default="weekly", pattern="^(weekly|monthly)$")
    exploit_share: float = Field(default=0.70, ge=0.5, le=0.9)
    min_mature_contacts: int = Field(default=30, ge=10, le=1000)
    min_paid_leads: int = Field(default=2, ge=2, le=100)
    maturity_days: int = Field(default=30, ge=7, le=180)
    lookback_days: int = Field(default=120, ge=31, le=730)
    evidence_max_age_days: int = Field(default=90, ge=7, le=365)
    max_experiments: int = Field(default=6, ge=2, le=12)
    max_winners: int = Field(default=2, ge=1, le=5)
    min_hypothesis_score: int = Field(default=40, ge=0, le=100)
    min_delivery_fit: int = Field(default=50, ge=0, le=100)


def period(now: float, cadence: str = "weekly") -> str:
    dt = datetime.fromtimestamp(now, TZ)
    return dt.strftime("%Y-%m") if cadence == "monthly" else f"{dt.isocalendar().year}-W{dt.isocalendar().week:02}"


def apportion(total: int, rows: list[dict]) -> list[int]:
    """Largest remainders conserve the complete batch, including reserved slots."""
    raw = [total * row["share"] for row in rows]
    result = [math.floor(x) for x in raw]
    for index in sorted(range(len(rows)), key=lambda i: (-(raw[i] - result[i]), rows[i].get("market_id", "")))[: total - sum(result)]:
        result[index] += 1
    return result


def wilson(successes: int, n: int) -> list[float] | None:
    if not n:
        return None
    p, z = successes / n, 1.96
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [round(max(0, centre - margin), 4), round(min(1, centre + margin), 4)]


class Portfolio:
    def __init__(self, store, settings, *, researcher=None, finder=None, policy=None):
        self.store, self.settings = store, settings
        self.policy = policy or PortfolioPolicy(**defaults().get("portfolio", {}).get("policy", {}))
        if self.policy.lookback_days <= self.policy.maturity_days:
            raise ValueError("Lookback must exceed cohort maturity")
        self.city = defaults()["city"]
        self.researcher = researcher or WebMarketResearcher(settings, self._reserve_ai)
        self.finder = finder

    def _reserve_ai(self):
        with self.store.transaction() as s:
            self.store.reserve(s, "ai_calls", self.settings.max_ai_calls)

    def bootstrap(self):
        # These are an editable research universe, with NO presumed scores.
        with self.store.transaction() as s:
            for key, item in defaults().get("niches", {}).items():
                if not s.get(Market, key):
                    s.add(Market(id=key, name=item.get("name", key), city=self.city, query=item["query"]))

    def _claim(self, key: str, kind: str, now: float) -> PortfolioRun | None:
        with self.store.transaction() as s:
            run = s.get(PortfolioRun, key)
            if run and (run.status not in {"running", "pending"} or run.lease_until > now):
                return None
            if not run:
                run = PortfolioRun(key=key, kind=kind, created_at=now)
            attempts = int(run.result.get("attempts", 0)) + 1
            if attempts > 3:
                run.status, run.error = "failed", "retry_limit"
                s.add(run)
                return None
            run.status, run.lease_token, run.lease_until = "running", uid(), now + 600
            run.result = {"attempts": attempts}
            s.add(run)
            return run

    def _finish(self, run: PortfolioRun, result: dict, status="completed", apply=None):
        with self.store.transaction() as s:
            current = s.get(PortfolioRun, run.key)
            if not current or current.lease_token != run.lease_token or current.status != "running":
                raise BusinessError("Stale portfolio run")
            if apply:
                apply(s)
            current.status, current.lease_until = status, 0
            current.error = result.get("code", "")[:100]
            current.result = {**result, "attempts": current.result["attempts"]}
            s.add(current)
        return {"run_key": run.key, **result}

    def retry(self, key: str):
        with self.store.transaction() as s:
            run = s.get(PortfolioRun, key)
            if not run or run.status not in {"blocked", "failed"}:
                raise BusinessError("Only blocked/failed portfolio runs can be retried")
            run.status, run.lease_until, run.result = "pending", 0, {}
            s.add(run)

    def ingest(self, report: ResearchReport, research_key: str, *, now=None, session=None):
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now, TZ).date()
        keys = [item.key for item in report.candidates]
        if len(keys) != len(set(keys)):
            raise BusinessError("Duplicate market keys in research")
        sources = {url for url in report.sources if source_url(url)}
        for candidate in report.candidates:
            for evidence in candidate.evidence:
                if evidence.url not in sources or evidence.as_of > today:
                    raise BusinessError("Evidence requires a retrieved source and nonfuture data date")

        def save(s):
            for candidate in report.candidates:
                market = s.get(Market, candidate.key)
                if market and market.city != self.city:
                    raise BusinessError("Market scope mismatch")
                if not market:
                    market = Market(id=candidate.key, name=candidate.name, city=self.city, query=candidate.query, created_at=now)
                # Existing campaign queries are frozen in plan snapshots.
                market.name, market.query = candidate.name, candidate.query
                s.add(market)
                s.flush()
                s.add(
                    MarketStudy(
                        market_id=market.id,
                        research_key=research_key,
                        evidence=[e.model_dump(mode="json") for e in candidate.evidence],
                        created_at=now,
                    )
                )

        if session is not None:
            save(session)
        else:
            with self.store.transaction() as s:
                save(s)

    def research(self, now=None) -> dict:
        now = time.time() if now is None else now
        self.bootstrap()
        key = f"research:{self.city}:{period(now)}"
        run = self._claim(key, "research", now)
        if not run:
            existing = self.store.get(PortfolioRun, key)
            return {"status": existing.status, "run_key": key, "cached": True, **existing.result}
        try:
            with Session(self.store.engine) as s:
                markets = [
                    {"key": m.id, "name": m.name, "query": m.query} for m in s.exec(select(Market).where(Market.active.is_(True))).all()
                ]
            report = self.researcher.research(self.city, markets[:30], datetime.fromtimestamp(now, TZ).date().isoformat())
            if not isinstance(report, ResearchReport):
                report = ResearchReport.model_validate(report)
            return self._finish(
                run,
                {"status": "completed", "markets": len(report.candidates), "source_count": len(report.sources)},
                apply=lambda s: self.ingest(report, key, now=now, session=s),
            )
        except ProviderFailure as exc:
            status = "blocked" if exc.blocked else "failed"
            return self._finish(run, {"status": status, "code": exc.code}, status)
        except Exception as exc:
            return self._finish(run, {"status": "failed", "code": type(exc).__name__}, "failed")

    def _priors(self, s, now: float) -> dict:
        today = datetime.fromtimestamp(now, TZ).date()
        latest = {}
        for study in s.exec(select(MarketStudy).order_by(MarketStudy.created_at.desc(), MarketStudy.id)).all():
            latest.setdefault(study.market_id, study)
        result = {}
        for market in s.exec(select(Market).where(Market.active.is_(True))).all():
            study = latest.get(market.id)
            if not study or not 0 <= now - study.created_at <= self.policy.evidence_max_age_days * DAY:
                continue
            by_dimension = {}
            for item in study.evidence:
                dt = datetime.fromisoformat(item["as_of"]).date()
                if 0 <= (today - dt).days <= self.policy.evidence_max_age_days and item["confidence"] >= 0.35:
                    by_dimension.setdefault(item["dimension"], []).append(item)
            if not {"demand", "budget", "digital_gap", "delivery_fit"}.issubset(by_dimension):
                continue
            scores = {
                key: sum(e["score"] * e["confidence"] for e in values) / sum(e["confidence"] for e in values)
                for key, values in by_dimension.items()
            }
            prior = sum(WEIGHTS[k] * v for k, v in scores.items()) / sum(WEIGHTS[k] for k in scores)
            if prior < self.policy.min_hypothesis_score or scores["delivery_fit"] < self.policy.min_delivery_fit:
                continue
            result[market.id] = {
                "market_id": market.id,
                "name": market.name,
                "query": market.query,
                "hypothesis_score": round(prior, 2),
                "dimensions": scores,
                "evidence": study.evidence,
                "study_id": study.id,
                "research_key": study.research_key,
            }
        return result

    def _metrics(self, s, now: float) -> dict:
        campaigns = {c.id: c for c in s.exec(select(Campaign)).all()}
        links = {a.lead_id: a for a in s.exec(select(Attribution)).all()}
        initial = {}
        for msg in s.exec(select(Message).where(Message.sequence == 0, Message.status == "sent")).all():
            if msg.sent_at is not None and now - self.policy.lookback_days * DAY <= msg.sent_at <= now:
                initial.setdefault(msg.lead_id, msg.sent_at)
        mature = {lead for lead, sent in initial.items() if sent <= now - self.policy.maturity_days * DAY}
        money = list(s.exec(select(MoneyEntry).where(MoneyEntry.created_at <= now)).all())
        replies, interested = set(), set()
        for event in s.exec(select(Activity).where(Activity.kind == "reply_received", Activity.created_at <= now)).all():
            replies.add(event.lead_id)
            if event.detail.get("interested"):
                interested.add(event.lead_id)
        metrics = {}
        for market in s.exec(select(Market)).all():
            ids = {c.id for c in campaigns.values() if c.market_id == market.id}
            observed = [e for e in money if e.campaign_id in ids and e.created_at >= now - self.policy.lookback_days * DAY]
            sent = {lead for lead in initial if lead in links and links[lead].campaign_id in ids}
            cohort = sent & mature
            cohort_campaigns = {links[lead].campaign_id for lead in cohort}
            entries = [e for e in money if e.campaign_id in cohort_campaigns and (e.lead_id in cohort or not e.lead_id)]
            revenue = sum(e.amount_cents for e in entries if e.kind == "revenue")
            reductions = sum(e.amount_cents for e in entries if e.kind in {"refund", "chargeback"})
            costs = sum(e.amount_cents for e in entries if e.kind not in {"revenue", "refund", "chargeback"})
            paid = sum(
                sum(
                    e.amount_cents * (1 if e.kind == "revenue" else -1)
                    for e in entries
                    if e.lead_id == lead and e.kind in {"revenue", "refund", "chargeback"}
                )
                > 0
                for lead in cohort
            )
            covered = bool(cohort_campaigns) and all(
                campaigns[c].costs_verified_at
                >= max(
                    [e.created_at for e in money if e.campaign_id == c]
                    + [initial[lead] for lead in sent if links[lead].campaign_id == c]
                    + [campaigns[c].created_at]
                )
                for c in cohort_campaigns
            )
            recorded = revenue - reductions - costs
            # Shrink noisy per-contact returns; this is a ranking rule, not a confidence bound.
            reward = recorded / (len(cohort) + 20) if covered else 0
            metrics[market.id] = {
                "sent_contacts": len(sent),
                "mature_contacts": len(cohort),
                "paid_leads": paid,
                "observed_revenue_cents": sum(e.amount_cents for e in observed if e.kind == "revenue"),
                "observed_refunds_chargebacks_cents": sum(e.amount_cents for e in observed if e.kind in {"refund", "chargeback"}),
                "observed_costs_cents": sum(e.amount_cents for e in observed if e.kind not in {"revenue", "refund", "chargeback"}),
                "replies": len(sent & replies),
                "interested": len(sent & interested),
                "gross_revenue_cents": revenue,
                "refunds_chargebacks_cents": reductions,
                "recorded_costs_cents": costs,
                "recorded_contribution_cents": recorded,
                "costs_verified": covered,
                "verified_contribution_cents": recorded if covered else None,
                "payment_rate": round(paid / len(cohort), 4) if cohort else None,
                "descriptive_payment_rate_interval": wilson(paid, len(cohort)),
                "rank_reward": round(reward, 4),
                "winner_eligible": bool(
                    covered and recorded > 0 and len(cohort) >= self.policy.min_mature_contacts and paid >= self.policy.min_paid_leads
                ),
            }
        return metrics

    def report(self, now=None) -> dict:
        now = time.time() if now is None else now
        with Session(self.store.engine) as s:
            return {
                "as_of": now,
                "currency": "eur",
                "maturity_days": self.policy.maturity_days,
                "lookback_days": self.policy.lookback_days,
                "markets": self._priors(s, now),
                "performance": self._metrics(s, now),
                "forecast_note": "Intervals describe mature contact outcomes; adaptive selection and future order margins add uncertainty.",
            }

    def plan(self, now=None) -> AllocationPlan:
        now = time.time() if now is None else now
        key = f"plan:{self.city}:{period(now, self.policy.cadence)}"
        with self.store.transaction() as s:
            existing = s.get(AllocationPlan, key)
            if existing:
                return existing
            priors, metrics = self._priors(s, now), self._metrics(s, now)
            if len(priors) < 2:
                raise BusinessError(
                    "At least two sectors with fresh source-linked demand, budget, website gap and delivery-fit evidence required"
                )
            winners = sorted((k for k in priors if metrics[k]["winner_eligible"]), key=lambda k: (-metrics[k]["rank_reward"], k))[
                : self.policy.max_winners
            ]
            experiments = sorted(
                (k for k in priors if k not in winners),
                key=lambda k: (metrics[k]["sent_contacts"], -priors[k]["hypothesis_score"], k),
            )[: self.policy.max_experiments]
            allocations = []
            for lane, pool, share in [
                ("exploit", winners, self.policy.exploit_share if winners else 0),
                ("explore", experiments, 1 - self.policy.exploit_share if winners else 1),
            ]:
                if not pool:
                    if share:
                        allocations.append({"market_id": "", "lane": "reserved", "share": share})
                    continue
                weights = []
                for k in pool:
                    if lane == "exploit":
                        weights.append(metrics[k]["rank_reward"])
                    else:
                        penalty = (
                            0.2
                            if (
                                metrics[k]["mature_contacts"] >= self.policy.min_mature_contacts
                                and (
                                    metrics[k]["paid_leads"] == 0
                                    or (metrics[k]["costs_verified"] and metrics[k]["recorded_contribution_cents"] <= 0)
                                )
                            )
                            else 1
                        )
                        weights.append(penalty * (1 + priors[k]["hypothesis_score"] / 100) / math.sqrt(1 + metrics[k]["sent_contacts"]))
                for market_id, weight in zip(pool, weights):
                    campaign = Campaign(plan_id=key, market_id=market_id, lane=lane, created_at=now)
                    s.add(campaign)
                    allocations.append(
                        {
                            "market_id": market_id,
                            "campaign_id": campaign.id,
                            "lane": lane,
                            "share": share * weight / sum(weights),
                            "query": priors[market_id]["query"],
                        }
                    )
            plan = AllocationPlan(
                id=key,
                mode="70_30" if winners else "pilot",
                allocations=allocations,
                created_at=now,
                snapshot={
                    "policy": self.policy.model_dump(),
                    "hypotheses": priors,
                    "performance": metrics,
                    "capacity_unit": "new_companies",
                    "reason": "verified_positive_contribution" if winners else "insufficient_verified_outcomes",
                },
            )
            s.add(plan)
            return plan

    def record_money(self, campaign_id: str, kind: str, amount_cents: int, request_key: str, *, lead_id="", order_id="", detail=""):
        if kind not in {"acquisition_cost", "delivery_cost", "fee", "tax", "refund", "chargeback"}:
            raise BusinessError("Only verified payment ingestion may record revenue")
        if type(amount_cents) is not int or not 0 <= amount_cents <= 100_000_000 or not 1 <= len(request_key) <= 160:
            raise BusinessError("Invalid money amount or idempotency key")
        with self.store.transaction() as s:
            if not s.get(Campaign, campaign_id):
                raise BusinessError("Unknown campaign")
            if lead_id:
                link = s.get(Attribution, lead_id)
                if not link or link.campaign_id != campaign_id:
                    raise BusinessError("Cost/refund attribution mismatch")
            if order_id:
                order = s.get(Order, order_id)
                if not order or order.lead_id != lead_id or order.currency != "eur":
                    raise BusinessError("Money order attribution or currency mismatch")
            if kind in {"refund", "chargeback"} and not lead_id:
                raise BusinessError("A refund or chargeback requires lead attribution")
            old = s.exec(select(MoneyEntry).where(MoneyEntry.request_key == request_key)).first()
            if old:
                if (old.campaign_id, old.kind, old.amount_cents, old.lead_id, old.order_id) != (
                    campaign_id,
                    kind,
                    amount_cents,
                    lead_id,
                    order_id,
                ):
                    raise BusinessError("Conflicting money idempotency key")
                return old
            entry = MoneyEntry(
                campaign_id=campaign_id,
                kind=kind,
                amount_cents=amount_cents,
                request_key=request_key,
                lead_id=lead_id,
                order_id=order_id,
                detail=detail[:1000],
            )
            s.add(entry)
            return entry

    def verify_costs(self, campaign_id: str):
        # Attestation by an authenticated accounting adapter/owner. New sends or
        # financial entries invalidate it automatically in the next report.
        with self.store.transaction() as s:
            campaign = s.get(Campaign, campaign_id)
            if not campaign:
                raise BusinessError("Unknown campaign")
            campaign.costs_verified_at = time.time()
            s.add(campaign)
            s.add(Activity(lead_id="", kind="campaign_costs_verified", detail={"campaign_id": campaign.id}))

    def tick(self, limit=20, now=None) -> dict:
        now = time.time() if now is None else now
        if not 1 <= limit <= 20:
            raise BusinessError("Portfolio batch must contain 1-20 new companies")
        if not self.settings.google_key and not self.finder:
            return {"status": "blocked", "code": "GOOGLE_PLACES_API_KEY_missing"}
        research = self.research(now)
        if research["status"] != "completed":
            return research
        plan = self.plan(now)
        today = datetime.fromtimestamp(now, TZ).date().isoformat()
        run = self._claim(f"acquisition:{self.city}:{today}", "acquisition", now)
        if not run:
            old = self.store.get(PortfolioRun, f"acquisition:{self.city}:{today}")
            return {"status": old.status, "cached": True, **old.result}
        quotas, summaries = apportion(limit, plan.allocations), []
        try:
            for allocation, quota in zip(plan.allocations, quotas):
                if not quota or allocation["lane"] == "reserved":
                    continue
                campaign_id = allocation["campaign_id"]
                # Recover progress after a crash without consuming the quota twice.
                with Session(self.store.engine) as s:
                    links = list(s.exec(select(Attribution).where(Attribution.campaign_id == campaign_id)).all())
                used = sum(datetime.fromtimestamp(link.created_at, TZ).date().isoformat() == today for link in links)
                created = 0
                if used < quota:
                    if self.finder:
                        places = self.finder(allocation["query"], 20)
                    else:
                        from google_places import search_places

                        districts = defaults().get("portfolio", {}).get("districts", [])
                        district = districts[datetime.fromtimestamp(now, TZ).date().toordinal() % len(districts)] if districts else ""
                        places = search_places(self.settings.google_key, f"{allocation['query']} {district}".strip(), page_size=20)
                    for place in places[:20]:
                        if used + created >= quota:
                            break
                        if place.get("business_status") and place["business_status"] != "OPERATIONAL":
                            continue
                        try:
                            _, new = self.store.add_lead(place, campaign_id=campaign_id)
                            created += int(new)
                        except BusinessError:
                            continue
                summaries.append(
                    {
                        "market_id": allocation["market_id"],
                        "lane": allocation["lane"],
                        "quota": quota,
                        "created": created,
                        "already_created": used,
                        "unused": max(0, quota - used - created),
                    }
                )
            return self._finish(
                run,
                {
                    "status": "completed",
                    "plan_id": plan.id,
                    "mode": plan.mode,
                    "capacity": limit,
                    "sectors": summaries,
                    "created": sum(r["created"] for r in summaries),
                },
            )
        except Exception as exc:
            return self._finish(run, {"status": "failed", "code": type(exc).__name__, "sectors": summaries}, "failed")

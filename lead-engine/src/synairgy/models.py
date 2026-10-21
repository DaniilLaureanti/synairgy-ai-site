"""Persistence models. JSON payloads retain evidence, never credentials."""

from __future__ import annotations

import time
from uuid import uuid4

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def uid() -> str:
    return uuid4().hex


class Lead(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    identity_key: str = Field(unique=True, index=True)
    company: str
    stage: str = "NEW"
    place: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    site: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    analysis: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    email: str = ""
    contact_verified: bool = False
    suppressed: bool = False
    replied_at: float | None = None
    preview_token: str = Field(default_factory=lambda: uid() + uid(), unique=True)
    created_at: float = Field(default_factory=time.time)


class Job(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    dedupe_key: str = Field(unique=True, index=True)
    kind: str
    lead_id: str = Field(index=True, foreign_key="lead.id")
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="pending", index=True)
    attempts: int = 0
    due_at: float = Field(default_factory=time.time, index=True)
    lease_until: float = 0
    lease_token: str = ""
    error: str = ""


class Activity(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    lead_id: str = Field(index=True)
    kind: str
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: float = Field(default_factory=time.time)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    dedupe_key: str = Field(unique=True)
    lead_id: str = Field(index=True, foreign_key="lead.id")
    recipient: str
    subject: str
    body: str
    status: str = Field(default="draft", index=True)
    approved: bool = False
    sequence: int = 0
    due_at: float = Field(default_factory=time.time, index=True)
    sent_at: float | None = None
    unsubscribe_token: str = Field(default_factory=lambda: uid() + uid(), unique=True)
    error: str = ""


class Suppression(SQLModel, table=True):
    email: str = Field(primary_key=True)
    reason: str
    created_at: float = Field(default_factory=time.time)


class Order(SQLModel, table=True):
    id: str = Field(default_factory=uid, primary_key=True)
    lead_id: str = Field(index=True, foreign_key="lead.id")
    request_key: str = Field(unique=True, index=True)
    offer: str = "Landing"
    amount_cents: int
    currency: str = "eur"
    status: str = "pending"
    session_id: str | None = Field(default=None, unique=True)
    checkout_url: str = ""
    delivery_path: str = ""
    created_at: float = Field(default_factory=time.time)


class WebhookReceipt(SQLModel, table=True):
    event_id: str = Field(primary_key=True)
    created_at: float = Field(default_factory=time.time)


class DailyCounter(SQLModel, table=True):
    id: str = Field(primary_key=True)
    count: int = 0


class SchemaVersion(SQLModel, table=True):
    version: int = Field(primary_key=True)

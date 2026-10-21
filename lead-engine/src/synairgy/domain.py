"""Pure business rules. No SDK, database, network, or environment access."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from urllib.parse import urlsplit


class Stage(StrEnum):
    NEW = "NEW"
    REVIEW = "REVIEW"
    SKIP = "SKIP"
    QUALIFIED = "QUALIFIED"
    DEMO_READY = "DEMO_READY"
    CONTACTED = "CONTACTED"
    INTERESTED = "INTERESTED"
    OFFERED = "OFFERED"
    PAID = "PAID"
    DELIVERY_READY = "DELIVERY_READY"
    FULFILLED = "FULFILLED"
    LOST = "LOST"
    SUPPRESSED = "SUPPRESSED"


TERMINAL = {Stage.SKIP, Stage.LOST, Stage.SUPPRESSED, Stage.FULFILLED}
TRANSITIONS = {
    Stage.NEW: {Stage.REVIEW, Stage.SKIP, Stage.QUALIFIED},
    Stage.REVIEW: {Stage.QUALIFIED, Stage.SKIP},
    Stage.QUALIFIED: {Stage.DEMO_READY},
    Stage.DEMO_READY: {Stage.CONTACTED, Stage.INTERESTED},
    Stage.CONTACTED: {Stage.INTERESTED},
    Stage.INTERESTED: {Stage.OFFERED},
    Stage.OFFERED: {Stage.PAID},
    Stage.PAID: {Stage.DELIVERY_READY},
    Stage.DELIVERY_READY: {Stage.FULFILLED},
    # A late, signature-verified payment still creates a delivery obligation.
    Stage.LOST: {Stage.PAID},
    Stage.SUPPRESSED: {Stage.PAID},
}


class BusinessError(ValueError):
    """Permanent, safe-to-display business validation error."""


def transition(current: str, target: str) -> None:
    if current == target:
        return
    if target in {Stage.LOST, Stage.SUPPRESSED} and current not in {Stage.PAID, Stage.DELIVERY_READY, Stage.FULFILLED}:
        return
    if target not in TRANSITIONS.get(Stage(current), set()):
        raise BusinessError(f"Invalid transition: {current} -> {target}")


def identity(place: dict) -> str:
    source_id = str(place.get("place_id") or "").strip()
    if source_id:
        return f"place:{source_id}"
    host = (urlsplit(str(place.get("website") or "")).hostname or "").lower().removeprefix("www.")
    name = re.sub(r"\s+", " ", str(place.get("name") or "").strip().lower())
    address = re.sub(r"\s+", " ", str(place.get("address") or "").strip().lower())
    if not name or not (host or address):
        raise BusinessError("Lead requires a name and a website or address")
    return hashlib.sha256(f"{host}|{name}|{address}".encode()).hexdigest()


def email_address(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[^\s<>@,;\r\n]+@[^\s<>@,;\r\n]+\.[^\s<>@,;\r\n]+", value):
        raise BusinessError("Invalid email address")
    return value


def contactable(stage: str, suppressed: bool, has_reply: bool = False) -> bool:
    return not suppressed and not has_reply and stage in {Stage.DEMO_READY, Stage.CONTACTED}


def backoff(attempt: int, jitter: float = 0.0) -> float:
    return min(3600.0, 30.0 * 2 ** min(max(attempt - 1, 0), 8)) + max(0.0, min(jitter, 10.0))


def normalize_analysis(value: dict) -> dict:
    from catalog import OFFER_CATALOG

    score_caps = {"business_quality": 20, "pain_strength": 30, "synairgy_fit": 25, "contactability": 15, "evidence_confidence": 10}

    required = {"problem", "evidence", "recommended_offer", "score_components", "opening", "call_script"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise BusinessError("Invalid analysis contract")
    if value["recommended_offer"] not in OFFER_CATALOG:
        raise BusinessError("Unknown offer")
    if not isinstance(value["evidence"], list) or not all(isinstance(x, str) for x in value["evidence"]):
        raise BusinessError("Invalid evidence")
    components = value["score_components"]
    if not isinstance(components, dict) or any(
        type(components.get(k)) is not int or not 0 <= components[k] <= cap for k, cap in score_caps.items()
    ):
        raise BusinessError("Invalid score components")
    return value

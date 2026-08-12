from __future__ import annotations

import time
from typing import Any
import requests

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"
PRESERVE_PIPELINE_STATUSES = {"CONTACTED", "INTERESTED", "MEETING", "OFFER", "WON", "LOST"}


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _request(method: str, url: str, *, token: str, json: dict | None = None) -> requests.Response:
    response: requests.Response | None = None
    for attempt in range(5):
        response = requests.request(method, url, headers=_headers(token), json=json, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            return response
        time.sleep(min(float(response.headers.get("Retry-After") or "1") + attempt * 0.5, 8))
    assert response is not None
    response.raise_for_status()
    return response


def lead_exists(token: str, data_source_id: str, place_id: str) -> dict[str, Any] | None:
    if not place_id:
        return None
    data = _request(
        "POST",
        f"{NOTION_BASE}/data_sources/{data_source_id}/query",
        token=token,
        json={
            "page_size": 1,
            "filter": {"property": "Place ID", "rich_text": {"equals": place_id}},
        },
    ).json()
    results = data.get("results") or []
    return results[0] if results else None


def _rich_text(value: str) -> dict:
    return {"rich_text": [{"type": "text", "text": {"content": (value or "")[:2000]}}]}


def _title(value: str) -> dict:
    return {"title": [{"type": "text", "text": {"content": (value or "Unnamed lead")[:2000]}}]}


def _current_status(existing: dict[str, Any]) -> str:
    try:
        return existing["properties"]["Status"]["select"]["name"] or ""
    except (KeyError, TypeError):
        return ""


def _build_properties(
    place: dict[str, Any],
    site: dict[str, Any],
    analysis: dict[str, Any],
    *,
    category: str,
    fingerprint: str,
    status: str,
    is_new: bool,
) -> dict[str, Any]:
    props: dict[str, Any] = {
        "Company": _title(place.get("name") or ""),
        "Status": {"select": {"name": status}},
        "Score": {"number": analysis["score"]},
        "Category": _rich_text(category),
        "Offer": {"select": {"name": analysis["recommended_offer"]}},
        "Price €": {"number": analysis["price_eur"]},
        "Address": _rich_text(place.get("address") or ""),
        "Problem": _rich_text(analysis.get("problem") or ""),
        "Evidence": _rich_text(" • ".join(analysis.get("evidence") or [])),
        "Why Now": _rich_text(analysis.get("why_now") or ""),
        "Opening": _rich_text(analysis.get("opening") or ""),
        "Call Script": _rich_text(analysis.get("call_script") or ""),
        "Contact Channel": {"select": {"name": analysis.get("recommended_channel") or "Other"}},
        "Place ID": _rich_text(place.get("place_id") or ""),
        "Fingerprint": _rich_text(fingerprint),
        "Legal Relevance": _rich_text(analysis.get("legal_relevance") or ""),
    }
    if is_new:
        props["Approved"] = {"checkbox": False}
        props["Do Not Contact"] = {"checkbox": False}
        props["Contact Attempts"] = {"number": 0}
        props["Source"] = {"select": {"name": "Google Places"}}

    if place.get("rating") is not None:
        props["Rating"] = {"number": place.get("rating")}
    if place.get("reviews") is not None:
        props["Reviews"] = {"number": place.get("reviews")}

    for name, value in {
        "Website": place.get("website") or site.get("final_url"),
        "Instagram": site.get("instagram"),
        "Google Maps": place.get("google_maps"),
    }.items():
        if value:
            props[name] = {"url": value}

    phone = place.get("phone") or site.get("phone")
    if phone:
        props["Phone"] = {"phone_number": phone}
    return props


def create_lead(
    token: str,
    data_source_id: str,
    place: dict[str, Any],
    site: dict[str, Any],
    analysis: dict[str, Any],
    *,
    category: str,
    fingerprint: str,
    status: str,
) -> dict[str, Any]:
    props = _build_properties(
        place,
        site,
        analysis,
        category=category,
        fingerprint=fingerprint,
        status=status,
        is_new=True,
    )
    return _request(
        "POST",
        f"{NOTION_BASE}/pages",
        token=token,
        json={"parent": {"data_source_id": data_source_id}, "properties": props},
    ).json()


def update_lead(
    token: str,
    existing: dict[str, Any],
    place: dict[str, Any],
    site: dict[str, Any],
    analysis: dict[str, Any],
    *,
    category: str,
    fingerprint: str,
    suggested_status: str,
) -> dict[str, Any]:
    page_id = existing.get("id")
    if not page_id:
        raise RuntimeError("Existing Notion lead is missing page id")
    current = _current_status(existing)
    status = current if current in PRESERVE_PIPELINE_STATUSES else suggested_status
    props = _build_properties(
        place,
        site,
        analysis,
        category=category,
        fingerprint=fingerprint,
        status=status,
        is_new=False,
    )
    return _request(
        "PATCH",
        f"{NOTION_BASE}/pages/{page_id}",
        token=token,
        json={"properties": props},
    ).json()

from __future__ import annotations

import html
import os
import sys
from typing import Any
import requests

NOTION_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2026-03-11"


def _notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _plain_text(prop: dict[str, Any]) -> str:
    values = prop.get("title") or prop.get("rich_text") or []
    return "".join(item.get("plain_text") or "" for item in values)


def _select(prop: dict[str, Any]) -> str:
    value = prop.get("select") or {}
    return value.get("name") or ""


def _phone(prop: dict[str, Any]) -> str:
    return prop.get("phone_number") or ""


def _date(prop: dict[str, Any]) -> str:
    value = prop.get("date") or {}
    return value.get("start") or ""


def query_due_followups(token: str, data_source_id: str, limit: int = 50) -> list[dict[str, Any]]:
    payload = {
        "page_size": min(max(limit, 1), 100),
        "filter": {
            "and": [
                {"property": "Next Follow-up", "date": {"on_or_before": "today"}},
                {"property": "Do Not Contact", "checkbox": {"equals": False}},
                {"property": "Status", "select": {"does_not_equal": "WON"}},
                {"property": "Status", "select": {"does_not_equal": "LOST"}},
                {"property": "Status", "select": {"does_not_equal": "SKIP"}},
            ]
        },
        "sorts": [{"property": "Next Follow-up", "direction": "ascending"}],
    }
    response = requests.post(
        f"{NOTION_BASE}/data_sources/{data_source_id}/query",
        headers=_notion_headers(token),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("results") or []


def normalize_page(page: dict[str, Any]) -> dict[str, str]:
    props = page.get("properties") or {}
    return {
        "company": _plain_text(props.get("Company") or {}) or "Unnamed lead",
        "status": _select(props.get("Status") or {}),
        "offer": _select(props.get("Offer") or {}),
        "phone": _phone(props.get("Phone") or {}),
        "due": _date(props.get("Next Follow-up") or {}),
        "url": page.get("url") or "",
    }


def send_telegram(token: str, chat_id: str, leads: list[dict[str, str]]) -> None:
    if not leads:
        return
    header = f"⏰ <b>SynAirgy follow-ups: {len(leads)}</b>\n"
    chunks: list[str] = []
    current = header
    for i, lead in enumerate(leads, start=1):
        line = (
            f"\n<b>{i}. {html.escape(lead['company'])}</b>"
            f"\n{html.escape(lead['status'])} · {html.escape(lead['offer'])}"
            f"\n📅 {html.escape(lead['due'])}"
        )
        if lead.get("phone"):
            line += f" · ☎️ {html.escape(lead['phone'])}"
        if lead.get("url"):
            line += f"\n<a href=\"{html.escape(lead['url'], quote=True)}\">Открыть в Notion</a>"
        line += "\n"
        if len(current) + len(line) > 3600:
            chunks.append(current)
            current = header + line
        else:
            current += line
    if current.strip():
        chunks.append(current)

    for chunk in chunks:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        response.raise_for_status()


def main() -> int:
    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not (notion_token and data_source_id and telegram_token and chat_id):
        print("Follow-up reminders disabled: Notion/Telegram secrets are incomplete.")
        return 0

    pages = query_due_followups(notion_token, data_source_id)
    leads = [normalize_page(page) for page in pages]
    send_telegram(telegram_token, chat_id, leads)
    print(f"Follow-up reminders: {len(leads)} due lead(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Follow-up reminder failed: {exc}", file=sys.stderr)
        raise

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

from ai_analyzer import analyze_lead
from google_places import search_places
from notion_crm import create_lead, lead_exists, update_lead
from scraper import inspect_site
from telegram_notify import notify_lead, notify_summary

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def fingerprint(place: dict, site: dict) -> str:
    source = "|".join([
        place.get("place_id") or "",
        place.get("website") or "",
        place.get("phone") or "",
        site.get("title") or "",
        site.get("meta_description") or "",
        (site.get("text") or "")[:2500],
    ])
    return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()[:32]


def main() -> int:
    config = load_config()
    google_key = require_env("GOOGLE_PLACES_API_KEY")
    openai_key = require_env("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini").strip() or "gpt-5-mini"
    dry_run = env_bool("DRY_RUN", False)
    refresh = env_bool("REFRESH_EXISTING", False)

    notion_token = os.getenv("NOTION_TOKEN", "").strip()
    notion_ds = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    if not dry_run and (not notion_token or not notion_ds):
        raise RuntimeError("NOTION_TOKEN and NOTION_DATA_SOURCE_ID are required unless DRY_RUN=1")

    niche = config["active_niche"]
    query = os.getenv("LEAD_QUERY", "").strip() or config["niches"][niche]["query"]
    limit = os.getenv("LEAD_LIMIT", "").strip()
    page_size = max(1, min(int(limit) if limit else int(config["page_size"]), 20))
    threshold = int(config["lead_threshold"])
    review_threshold = int(config["review_threshold"])

    places = search_places(
        google_key,
        query,
        page_size=page_size,
        max_pages=int(config["max_pages"]),
        language_code=config["language_code"],
        region_code=config["region_code"],
        delay_seconds=float(config["request_delay_seconds"]),
    )

    output = []
    new_count = 0
    updated_count = 0
    high_count = 0
    duplicate_count = 0
    tg = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    for index, place in enumerate(places, start=1):
        if place.get("business_status") and place["business_status"] != "OPERATIONAL":
            continue

        existing = lead_exists(notion_token, notion_ds, place.get("place_id") or "") if notion_token and notion_ds else None
        if existing and not refresh:
            duplicate_count += 1
            continue

        site = inspect_site(
            place.get("website") or "",
            max_chars=int(config["website_max_chars"]),
            timeout=int(config["website_timeout_seconds"]),
        )
        place["phone"] = place.get("phone") or site.get("phone") or ""
        analysis = analyze_lead(openai_key, model, place, site)
        status = "READY" if analysis["score"] >= threshold else ("REVIEW" if analysis["score"] >= review_threshold else "SKIP")
        fp = fingerprint(place, site)

        output.append({
            "place": place,
            "site": {k: site.get(k) for k in ["reachable", "title", "meta_description", "instagram", "phone", "signals", "error"]},
            "analysis": analysis,
            "status": status,
            "fingerprint": fp,
        })

        notion_page = {}
        if not dry_run:
            if existing:
                notion_page = update_lead(
                    notion_token,
                    existing,
                    place,
                    site,
                    analysis,
                    category=niche,
                    fingerprint=fp,
                    suggested_status=status,
                )
                updated_count += 1
            else:
                notion_page = create_lead(
                    notion_token,
                    notion_ds,
                    place,
                    site,
                    analysis,
                    category=niche,
                    fingerprint=fp,
                    status=status,
                )
                new_count += 1

        if analysis["score"] >= threshold:
            high_count += 1
            if tg and chat:
                notify_lead(tg, chat, place, analysis, notion_page.get("url", "") if notion_page else "")

        if index < len(places):
            time.sleep(float(config["request_delay_seconds"]))

    out = Path(os.getenv("OUTPUT_PATH", ROOT / "out" / "results.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "query": query,
        "dry_run": dry_run,
        "refresh_existing": refresh,
        "discovered": len(places),
        "new_leads": new_count,
        "updated_leads": updated_count,
        "high_score": high_count,
        "skipped_duplicates": duplicate_count,
        "results": output,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if tg and chat:
        notify_summary(
            tg,
            chat,
            query=query,
            discovered=len(places),
            new_leads=new_count,
            updated_leads=updated_count,
            high_score=high_count,
            skipped_duplicates=duplicate_count,
        )

    print(json.dumps({
        "query": query,
        "discovered": len(places),
        "new_leads": new_count,
        "updated_leads": updated_count,
        "high_score": high_count,
        "duplicates": duplicate_count,
        "dry_run": dry_run,
        "output": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Lead Engine failed: {exc}", file=sys.stderr)
        raise

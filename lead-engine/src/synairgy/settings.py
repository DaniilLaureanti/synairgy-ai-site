from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]


def defaults() -> dict:
    return json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(int(default))).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR") or ROOT / "data").resolve())
    openai_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""), repr=False)
    model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5-mini"))
    lead_threshold: int = field(default_factory=lambda: int(defaults()["lead_threshold"]))
    review_threshold: int = field(default_factory=lambda: int(defaults()["review_threshold"]))
    google_key: str = field(default_factory=lambda: os.getenv("GOOGLE_PLACES_API_KEY", ""), repr=False)
    admin_token: str = field(default_factory=lambda: os.getenv("ADMIN_TOKEN", ""), repr=False)
    public_url: str = field(default_factory=lambda: (
        os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "http://127.0.0.1:8000"
    ).rstrip("/"))
    outreach_enabled: bool = field(default_factory=lambda: flag("OUTREACH_ENABLED"))
    auto_approve: bool = field(default_factory=lambda: flag("AUTO_APPROVE_OUTREACH"))
    daily_limit: int = field(default_factory=lambda: int(os.getenv("DAILY_SEND_LIMIT", "20")))
    max_ai_calls: int = field(default_factory=lambda: int(os.getenv("DAILY_AI_CALL_LIMIT", "30")))
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USERNAME", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""), repr=False)
    sender_email: str = field(default_factory=lambda: os.getenv("SENDER_EMAIL", ""))
    sender_address: str = field(default_factory=lambda: os.getenv("SENDER_POSTAL_ADDRESS", ""))
    stripe_key: str = field(default_factory=lambda: os.getenv("STRIPE_API_KEY", ""), repr=False)
    stripe_webhook_secret: str = field(default_factory=lambda: os.getenv("STRIPE_WEBHOOK_SECRET", ""), repr=False)
    stripe_live: bool = field(default_factory=lambda: flag("STRIPE_LIVE_MODE"))
    portfolio_enabled: bool = field(default_factory=lambda: flag("PORTFOLIO_ENABLED", defaults().get("portfolio", {}).get("enabled", False)))
    telegram_enabled: bool = field(default_factory=lambda: flag("TELEGRAM_ENABLED"))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""), repr=False)
    telegram_owner_id: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_OWNER_ID") or "0"))
    telegram_report_hour: int = field(default_factory=lambda: int(os.getenv("TELEGRAM_REPORT_HOUR") or "19"))

    def __post_init__(self):
        if not 1 <= self.daily_limit <= 500 or not 1 <= self.max_ai_calls <= 1000:
            raise ValueError("Daily limits outside supported range")
        if not 0 <= self.review_threshold <= self.lead_threshold <= 100:
            raise ValueError("Invalid qualification thresholds")
        if not 0 <= self.telegram_report_hour <= 23 or not 0 <= self.telegram_owner_id < 2**52:
            raise ValueError("Invalid Telegram owner/report settings")
        if self.telegram_token and not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", self.telegram_token):
            raise ValueError("Invalid Telegram token format")
        url = urlsplit(self.public_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Invalid PUBLIC_BASE_URL")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'engine.sqlite3'}"

    def readiness(self) -> dict:
        return {
            "discovery": {
                "ready": bool(self.google_key and self.openai_key),
                "missing": [k for k, v in {"GOOGLE_PLACES_API_KEY": self.google_key, "OPENAI_API_KEY": self.openai_key}.items() if not v],
            },
            "outreach": {
                "enabled": self.outreach_enabled,
                "ready": bool(self.smtp_host and self.sender_email and self.sender_address and self.public_url.startswith("https://")),
            },
            "billing": {"ready": bool(self.stripe_key and self.stripe_webhook_secret), "live": self.stripe_live},
            "admin": {"ready": len(self.admin_token) >= 32},
            "portfolio": {"enabled": self.portfolio_enabled, "research_configured": bool(self.openai_key), "capacity_unit": "new_companies"},
            "telegram": {
                "enabled": self.telegram_enabled,
                "configured": bool(self.telegram_token and self.telegram_owner_id),
                "transport": "long_polling",
            },
        }

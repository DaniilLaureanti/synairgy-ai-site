from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

import requests

from .ports import ProviderFailure


class PublicInspector:
    def inspect(self, place: dict) -> dict:
        from scraper import inspect_site

        return inspect_site(place.get("website", ""))


class OpenAIAnalyzer:
    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def analyze(self, place: dict, site: dict) -> dict:
        from ai_analyzer import analyze_lead

        if not self.api_key:
            raise ProviderFailure("openai_key_missing", blocked=True)
        try:
            return analyze_lead(self.api_key, self.model, place, site)
        except requests.HTTPError as exc:
            response = exc.response
            status = response.status_code if response is not None else 0
            code = ""
            try:
                code = response.json().get("error", {}).get("code", "")
            except Exception:
                pass
            if code in {"credit_balance_exhausted", "insufficient_quota"}:
                raise ProviderFailure("openai_credit_balance_exhausted", blocked=True) from None
            raise ProviderFailure(
                f"openai_http_{status}", blocked=status in {401, 403}, permanent=400 <= status < 500 and status not in {408, 429}
            ) from None
        except requests.RequestException:
            raise ProviderFailure("openai_transport_error") from None


class SMTPSender:
    def __init__(self, settings):
        self.settings = settings

    def send(self, *, recipient: str, subject: str, body: str, message_id: str, unsubscribe_url: str) -> str:
        from .domain import email_address

        sender = email_address(self.settings.sender_email)
        recipient = email_address(recipient)
        if any(c in subject for c in "\r\n"):
            raise ProviderFailure("invalid_subject", permanent=True)
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, recipient, subject
        msg["Message-ID"] = f"<{message_id}@{sender.split('@')[1]}>"
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.set_content(body)
        # No send retries: a timeout after SMTP DATA can mean accepted.
        context = ssl.create_default_context()
        if self.settings.smtp_port == 465:
            smtp = smtplib.SMTP_SSL(self.settings.smtp_host, 465, timeout=20, context=context)
        else:
            smtp = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20)
        with smtp:
            if self.settings.smtp_port != 465:
                smtp.starttls(context=context)
                smtp.ehlo()
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            if smtp.send_message(msg):
                raise ProviderFailure("smtp_recipient_rejected", permanent=True)
        return str(msg["Message-ID"])

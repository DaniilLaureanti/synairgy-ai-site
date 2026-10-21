"""Deterministic, escaped static concepts; never executable model-generated code."""

from __future__ import annotations

import html
import os
import re
import tempfile
from pathlib import Path


def render(lead, *, concept: bool = True) -> str:
    company = html.escape(lead.company)
    phone = re.sub(r"[^+0-9]", "", str(lead.place.get("phone") or lead.site.get("phone") or ""))
    cta = (
        f'<a class="cta" href="tel:{phone}">Kontakt aufnehmen</a>'
        if phone
        else '<p class="cta">Kontaktinformationen nach Freigabe ergänzen</p>'
    )
    notice = (
        "Privates Konzept · keine offizielle Unternehmenswebsite"
        if concept
        else "Website-Paket · Veröffentlichung und Domain-Anbindung noch ausstehend"
    )
    description = html.escape(str(lead.site.get("meta_description") or lead.site.get("title") or lead.company))[:800]
    address = html.escape(str(lead.place.get("address") or ""))
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>{company} — Website-Konzept</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f2eb;color:#182620;font:17px/1.6 system-ui,sans-serif}}header,main,footer{{max-width:1080px;margin:auto;padding:24px}}header{{display:flex;gap:16px;justify-content:space-between;flex-wrap:wrap}}small{{font-size:13px}}section{{padding:54px 0;max-width:760px}}h1{{font-size:clamp(36px,8vw,80px);line-height:1.1;letter-spacing:-.04em}}h2{{font-size:30px}}.cta{{display:inline-block;padding:16px 24px;background:#223d30;color:white;text-decoration:none;border-radius:6px}}footer{{border-top:1px solid #b6beb4}}p{{overflow-wrap:anywhere}}@media(max-width:500px){{section{{padding:28px 0}}}}
</style></head><body><header><strong>{company}</strong><small>{notice}</small></header><main><section><p>Persönlich. Direkt. Vor Ort.</p><h1>{company}</h1><p>{description}</p>{cta}</section><section><h2>Ein klarer Weg zur Anfrage</h2><p>Leistungen, echte Referenzen und freigegebene Bilder werden im Onboarding gemeinsam festgelegt. Keine erfundenen Bewertungen oder Leistungsversprechen.</p></section><section><h2>Kontakt</h2><p>{address}</p>{cta}</section></main><footer><small>Konzept von SynAirgy. Impressum und Datenschutzhinweise müssen vor öffentlicher Freigabe ergänzt werden.</small></footer></body></html>"""


def save_atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="concept-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

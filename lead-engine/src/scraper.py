from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from synairgy.safe_http import USER_AGENT, get_public

BOOKING_HINTS = ("termin", "booking", "reserve", "reservation", "appointment", "calendly", "treatwell", "planity", "fresha", "shore.com", "opentable", "quandoo")
VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com", "tiktok.com")


def _valid_public_url(url: str) -> bool:
    try:
        p = urlsplit(url)
        return p.scheme in {"http", "https"} and bool(p.hostname) and not (p.username or p.password)
    except ValueError:
        return False


def _robots_allows(url: str) -> bool:
    parsed = urlsplit(url)
    try:
        status, _, raw, final = get_public(f"{parsed.scheme}://{parsed.netloc}/robots.txt", 5)
        if status in {404, 410}:
            return True
        if status >= 400:
            return False
        robots = RobotFileParser()
        robots.set_url(final)
        robots.parse(raw.decode("utf-8", errors="replace").splitlines())
        return robots.can_fetch(USER_AGENT, url)
    except Exception:
        return False


def inspect_site(url: str, *, max_chars: int = 12000, timeout: int = 10) -> dict:
    result = {"reachable": False, "status_code": None, "title": "", "meta_description": "", "text": "", "instagram": "", "phone": "", "email": "", "signals": {}, "error": ""}
    if not url or not _valid_public_url(url):
        result["error"] = "missing_or_invalid_url"
        return result
    if not _robots_allows(url):
        result["error"] = "robots_disallow_or_unavailable"
        return result
    try:
        status, content_type, raw, final = get_public(url, timeout)
        result["status_code"] = status
        if status >= 400 or "html" not in content_type.lower():
            result["error"] = "http_error_or_non_html"
            return result
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        links = [urljoin(final, a["href"].strip()) for a in soup.find_all("a", href=True)]
        instagram = next((h for h in links if (urlsplit(h).hostname or "").lower() in {"instagram.com", "www.instagram.com"}), "")
        phone = next((h[4:] for h in links if h.lower().startswith("tel:")), "")
        email = next((h[7:].split("?")[0] for h in links if h.lower().startswith("mailto:")), "")
        meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
        iframes = [i.get("src", "").lower() for i in soup.find_all("iframe")]
        result.update({
            "reachable": True, "final_url": final,
            "title": soup.title.get_text(" ", strip=True)[:300] if soup.title else "",
            "meta_description": str(meta.get("content", ""))[:600] if meta else "",
            "text": re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:max_chars],
            "instagram": instagram[:1000], "phone": phone[:120], "email": email[:254],
            "signals": {"has_instagram_link": bool(instagram), "has_contact_form": bool(soup.find("form")),
                        "has_online_booking": any(h in " ".join(links).lower() for h in BOOKING_HINTS),
                        "has_whatsapp": any("wa.me/" in h or "whatsapp" in h.lower() for h in links),
                        "has_video": bool(soup.find("video")) or any(h in src for h in VIDEO_HOSTS for src in iframes),
                        "image_count": len(soup.find_all("img")), "video_count": len(soup.find_all("video"))},
        })
    except Exception as exc:
        result["error"] = f"inspection_failed:{type(exc).__name__}"
    return result

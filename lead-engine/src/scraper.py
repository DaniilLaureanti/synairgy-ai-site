from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup

USER_AGENT="SynAirgyLeadEngine/0.1 (+https://synairgy.ai)"
BOOKING_HINTS=("termin","booking","book","reserve","reservation","appointment","calendly","treatwell","planity","fresha","shore.com","opentable","quandoo")
VIDEO_HOSTS=("youtube.com","youtu.be","vimeo.com","tiktok.com")

def _valid_public_url(url:str)->bool:
    try:
        parsed=urlparse(url); return parsed.scheme in {"http","https"} and bool(parsed.netloc)
    except Exception: return False

def _robots_allows(url:str)->bool:
    try:
        parsed=urlparse(url); robots_url=f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response=requests.get(robots_url,headers={"User-Agent":USER_AGENT},timeout=5)
        if response.status_code>=400: return True
        rp=RobotFileParser(); rp.set_url(robots_url); rp.parse(response.text.splitlines()); return rp.can_fetch(USER_AGENT,url)
    except Exception:
        return True

def inspect_site(url:str,*,max_chars:int=12000,timeout:int=10)->dict:
    empty={"reachable":False,"status_code":None,"title":"","meta_description":"","text":"","instagram":"","phone":"","email":"","signals":{"has_instagram_link":False,"has_contact_form":False,"has_online_booking":False,"has_whatsapp":False,"has_video":False,"image_count":0,"video_count":0},"error":""}
    if not url or not _valid_public_url(url): empty["error"]="missing_or_invalid_url"; return empty
    if not _robots_allows(url): empty["error"]="robots_disallow"; return empty
    try:
        response=requests.get(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html,application/xhtml+xml"},timeout=timeout,allow_redirects=True,stream=True); empty["status_code"]=response.status_code; response.raise_for_status()
        if "html" not in (response.headers.get("Content-Type") or "").lower(): empty["error"]="non_html"; return empty
        raw=response.content[:2_000_000]; soup=BeautifulSoup(raw,"html.parser")
        for tag in soup(["script","style","noscript","svg"]): tag.decompose()
        title=soup.title.get_text(" ",strip=True) if soup.title else ""
        meta=soup.find("meta",attrs={"name":re.compile("^description$",re.I)}); description=meta.get("content","").strip() if meta else ""
        hrefs=[]
        for a in soup.find_all("a",href=True): hrefs.append(urljoin(response.url,a.get("href","").strip()))
        instagram=next((h for h in hrefs if "instagram.com" in h.lower()),"")
        tel=next((h[4:] for h in hrefs if h.lower().startswith("tel:")),"")
        email=next((h[7:].split("?")[0] for h in hrefs if h.lower().startswith("mailto:")),"")
        lower_links=" ".join(hrefs).lower(); has_contact_form=bool(soup.find_all("form")); has_online_booking=any(h in lower_links for h in BOOKING_HINTS); has_whatsapp="wa.me/" in lower_links or "whatsapp" in lower_links
        iframe_srcs=[(i.get("src") or "").lower() for i in soup.find_all("iframe") if i.get("src")]; video_count=len(soup.find_all("video")); has_video=video_count>0 or any(host in src for src in iframe_srcs for host in VIDEO_HOSTS); image_count=len(soup.find_all("img"))
        text=re.sub(r"\s+"," "," ".join(soup.stripped_strings)).strip()[:max_chars]
        return {"reachable":True,"status_code":response.status_code,"final_url":response.url,"title":title[:300],"meta_description":description[:600],"text":text,"instagram":instagram[:1000],"phone":tel[:120],"email":email[:320],"signals":{"has_instagram_link":bool(instagram),"has_contact_form":has_contact_form,"has_online_booking":has_online_booking,"has_whatsapp":has_whatsapp,"has_video":has_video,"image_count":image_count,"video_count":video_count},"error":""}
    except requests.RequestException as exc: empty["error"]=f"http_error:{type(exc).__name__}"; return empty
    except Exception as exc: empty["error"]=f"parse_error:{type(exc).__name__}"; return empty

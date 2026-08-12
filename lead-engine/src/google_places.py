from __future__ import annotations

import time
from typing import Any
import requests

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(["places.id","places.displayName","places.formattedAddress","places.rating","places.userRatingCount","places.websiteUri","places.googleMapsUri","places.businessStatus","places.types","nextPageToken"])

def search_places(api_key: str, text_query: str, *, page_size: int = 20, max_pages: int = 1, language_code: str = "de", region_code: str = "DE", delay_seconds: float = 0.35) -> list[dict[str, Any]]:
    page_size = max(1, min(int(page_size), 20)); max_pages = max(1, min(int(max_pages), 3))
    headers = {"Content-Type":"application/json","X-Goog-Api-Key":api_key,"X-Goog-FieldMask":FIELD_MASK}
    body: dict[str, Any] = {"textQuery":text_query,"pageSize":page_size,"languageCode":language_code,"regionCode":region_code}
    all_places=[]; page_token=None
    for page in range(max_pages):
        payload=dict(body)
        if page_token: payload["pageToken"]=page_token
        response=requests.post(ENDPOINT,headers=headers,json=payload,timeout=20); response.raise_for_status(); data=response.json()
        for place in data.get("places",[]):
            name_obj=place.get("displayName") or {}
            all_places.append({"place_id":place.get("id") or "","name":name_obj.get("text") or "","address":place.get("formattedAddress") or "","rating":place.get("rating"),"reviews":place.get("userRatingCount"),"website":place.get("websiteUri") or "","google_maps":place.get("googleMapsUri") or "","business_status":place.get("businessStatus") or "","types":place.get("types") or []})
        page_token=data.get("nextPageToken")
        if not page_token: break
        if page+1<max_pages: time.sleep(delay_seconds)
    seen=set(); unique=[]
    for place in all_places:
        key=place.get("place_id") or f"{place.get('name')}|{place.get('address')}"
        if key and key not in seen: seen.add(key); unique.append(place)
    return unique

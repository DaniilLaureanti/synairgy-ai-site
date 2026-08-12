from __future__ import annotations

import html
from typing import Any
import requests

def _post(token:str,payload:dict[str,Any])->None:
    response=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json=payload,timeout=20); response.raise_for_status()

def notify_lead(token:str,chat_id:str,place:dict,analysis:dict,notion_url:str="")->None:
    text=(f"🔥 <b>SYNAIRGY LEAD — {analysis.get('score',0)}/100</b>\n\n<b>{html.escape(place.get('name') or 'Lead')}</b>\n🎯 {html.escape(analysis.get('recommended_offer') or '')} · от €{int(analysis.get('price_eur') or 0)}\n⚠️ {html.escape(analysis.get('problem') or '')}\n\n<b>Заход:</b>\n{html.escape(analysis.get('opening') or '')}\n")
    if place.get("phone"): text+=f"\n☎️ {html.escape(place['phone'])}\n"
    keyboard=[]
    if notion_url: keyboard.append([{"text":"Открыть лид в Notion","url":notion_url}])
    if place.get("website"): keyboard.append([{"text":"Сайт компании","url":place["website"]}])
    payload={"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}
    if keyboard: payload["reply_markup"]={"inline_keyboard":keyboard}
    _post(token,payload)

def notify_summary(token:str,chat_id:str,*,query:str,discovered:int,new_leads:int,high_score:int,skipped_duplicates:int)->None:
    text=f"🎯 <b>SynAirgy Lead Engine завершён</b>\n\nЗапрос: {html.escape(query)}\nНайдено: {discovered}\nНовых в CRM: {new_leads}\n🔥 Score ≥ threshold: {high_score}\nДубли: {skipped_duplicates}"
    _post(token,{"chat_id":chat_id,"text":text,"parse_mode":"HTML","disable_web_page_preview":True})

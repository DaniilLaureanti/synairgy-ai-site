from __future__ import annotations

import json
from typing import Any
import requests
from catalog import OFFER_CATALOG, OFFER_DESCRIPTIONS

RESPONSES_URL = "https://api.openai.com/v1/responses"
SCORE_COMPONENTS = {
    "business_quality": 20,
    "pain_strength": 30,
    "synairgy_fit": 25,
    "contactability": 15,
    "evidence_confidence": 10,
}


def _schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "problem",
            "evidence",
            "why_now",
            "recommended_offer",
            "recommended_channel",
            "score_components",
            "opening",
            "call_script",
            "legal_relevance",
            "skip_reason",
        ],
        "properties": {
            "problem": {"type": "string"},
            "evidence": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
            "why_now": {"type": "string"},
            "recommended_offer": {"type": "string", "enum": list(OFFER_CATALOG)},
            "recommended_channel": {
                "type": "string",
                "enum": ["Phone", "Instagram", "Contact form", "Existing relationship", "Other"],
            },
            "score_components": {
                "type": "object",
                "additionalProperties": False,
                "required": list(SCORE_COMPONENTS),
                "properties": {
                    key: {"type": "integer", "minimum": 0, "maximum": maximum}
                    for key, maximum in SCORE_COMPONENTS.items()
                },
            },
            "opening": {"type": "string"},
            "call_script": {"type": "string"},
            "legal_relevance": {"type": "string"},
            "skip_reason": {"type": "string"},
        },
    }


def _system_prompt() -> str:
    offers = "\n".join(
        f"- {name}: €{price} — {OFFER_DESCRIPTIONS[name]}"
        for name, price in OFFER_CATALOG.items()
    )
    return f"""Ты sales analyst SynAirgy в Гамбурге.

Твоя задача — НЕ продавать любой ценой, а отфильтровать слабые лиды. Для каждого бизнеса выбери максимум ОДНУ реальную проблему и ОДИН продукт.

Каталог:
{offers}

Правила доказательности:
1. Используй только факты из Google Places и публичного HTML сайта, переданного во входе.
2. Не утверждай, что визуал, дизайн или Instagram плохой, если фактическое качество контента не было показано.
3. Отсутствие Instagram-ссылки, видео на сайте, онлайн-записи, формы и т.п. — только сигнал, а не доказательство низкого качества бизнеса.
4. Если доказательств мало — снижай evidence_confidence и общий потенциал лида.
5. AI/automation предлагай только когда видна ручная рутина, FAQ, телефонная запись, формы/CRM-процесс или другая конкретная точка автоматизации.
6. Для первого проекта предпочитай простой продукт с ясной измеримой ценностью, если он реально решает найденную проблему.
7. opening и call_script — короткие, человеческие, на немецком языке; без давления и без шаблонного массового спама.
8. legal_relevance — кратко объясни, почему конкретный ручной B2B-контакт потенциально связан с очевидной деловой потребностью именно этой компании. Если такой причины нет, прямо скажи это и снизь contactability/score.
9. Холодную электронную рекламу не предлагай как стандартный канал. Instagram и Contact form выбирай только если во входных данных есть явный контекст, делающий такой канал уместным; иначе предпочитай Phone при реальной B2B-релевантности или Other.
10. recommended_channel — только рекомендация для РУЧНОЙ проверки человеком. Система ничего не рассылает автоматически.
11. Если лид в целом слабый, заполни skip_reason конкретной причиной. Для сильного лида skip_reason оставь пустой строкой.
"""


def analyze_lead(api_key: str, model: str, place: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "model": model,
        "store": False,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": _system_prompt()}]},
            {
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": json.dumps({"place": place, "website_inspection": site}, ensure_ascii=False),
                }],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "synairgy_lead_analysis",
                "description": "Evidence-grounded qualification of one SynAirgy B2B lead.",
                "strict": True,
                "schema": _schema(),
            },
            "verbosity": "low",
        },
    }
    response = requests.post(
        RESPONSES_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    text = ""
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                text += part.get("text", "")
    if not text:
        raise RuntimeError("OpenAI response contained no output_text")
    result = json.loads(text)
    result["score"] = normalize_score(result, place, site)
    result["price_eur"] = OFFER_CATALOG[result["recommended_offer"]]
    return result


def normalize_score(result: dict[str, Any], place: dict[str, Any], site: dict[str, Any]) -> int:
    components = result.get("score_components") or {}
    score = sum(
        max(0, min(int(components.get(key, 0)), maximum))
        for key, maximum in SCORE_COMPONENTS.items()
    )
    if place.get("business_status") and place.get("business_status") != "OPERATIONAL":
        return 0
    evidence = [e for e in result.get("evidence", []) if str(e).strip()]
    confidence = int(components.get("evidence_confidence", 0) or 0)
    if not evidence:
        score = min(score, 50)
    if confidence < 5:
        score = min(score, 69)
    if not site.get("reachable") and not place.get("website"):
        score = min(score, 62)
    return max(0, min(score, 100))

"""LLM-слой симулятора «Аким на 5 часов».
Основа — функция structured() из первого коммита Adilzhan (ai.py): вызов OpenAI Responses API
со строгой JSON-схемой. Модель НЕ считает числа — она объясняет результат engine.simulate().
При DEMO_MODE=true или без ключа работает детерминированное объяснение (fallback)."""
import os, json, httpx
from engine import MEASURES, INDICATOR_NAMES, DISTRICT_PROFILES

MODEL = os.getenv("OPENAI_MODEL", "gpt-6-sol")

def openai_key():
    return os.getenv("OPENAI_API_KEY", "").strip()

def demo_mode():
    return os.getenv("DEMO_MODE", "false").lower() == "true"

async def structured(instructions, content, schema, name):
    key = openai_key()
    if not key: raise ValueError("Добавьте OPENAI_API_KEY в .env или включите DEMO_MODE=true.")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.openai.com/v1/responses", headers={"Authorization": f"Bearer {key}"}, json={
            "model": MODEL, "store": False, "instructions": instructions,
            "input": [{"role": "user", "content": content}],
            "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}}})
        r.raise_for_status()
        result = r.json()
        texts = [part["text"] for item in result.get("output", []) for part in item.get("content", []) if part.get("type") == "output_text"]
        if not texts: raise ValueError("Модель не вернула данные.")
        return json.loads("".join(texts))

EXPLAIN_SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "strengths": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}},
    "consequences": {"type": "array", "items": {"type": "string"}},
    "tradeoffs": {"type": "array", "items": {"type": "string"}},
    "recommendation": {"type": "string"}},
    "required": ["summary","strengths","risks","consequences","tradeoffs","recommendation"], "additionalProperties": False}

INSTRUCTIONS = ("Ты — советник акима Астаны в симуляторе распределения бюджета. Тебе передан результат "
    "ДЕТЕРМИНИРОВАННОГО расчёта: базовый и итоговый Astana Quality of Life Score, оценки районов до/после, "
    "вклад каждой меры по показателям, критические значения (<40), остаток бюджета. "
    "Правила: не пересчитывай и не придумывай числа — цитируй только переданные; объясни сильные стороны, риски, "
    "последствия и компромиссы сценария простым языком управленца; отдельно отметь самый слабый район и "
    "критические показатели; формулируй выводы как гипотезы для обсуждения. Отвечай по-русски, кратко, по 2-4 пункта в списках.")

def _payload(decisions, result, base):
    top = sorted(result["contributions"], key=lambda c: -abs(c[3]))[:12]
    return {"decisions": [{"measure": m, "name": MEASURES[m].name if m in MEASURES else m, "district": d} for m, d in decisions],
            "base_score": base["score"], "score": result["score"], "delta": round(result["score"]-base["score"],2),
            "cost": result["cost"], "budget_left": result["budget_left"],
            "district_scores_before": base["district_scores"], "district_scores_after": result["district_scores"],
            "district_profiles": DISTRICT_PROFILES, "critical_after": result["critical"], "n_crit_before": base["n_crit"],
            "top_contributions": [{"measure": m, "district": dist, "indicator": INDICATOR_NAMES.get(k, k), "delta": v} for m, dist, k, v in top]}

def fallback_explanation(decisions, result, base):
    p = _payload(decisions, result, base)
    weakest = min(result["district_scores"], key=result["district_scores"].get)
    gains = sorted(((d, round(result["district_scores"][d]-base["district_scores"][d],2)) for d in result["district_scores"]), key=lambda x: -x[1])
    crit_txt = ", ".join(f"{d}/{INDICATOR_NAMES[k]}" for d, k in result["critical"])
    return {"summary": f"Score изменился с {p['base_score']} до {p['score']} ({p['delta']:+}). Потрачено {p['cost']} из 100, остаток {p['budget_left']}.",
            "strengths": [f"{d}: +{g}" for d, g in gains if g > 0][:4] or ["Ни один район не улучшился."],
            "risks": [f"Критические показатели (<40): {crit_txt}" if result["critical"] else "Критических показателей не осталось.",
                      f"Самый слабый район после мер: {weakest} ({result['district_scores'][weakest]})."],
            "consequences": [f"{c['measure']} -> {c['district']}: {c['indicator']} {c['delta']:+}" for c in p["top_contributions"][:5]],
            "tradeoffs": [f"Районы без изменений: {', '.join(d for d, g in gains if g == 0) or 'нет'}."],
            "recommendation": "Объяснение сформировано без LLM (DEMO_MODE или нет ключа). Для AI-анализа задайте OPENAI_API_KEY.",
            "source": "deterministic"}

async def explain_scenario(decisions, result, base, lang: str = "ru", event: dict | None = None):
    if demo_mode() or not openai_key():
        return fallback_explanation(decisions, result, base)
    try:
        payload = _payload(decisions, result, base)
        if event: payload["event"] = {"name": event["name"], "description": event["description"], "shocks": event["shocks"]}
        instr = INSTRUCTIONS + (" Отвечай на казахском языке." if lang == "kz" else "")
        out = await structured(instr, json.dumps(payload, ensure_ascii=False), EXPLAIN_SCHEMA, "scenario_explanation")
        out["source"] = MODEL
        return out
    except Exception as e:
        out = fallback_explanation(decisions, result, base)
        out["note"] = f"LLM недоступна ({e.__class__.__name__}), показано детерминированное объяснение."
        return out

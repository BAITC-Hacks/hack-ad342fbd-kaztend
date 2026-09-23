"""Агент-советник акима: понимает запрос на естественном языке (RU/KZ), сам вызывает инструменты
(validate / simulate / improve / best_under_budget / catalog), собирает допустимый набор и объясняет.
LLM не считает числа: все расчёты делает engine, модель только выбирает и объясняет.
Без ключа или в DEMO_MODE работает детерминированный разбор ограничений (fallback)."""
from __future__ import annotations
import json, os, re, httpx
import engine, analytics
from engine import Decision, MEASURES, DISTRICTS, DISTRICT_PROFILES
from ai import openai_key, demo_mode, MODEL

MAX_STEPS = 8

# ---------- инструменты (детерминированные) ----------
def _dec(items): return [Decision(d["measure"], d.get("district") or None) for d in items]

def tool_catalog(_args: dict) -> dict:
    return {"budget": engine.BUDGET, "rules": "ровно 5 решений, без повторов, ≤2 мер одного направления, район для мер типа «Район»; несовместимы M1/M3, M4/M7 и M5/M13 в одном районе",
            "districts": {d: {"population_share": p, "profile": DISTRICT_PROFILES[d], "indicators": dict(zip(engine.INDICATORS, v))} for d, (p, v) in DISTRICTS.items()},
            "measures": [{"id": m.id, "direction": m.direction, "name": m.name, "scope": m.scope, "cost": m.cost, "lag": m.lag, "effects": m.effects} for m in MEASURES.values()]}

def tool_validate(args: dict) -> dict:
    errs = engine.validate(_dec(args["decisions"])); return {"valid": not errs, "errors": errs}

def tool_simulate(args: dict) -> dict:
    r = engine.simulate(_dec(args["decisions"]))
    if not r["valid"]: return r
    return {k: r[k] for k in ("valid","score","cost","budget_left","d_avg","d_min","n_crit","critical","district_scores")}

def tool_improve(args: dict) -> dict:
    from app import _improve  # локальный поиск одной замены
    return {"improvements": _improve(_dec(args["decisions"]), k=3)}

def tool_best_under_budget(args: dict) -> dict:
    res = analytics.best_under_budget(int(args.get("budget", engine.BUDGET)), args.get("focus_district"))
    return res or {"error": "кэш перебора не готов"}

TOOLS = {"catalog": tool_catalog, "validate": tool_validate, "simulate": tool_simulate, "improve": tool_improve, "best_under_budget": tool_best_under_budget}
DEC_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {"measure": {"type": "string"}, "district": {"type": ["string", "null"]}}, "required": ["measure", "district"], "additionalProperties": False}}
TOOL_SPECS = [
 {"type": "function", "name": "catalog", "description": "Справочник: районы с показателями, мероприятия с эффектами и стоимостью, правила.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
 {"type": "function", "name": "validate", "description": "Проверить набор из 5 решений на правила.", "parameters": {"type": "object", "properties": {"decisions": DEC_SCHEMA}, "required": ["decisions"], "additionalProperties": False}},
 {"type": "function", "name": "simulate", "description": "Рассчитать Score и оценки районов для набора решений.", "parameters": {"type": "object", "properties": {"decisions": DEC_SCHEMA}, "required": ["decisions"], "additionalProperties": False}},
 {"type": "function", "name": "improve", "description": "Найти замены одной меры/района, повышающие Score.", "parameters": {"type": "object", "properties": {"decisions": DEC_SCHEMA}, "required": ["decisions"], "additionalProperties": False}},
 {"type": "function", "name": "best_under_budget", "description": "Лучший допустимый набор при бюджете не выше budget, опционально с фокусом на район.", "parameters": {"type": "object", "properties": {"budget": {"type": "integer"}, "focus_district": {"type": ["string", "null"]}}, "required": ["budget", "focus_district"], "additionalProperties": False}},
]
FINAL_SCHEMA = {"type": "object", "properties": {
    "decisions": DEC_SCHEMA, "rationale": {"type": "string"}, "tradeoffs": {"type": "array", "items": {"type": "string"}},
    "answer": {"type": "string"}}, "required": ["decisions", "rationale", "tradeoffs", "answer"], "additionalProperties": False}
SYSTEM = ("Ты — агент-советник акима Астаны в симуляторе бюджета. Пользователь описывает цель и ограничения "
          "(бюджет, приоритетный район, направления). Работай инструментами: сначала catalog, затем best_under_budget "
          "или сборка набора вручную, обязательно validate и simulate итогового набора; используй improve для доводки. "
          "Числа бери только из инструментов, ничего не выдумывай. Итог — ровно 5 решений, допустимых по правилам. "
          "Отвечай на языке пользователя (русский или казахский), кратко и по делу; формулируй как рекомендацию для обсуждения.")

# ---------- fallback без LLM ----------
_DISTRICT_ALIASES = {"нура": "Нура", "нұра": "Нура", "есиль": "Есиль", "есіл": "Есиль", "алматы": "Алматы", "сарыарка": "Сарыарка", "сарыарқа": "Сарыарка", "байконур": "Байконур", "байқоңыр": "Байконур"}

def parse_constraints(message: str, current: list | None) -> dict:
    text = message.lower()
    budget = engine.BUDGET
    m = re.search(r"(?:не больше|не более|максимум|до|бюджет|≤|<=|аспа|дейін)\D{0,12}(\d{2,3})", text)
    if m: budget = max(0, min(engine.BUDGET, int(m.group(1))))
    focus = next((v for k, v in _DISTRICT_ALIASES.items() if k in text), None)
    improve = any(w in text for w in ("улучш", "доработ", "жақсарт", "лучше", "оптимиз"))
    return {"budget": budget, "focus_district": focus, "improve_current": improve and bool(current)}

def fallback(message: str, current: list | None) -> dict:
    c = parse_constraints(message, current)
    trace = [{"tool": "parse_constraints", "input": message, "output": c}]
    decisions = None
    if c["improve_current"]:
        imp = tool_improve({"decisions": current}); trace.append({"tool": "improve", "output": imp})
        if imp["improvements"]: decisions = imp["improvements"][0]["decisions"]
    if decisions is None:
        best = tool_best_under_budget({"budget": c["budget"], "focus_district": c["focus_district"]})
        trace.append({"tool": "best_under_budget", "input": {"budget": c["budget"], "focus_district": c["focus_district"]}, "output": best})
        decisions = best.get("decisions") if best and "decisions" in best else None
    if not decisions:
        return {"decisions": [], "answer": "Не удалось подобрать набор: кэш перебора ещё не готов.", "rationale": "", "tradeoffs": [], "trace": trace, "source": "deterministic"}
    r = tool_simulate({"decisions": decisions}); trace.append({"tool": "simulate", "output": r})
    names = ", ".join(f"{d['measure']}{' · '+d['district'] if d['district'] else ''}" for d in decisions)
    focus_txt = f" с приоритетом района {c['focus_district']}" if c["focus_district"] else ""
    answer = (f"Подобран допустимый набор при бюджете ≤ {c['budget']}{focus_txt}: {names}. "
              f"Score {r['score']} (база {engine.baseline()['score']}), стоимость {r['cost']}, слабейший район даёт {r['d_min']}, критических значений {r['n_crit']}.")
    return {"decisions": decisions, "answer": answer, "rationale": "Детерминированный режим (нет ключа или DEMO_MODE): ограничения разобраны правилами, набор взят из полного перебора допустимых вариантов.",
            "tradeoffs": [f"Остаток бюджета {r['budget_left']} у.е. не даёт бонуса — можно проверить более дорогие меры."], "trace": trace, "source": "deterministic"}

# ---------- LLM-агент с инструментами (OpenAI Responses API) ----------
async def run_agent(message: str, current: list | None, lang: str = "ru") -> dict:
    if demo_mode() or not openai_key():
        return fallback(message, current)
    trace = []
    user = {"message": message, "current_decisions": current or [], "language": lang}
    input_items = [{"role": "user", "content": json.dumps(user, ensure_ascii=False)}]
    headers = {"Authorization": f"Bearer {openai_key()}"}
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            for _ in range(MAX_STEPS):
                body = {"model": MODEL, "store": False, "instructions": SYSTEM, "input": input_items, "tools": TOOL_SPECS,
                        "text": {"format": {"type": "json_schema", "name": "advisor_answer", "strict": True, "schema": FINAL_SCHEMA}}}
                resp = await client.post("https://api.openai.com/v1/responses", headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                outputs = data.get("output", [])
                calls = [o for o in outputs if o.get("type") == "function_call"]
                if not calls:
                    texts = [p["text"] for o in outputs for p in o.get("content", []) if p.get("type") == "output_text"]
                    final = json.loads("".join(texts)) if texts else {}
                    if final.get("decisions"):
                        r = tool_simulate({"decisions": final["decisions"]}); trace.append({"tool": "simulate(final)", "output": r})
                        if not r.get("valid"):
                            fb = fallback(message, current); fb["note"] = "Набор агента не прошёл валидацию — показан детерминированный вариант."; return fb
                    final.update({"trace": trace, "source": MODEL}); return final
                input_items.extend(outputs)
                for call in calls:
                    args = json.loads(call.get("arguments") or "{}")
                    try: result = TOOLS[call["name"]](args)
                    except Exception as e: result = {"error": str(e)}
                    trace.append({"tool": call["name"], "input": args, "output": result})
                    input_items.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, ensure_ascii=False)})
        fb = fallback(message, current); fb["note"] = "Агент превысил лимит шагов — показан детерминированный вариант."; return fb
    except Exception as e:
        fb = fallback(message, current); fb["note"] = f"LLM недоступна ({e.__class__.__name__}) — показан детерминированный вариант."; fb["trace"] = trace + fb["trace"]; return fb

"""Агент-советник акима: понимает запрос на естественном языке (RU/KZ), сам вызывает инструменты
(validate / simulate / improve / best_under_budget / catalog), собирает допустимый набор и объясняет.
LLM не считает числа: все расчёты делает engine, модель только выбирает и объясняет.
Без ключа или в DEMO_MODE работает детерминированный разбор ограничений (fallback)."""
from __future__ import annotations
import asyncio, json, httpx
import engine, analytics, events
import constraints as user_constraints
from constraints import parse_constraints
from engine import Decision, MEASURES, DISTRICTS, DISTRICT_PROFILES
from ai import openai_key, demo_mode, MODEL

MAX_STEPS = 8

# ---------- инструменты (детерминированные) ----------
def _dec(items): return [Decision(d["measure"], d.get("district") or None) for d in items]

def _context(context=None):
    return context or {"constraints": parse_constraints(""), "districts": None, "event": None}


def tool_catalog(_args: dict, context=None) -> dict:
    ctx = _context(context)
    districts = ctx["districts"] or DISTRICTS
    return {"budget": engine.BUDGET, "constraints": ctx["constraints"], "event": ctx["event"],
            "baseline": engine.baseline(districts),
            "rules": "ровно 5 решений, без повторов, ≤2 мер направления; M1/M3 несовместимы в любых районах, M4/M7 и M5/M13 — в одном районе. Фокус: минимум 2 районные меры. Каждое приоритетное направление должно быть представлено, при фокусе — в выбранном районе.",
            "districts": {d: {"population_share": p, "profile": DISTRICT_PROFILES[d], "indicators": dict(zip(engine.INDICATORS, v))} for d, (p, v) in districts.items()},
            "measures": [{"id": m.id, "direction": m.direction, "name": m.name, "scope": m.scope, "cost": m.cost, "lag": m.lag, "effects": m.effects} for m in MEASURES.values()]}


def tool_validate(args: dict, context=None) -> dict:
    errs = user_constraints.errors(_dec(args["decisions"]), _context(context)["constraints"])
    return {"valid": not errs, "errors": errs}


def tool_simulate(args: dict, context=None) -> dict:
    ctx = _context(context)
    valid = tool_validate(args, ctx)
    if not valid["valid"]:
        return valid
    r = engine.simulate(_dec(args["decisions"]), ctx["districts"])
    return {k: r[k] for k in ("valid", "score", "cost", "budget_left", "d_avg", "d_min", "n_crit", "critical", "district_scores")}


def tool_improve(args: dict, context=None) -> dict:
    from app import _improve
    ctx = _context(context)
    return {"improvements": _improve(_dec(args["decisions"]), k=3, districts=ctx["districts"], constraints=ctx["constraints"])}


def tool_best_under_budget(args: dict, context=None) -> dict:
    from search import get_cache
    ctx = _context(context)
    c = ctx["constraints"]
    budget = min(c["budget"], int(args.get("budget", engine.BUDGET)))
    if budget < 61:
        return {"error": "При таком бюджете нельзя выбрать пять решений: минимальная стоимость допустимого набора — 61 у.е.", "minimum_cost": 61}
    focus = c.get("focus_district") or args.get("focus_district")
    cache = get_cache(ctx["event"], focus, tuple(sorted(c.get("directions", []))))
    return cache["best_under_budget"].get(str(budget)) or {
        "error": "Нет допустимого набора для указанных бюджета и приоритетов.",
        "minimum_cost": cache["minimum_cost"]}

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
          "Переданные constraints обязательны, не ослабляй их. Инструменты уже учитывают событие. Числа бери только из инструментов, ничего не выдумывай. Итог — ровно 5 решений, допустимых по правилам. "
          "Отвечай на языке пользователя (русский или казахский), кратко и по делу; формулируй как рекомендацию для обсуждения.")

# ---------- fallback без LLM ----------
def fallback(message: str, current: list | None, context=None) -> dict:
    ctx = context or {"constraints": parse_constraints(message, current), "districts": None, "event": None}
    c = ctx["constraints"]
    trace = [{"tool": "parse_constraints", "input": message, "output": c}]
    decisions = None
    if c["improve_current"]:
        imp = tool_improve({"decisions": current}, ctx)
        trace.append({"tool": "improve", "output": imp})
        if imp["improvements"]:
            decisions = imp["improvements"][0]["decisions"]
    if decisions is None:
        best = tool_best_under_budget(c, ctx)
        trace.append({"tool": "best_under_budget", "input": c, "output": best})
        decisions = best.get("decisions")
        if not decisions:
            return {"decisions": [], "answer": best["error"], "minimum_cost": best.get("minimum_cost"),
                    "rationale": "", "tradeoffs": [], "trace": trace, "source": "deterministic", "constraints": c}
    r = tool_simulate({"decisions": decisions}, ctx)
    trace.append({"tool": "simulate", "output": r})
    if not r["valid"]:
        return {"decisions": [], "answer": "; ".join(r["errors"]), "trace": trace, "source": "deterministic", "constraints": c}
    names = ", ".join(f"{d['measure']}{' · '+d['district'] if d['district'] else ''}" for d in decisions)
    focus_txt = f" с приоритетом района {c['focus_district']}" if c["focus_district"] else ""
    event_txt = f" Событие: {events.get_event(ctx['event'])['name']}." if ctx["event"] else ""
    answer = (f"Подобран допустимый набор при бюджете ≤ {c['budget']}{focus_txt}: {names}. "
              f"Score {r['score']} (база {engine.baseline(ctx['districts'])['score']}), стоимость {r['cost']}, "
              f"слабейший район даёт {r['d_min']}, критических значений {r['n_crit']}.{event_txt}")
    return {"decisions": decisions, "answer": answer,
            "rationale": "Ограничения проверены кодом. Поиск учитывает выбранное событие и приоритеты; при улучшении текущего набора сначала проверяется одна замена.",
            "tradeoffs": [f"Остаток бюджета {r['budget_left']} у.е. не даёт бонуса к Score."],
            "trace": trace, "source": "deterministic", "constraints": c}

# ---------- LLM-агент с инструментами (OpenAI Responses API) ----------
async def run_agent(message: str, current: list | None, lang: str = "ru", event=None, constraints=None) -> dict:
    c = parse_constraints(message, current)
    if constraints is not None:
        c.update(constraints)
    ctx = {"constraints": c, "event": event,
           "districts": events.apply_event(events.get_event(event)) if event else None}
    async def use_fallback():
        return await asyncio.to_thread(fallback, message, current, ctx)
    if demo_mode() or not openai_key():
        return await use_fallback()
    trace = []
    user = {"message": message, "current_decisions": current or [], "language": lang, "constraints": c, "event": event}
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
                        r = tool_simulate({"decisions": final["decisions"]}, ctx); trace.append({"tool": "simulate(final)", "output": r})
                        if not r.get("valid"):
                            fb = await use_fallback(); fb["note"] = "Набор агента не прошёл валидацию — показан детерминированный вариант."; return fb
                    if not final.get("decisions"):
                        return await use_fallback()
                    final.update({"trace": trace, "source": MODEL, "constraints": c}); return final
                input_items.extend(outputs)
                for call in calls:
                    args = json.loads(call.get("arguments") or "{}")
                    try: result = await asyncio.to_thread(TOOLS[call["name"]], args, ctx)
                    except Exception as e: result = {"error": str(e)}
                    trace.append({"tool": call["name"], "input": args, "output": result})
                    input_items.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps(result, ensure_ascii=False)})
        fb = await use_fallback(); fb["note"] = "Агент превысил лимит шагов — показан детерминированный вариант."; return fb
    except Exception as e:
        fb = await use_fallback(); fb["note"] = f"LLM недоступна ({e.__class__.__name__}) — показан детерминированный вариант."; fb["trace"] = trace + fb["trace"]; return fb

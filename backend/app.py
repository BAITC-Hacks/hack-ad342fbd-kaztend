"""FastAPI-приложение «Аким на 5 часов» — AI-симулятор бюджета Астаны (HackAlem AI, спец-трек Astana Innovations)."""
import sys, json, hashlib
from pathlib import Path
from typing import Optional, Literal
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(ROOT / ".env")

import engine, ai, analytics, events, store, report  # noqa: E402
import agent as agent_mod  # noqa: E402
import constraints as user_constraints
import search

DATA = ROOT / "data"
app = FastAPI(title="Аким на 5 часов — AI-симулятор бюджета Астаны")

class DecisionIn(BaseModel):
    measure: str
    district: Optional[str] = None


class DecisionsIn(BaseModel):
    decisions: list[DecisionIn]
    event: Optional[str] = None      # id события (см. /api/events) — шок применяется до мер
    lang: Optional[str] = "ru"


class AdvisorConstraints(BaseModel):
    budget: int = Field(default=100, ge=0, le=100)
    focus_district: Optional[Literal["Есиль", "Алматы", "Сарыарка", "Байконур", "Нура"]] = None
    directions: list[Literal["Транспорт", "Экология", "Соцсфера", "Безопасность", "Сервисы"]] = Field(default_factory=list)


class AgentIn(BaseModel):
    message: str
    decisions: list[DecisionIn] = []
    lang: Optional[str] = "ru"
    event: Optional[str] = None
    constraints: Optional[AdvisorConstraints] = None


class ScenarioIn(BaseModel):
    team: str
    decisions: list[DecisionIn]
    event: Optional[str] = None


class ReportIn(BaseModel):
    decisions: list[DecisionIn]
    team: Optional[str] = ""
    event: Optional[str] = None
    explanation: Optional[dict] = None
    explanation_scenario_id: Optional[str] = None


def _to_engine(items: list[DecisionIn]) -> list[engine.Decision]:
    return [engine.Decision(d.measure, (d.district or None)) for d in items]


def _scenario_id(items, event):
    value = {"decisions": sorted((d.measure, d.district or "") for d in items), "event": event or None}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _districts_for(event_id: Optional[str]):
    if not event_id: return None, None
    try: ev = events.get_event(event_id)
    except KeyError: raise HTTPException(404, f"Неизвестное событие {event_id}")
    return events.apply_event(ev), ev


@app.get("/api/catalog")
def catalog():
    passports = json.loads((DATA / "passports.json").read_text(encoding="utf-8"))
    return {
        "budget": engine.BUDGET, "n_decisions": engine.N_DECISIONS, "max_per_direction": engine.MAX_PER_DIRECTION,
        "horizon_quarters": engine.H, "critical_threshold": engine.CRIT_THRESHOLD,
        "indicators": [{"code": k, "name": engine.INDICATOR_NAMES[k], "weight": engine.WEIGHTS[k], **passports["indicators"].get(k, {})} for k in engine.INDICATORS],
        "districts": [{"name": d, "population_share": p, "profile": engine.DISTRICT_PROFILES[d], "indicators": dict(zip(engine.INDICATORS, v))} for d, (p, v) in engine.DISTRICTS.items()],
        "measures": [{"id": m.id, "direction": m.direction, "name": m.name, "scope": m.scope, "cost": m.cost, "lag": m.lag,
                      "effects": m.effects, **passports["measures"].get(m.id, {})} for m in engine.MEASURES.values()],
        "synergies": [{"pair": list(p), "indicator": k, "bonus": b} for p, (k, b) in engine.SYNERGIES.items()],
        "incompatible_any": engine.INCOMPAT_ANY, "incompatible_same_district": engine.INCOMPAT_SAME_DISTRICT,
        "events": [{"id": e["id"], "name": e["name"], "description": e["description"], "shocks": e["shocks"],
                    "baseline": engine.baseline(events.apply_event(e))} for e in events.EVENTS],
        "references": passports["references"], "baseline": engine.baseline(),
    }


@app.post("/api/validate")
def validate(body: DecisionsIn):
    errors = engine.validate(_to_engine(body.decisions))
    cost = sum(engine.MEASURES[d.measure].cost for d in body.decisions if d.measure in engine.MEASURES)
    return {"valid": not errors, "errors": errors, "cost": cost, "budget_left": engine.BUDGET - cost}


@app.post("/api/simulate")
def simulate(body: DecisionsIn):
    districts, ev = _districts_for(body.event)
    result = engine.simulate(_to_engine(body.decisions), districts)
    result["baseline"] = engine.baseline(districts)
    result["baseline_no_event"] = engine.baseline()
    result["event"] = ev
    result["scenario_id"] = _scenario_id(body.decisions, body.event)
    return result


@app.post("/api/explain")
async def explain(body: DecisionsIn):
    districts, ev = _districts_for(body.event)
    decs = _to_engine(body.decisions)
    result = engine.simulate(decs, districts)
    if not result["valid"]:
        return {"valid": False, "errors": result["errors"]}
    base = engine.baseline(districts)
    explanation = await ai.explain_scenario([(d.measure, d.district or None) for d in body.decisions], result, base, lang=body.lang or "ru", event=ev)
    return {"valid": True, "result": result, "baseline": base, "explanation": explanation, "event": ev,
            "scenario_id": _scenario_id(body.decisions, body.event)}


@app.post("/api/analyze")
def analyze(body: DecisionsIn):
    districts, ev = _districts_for(body.event)
    out = analytics.analyze(_to_engine(body.decisions), districts)
    out["event"] = ev
    out["scenario_id"] = _scenario_id(body.decisions, body.event)
    return out


def _improve(decisions: list[engine.Decision], k: int = 3, districts=None, constraints=None) -> list[dict]:
    """Локальный поиск: одна замена меры или района, которая максимально повышает Score."""
    current = engine.simulate(decisions, districts)
    if not current["valid"]:
        return []
    best = []
    for i in range(len(decisions)):
        for m in engine.MEASURES.values():
            targets = list(engine.DISTRICTS) if m.scope == "Район" else [None]
            for dist in targets:
                cand = list(decisions); cand[i] = engine.Decision(m.id, dist)
                if engine.validate(cand): continue
                if constraints and not user_constraints.matches(cand, constraints["budget"], constraints.get("focus_district"), constraints.get("directions", ())): continue
                r = engine.simulate(cand, districts)
                if r["score"] > current["score"] + 1e-9:
                    best.append({"score": r["score"], "cost": r["cost"], "delta": round(r["score"] - current["score"], 2),
                                 "replace_slot": i, "old": {"measure": decisions[i].measure, "district": decisions[i].district},
                                 "new": {"measure": m.id, "district": dist},
                                 "decisions": [{"measure": d.measure, "district": d.district} for d in cand]})
    best.sort(key=lambda x: (-x["score"], x["cost"]))
    seen, out = set(), []
    for b in best:
        key = tuple(sorted((d["measure"], d["district"]) for d in b["decisions"]))
        if key in seen: continue
        seen.add(key); out.append(b)
        if len(out) >= k: break
    return out


@app.post("/api/advise")
def advise(body: Optional[DecisionsIn] = None):
    districts, _ = _districts_for(body.event) if body else (None, None)
    improvements = _improve(_to_engine(body.decisions), districts=districts) if body and body.decisions else []
    cache = search.get_cache(body.event if body else None)
    return {"event": body.event if body else None,
            "top_sets": {"status": "ready", "sets": cache["sets"], "evaluated": cache["evaluated"]},
            "improvements": improvements,
            "pareto": {"ready": True, "front": cache["front"], "evaluated": cache["evaluated"]}}


@app.get("/api/pareto")
def pareto(budget: Optional[int] = None, focus_district: Optional[str] = None, event: Optional[str] = None):
    _districts_for(event)
    if focus_district and focus_district not in engine.DISTRICTS:
        raise HTTPException(422, "Неизвестный район")
    cache = search.get_cache(event, focus_district)
    out = {"ready": True, "event": event, "evaluated": cache["evaluated"], "front": cache["front"], "method": cache["method"]}
    if budget is not None:
        out["best_under_budget"] = cache["best_under_budget"].get(str(max(0, min(100, budget))))
        out["minimum_cost"] = cache["minimum_cost"]
    return out


@app.get("/api/events")
def list_events():
    return {"events": events.EVENTS}


@app.post("/api/event")
def random_event(seed: Optional[int] = None):
    ev = events.get_event(seed=seed)
    districts = events.apply_event(ev)
    return {"event": ev, "baseline_with_event": engine.baseline(districts), "baseline": engine.baseline()}


@app.post("/api/agent")
async def agent_endpoint(body: AgentIn):
    districts, ev = _districts_for(body.event)
    current = [{"measure": d.measure, "district": d.district} for d in body.decisions] or None
    out = await agent_mod.run_agent(body.message, current, body.lang or "ru", body.event,
                                    body.constraints.model_dump() if body.constraints else None)
    if out.get("decisions"):
        out["result"] = engine.simulate(_to_engine([DecisionIn(**d) for d in out["decisions"]]), districts)
    out["event"] = ev
    out["baseline"] = engine.baseline(districts)
    return out


@app.post("/api/constraints")
def parse_agent_constraints(body: AgentIn):
    return user_constraints.parse_constraints(body.message, body.decisions)


@app.get("/api/scenarios")
def scenarios():
    return {"scenarios": store.list_scenarios()}


@app.post("/api/scenarios")
def save_scenario(body: ScenarioIn):
    districts, ev = _districts_for(body.event)
    r = engine.simulate(_to_engine(body.decisions), districts)
    if not r["valid"]:
        raise HTTPException(400, "; ".join(r["errors"]))
    return store.add_scenario(body.team, [d.model_dump() for d in body.decisions], r["score"], r["cost"], ev["id"] if ev else None)


@app.delete("/api/scenarios/{sid}")
def delete_scenario(sid: str):
    return {"deleted": store.delete_scenario(sid)}


@app.post("/api/report", response_class=PlainTextResponse)
def make_report(body: ReportIn):
    districts, ev = _districts_for(body.event)
    if body.explanation is not None and body.explanation_scenario_id != _scenario_id(body.decisions, body.event):
        raise HTTPException(409, "Объяснение относится к другому сценарию. Сформируйте его заново.")
    return report.scenario_report(_to_engine(body.decisions), body.explanation, ev, districts, body.team or "")


app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")

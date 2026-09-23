"""FastAPI-приложение «Аким на 5 часов» — AI-симулятор бюджета Астаны (HackAlem AI, спец-трек Astana Innovations)."""
import sys, json, threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(ROOT / ".env")

import engine, ai, optimizer, analytics, events, store, report  # noqa: E402
import agent as agent_mod  # noqa: E402

DATA = ROOT / "data"
TOP_SETS_FILE = DATA / "top_sets.json"
_top_sets: dict = {"status": "building", "sets": []}
_pareto: dict | None = None


def _build_caches():
    global _top_sets, _pareto
    try:
        if TOP_SETS_FILE.exists():
            _top_sets = json.loads(TOP_SETS_FILE.read_text(encoding="utf-8"))
        else:
            res, n = optimizer.top_k(20)
            _top_sets = {"status": "ready", "evaluated": n, "sets": [{"score": s, "cost": c, "decisions": [{"measure": m, "district": d} for m, d in dec]} for s, c, dec in res]}
            DATA.mkdir(parents=True, exist_ok=True)
            TOP_SETS_FILE.write_text(json.dumps(_top_sets, ensure_ascii=False, indent=1), encoding="utf-8")
        _pareto = analytics.load_pareto() or analytics.build_pareto_cache()
    except Exception as e:  # pragma: no cover
        _top_sets = {"status": f"error: {e}", "sets": []}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_build_caches, daemon=True).start()
    yield


app = FastAPI(title="Аким на 5 часов — AI-симулятор бюджета Астаны", lifespan=lifespan)


class DecisionIn(BaseModel):
    measure: str
    district: Optional[str] = None


class DecisionsIn(BaseModel):
    decisions: list[DecisionIn]
    event: Optional[str] = None      # id события (см. /api/events) — шок применяется до мер
    lang: Optional[str] = "ru"


class AgentIn(BaseModel):
    message: str
    decisions: list[DecisionIn] = []
    lang: Optional[str] = "ru"


class ScenarioIn(BaseModel):
    team: str
    decisions: list[DecisionIn]
    event: Optional[str] = None


class ReportIn(BaseModel):
    decisions: list[DecisionIn]
    team: Optional[str] = ""
    event: Optional[str] = None
    explanation: Optional[dict] = None


def _to_engine(items: list[DecisionIn]) -> list[engine.Decision]:
    return [engine.Decision(d.measure, (d.district or None)) for d in items]


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
        "events": [{"id": e["id"], "name": e["name"], "description": e["description"], "shocks": e["shocks"]} for e in events.EVENTS],
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
    return {"valid": True, "result": result, "baseline": base, "explanation": explanation, "event": ev}


@app.post("/api/analyze")
def analyze(body: DecisionsIn):
    districts, ev = _districts_for(body.event)
    out = analytics.analyze(_to_engine(body.decisions), districts)
    out["event"] = ev
    return out


def _improve(decisions: list[engine.Decision], k: int = 3, districts=None) -> list[dict]:
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
    return {"top_sets": _top_sets, "improvements": improvements,
            "pareto": {"ready": _pareto is not None, "front": (_pareto or {}).get("front", []), "evaluated": (_pareto or {}).get("evaluated")}}


@app.get("/api/pareto")
def pareto(budget: Optional[int] = None, focus_district: Optional[str] = None):
    if _pareto is None:
        return {"ready": False}
    out = {"ready": True, "evaluated": _pareto["evaluated"], "front": _pareto["front"], "method": _pareto["method"]}
    if budget is not None:
        out["best_under_budget"] = analytics.best_under_budget(budget, focus_district, _pareto)
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
    current = [{"measure": d.measure, "district": d.district} for d in body.decisions] or None
    out = await agent_mod.run_agent(body.message, current, body.lang or "ru")
    if out.get("decisions"):
        out["result"] = engine.simulate(_to_engine([DecisionIn(**d) for d in out["decisions"]]))
    return out


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
    return report.scenario_report(_to_engine(body.decisions), body.explanation, ev, districts, body.team or "")


app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")

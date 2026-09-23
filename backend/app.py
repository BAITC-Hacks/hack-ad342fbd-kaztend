"""FastAPI-приложение симулятора «Аким на 5 часов» (HackAlem AI, спец-трек Astana Innovations)."""
import os, sys, json, threading
from pathlib import Path
from typing import Optional
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(ROOT / ".env")

import engine, ai, optimizer  # noqa: E402

app = FastAPI(title="Аким на 5 часов — AI-симулятор бюджета Астаны")
TOP_SETS_FILE = ROOT / "data" / "top_sets.json"
_top_sets: dict = {"status": "building", "sets": []}


class DecisionIn(BaseModel):
    measure: str
    district: Optional[str] = None


class DecisionsIn(BaseModel):
    decisions: list[DecisionIn]


def _to_engine(items: list[DecisionIn]) -> list[engine.Decision]:
    return [engine.Decision(d.measure, (d.district or None)) for d in items]


def _build_top_sets():
    global _top_sets
    try:
        if TOP_SETS_FILE.exists():
            _top_sets = json.loads(TOP_SETS_FILE.read_text(encoding="utf-8"))
            return
        res, n = optimizer.top_k(20)
        sets = [{"score": s, "cost": c, "decisions": [{"measure": m, "district": d} for m, d in dec]} for s, c, dec in res]
        _top_sets = {"status": "ready", "evaluated": n, "sets": sets}
        TOP_SETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOP_SETS_FILE.write_text(json.dumps(_top_sets, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # pragma: no cover
        _top_sets = {"status": f"error: {e}", "sets": []}


@app.on_event("startup")
def _startup():
    threading.Thread(target=_build_top_sets, daemon=True).start()


@app.get("/api/catalog")
def catalog():
    return {
        "budget": engine.BUDGET, "n_decisions": engine.N_DECISIONS, "max_per_direction": engine.MAX_PER_DIRECTION,
        "horizon_quarters": engine.H, "critical_threshold": engine.CRIT_THRESHOLD,
        "indicators": [{"code": k, "name": engine.INDICATOR_NAMES[k], "weight": engine.WEIGHTS[k]} for k in engine.INDICATORS],
        "districts": [{"name": d, "population_share": p, "profile": engine.DISTRICT_PROFILES[d],
                       "indicators": dict(zip(engine.INDICATORS, v))} for d, (p, v) in engine.DISTRICTS.items()],
        "measures": [{"id": m.id, "direction": m.direction, "name": m.name, "scope": m.scope, "cost": m.cost,
                      "lag": m.lag, "effects": m.effects} for m in engine.MEASURES.values()],
        "synergies": [{"pair": list(p), "indicator": k, "bonus": b} for p, (k, b) in engine.SYNERGIES.items()],
        "incompatible_any": engine.INCOMPAT_ANY, "incompatible_same_district": engine.INCOMPAT_SAME_DISTRICT,
        "baseline": engine.baseline(),
    }


@app.post("/api/validate")
def validate(body: DecisionsIn):
    errors = engine.validate(_to_engine(body.decisions))
    cost = sum(engine.MEASURES[d.measure].cost for d in body.decisions if d.measure in engine.MEASURES)
    return {"valid": not errors, "errors": errors, "cost": cost, "budget_left": engine.BUDGET - cost}


@app.post("/api/simulate")
def simulate(body: DecisionsIn):
    result = engine.simulate(_to_engine(body.decisions))
    result["baseline"] = engine.baseline()
    return result


@app.post("/api/explain")
async def explain(body: DecisionsIn):
    result = engine.simulate(_to_engine(body.decisions))
    if not result["valid"]:
        return {"valid": False, "errors": result["errors"]}
    base = engine.baseline()
    explanation = await ai.explain_scenario([(d.measure, d.district or None) for d in body.decisions], result, base)
    return {"valid": True, "result": result, "baseline": base, "explanation": explanation}


def _improve(decisions: list[engine.Decision], k: int = 3) -> list[dict]:
    """Локальный поиск: одна замена меры или района, которая максимально повышает Score."""
    current = engine.simulate(decisions)
    if not current["valid"]:
        return []
    best = []
    for i in range(len(decisions)):
        for m in engine.MEASURES.values():
            targets = list(engine.DISTRICTS) if m.scope == "Район" else [None]
            for dist in targets:
                cand = list(decisions); cand[i] = engine.Decision(m.id, dist)
                if engine.validate(cand): continue
                r = engine.simulate(cand)
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
    improvements = _improve(_to_engine(body.decisions)) if body and body.decisions else []
    return {"top_sets": _top_sets, "improvements": improvements}


@app.get("/api/advise")
def advise_get():
    return {"top_sets": _top_sets, "improvements": []}


app.mount("/", StaticFiles(directory=str(ROOT / "frontend"), html=True), name="frontend")

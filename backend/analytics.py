"""Аналитика по методологии OECD/JRC (Handbook on Constructing Composite Indicators, 2008):
робастность к весам, равенство районов, эффективность мер, Парето-фронт «стоимость - Score»."""
from __future__ import annotations
import json, itertools
from pathlib import Path
import engine
from engine import Decision, INDICATORS, WEIGHTS, DISTRICTS, MEASURES

DATA = Path(__file__).resolve().parent.parent / "data"
DIRECTION_OF = {"T1":"Транспорт","T2":"Транспорт","E1":"Экология","E2":"Экология","S1":"Соцсфера","S2":"Соцсфера",
                "B1":"Безопасность","B2":"Безопасность","C1":"Сервисы","C2":"Сервисы"}
DIRECTIONS = ["Транспорт","Экология","Соцсфера","Безопасность","Сервисы"]

def _renorm(w: dict) -> dict:
    s = sum(w.values()); return {k: v/s for k, v in w.items()}

def sensitivity(decisions: list[Decision], districts: dict | None = None, delta: float = 0.2) -> dict:
    """Робастность: пересчёт Score при изменении веса каждого направления на ±delta (с перенормировкой),
    плюс равные веса. Возвращает разброс и вывод, устойчив ли выигрыш относительно базы."""
    r = engine.simulate(decisions, districts)
    if not r["valid"]:
        return {"valid": False, "errors": r["errors"]}
    base = engine.baseline(districts)
    scenarios = []
    for direction in DIRECTIONS:
        for sign, label in ((1, "+"), (-1, "−")):
            w = {k: v*(1+sign*delta) if DIRECTION_OF[k]==direction else v for k, v in WEIGHTS.items()}
            w = _renorm(w)
            s = engine.score_with_weights(r, w, districts)
            bs = engine.score_with_weights(base, w, districts)
            scenarios.append({"scenario": f"{direction} {label}{int(delta*100)}%", "score": s, "baseline": bs, "gain": round(s-bs, 2)})
    eq = _renorm({k: 1.0 for k in INDICATORS})
    scenarios.append({"scenario": "Равные веса", "score": engine.score_with_weights(r, eq, districts),
                      "baseline": engine.score_with_weights(base, eq, districts), "gain": 0})
    scenarios[-1]["gain"] = round(scenarios[-1]["score"] - scenarios[-1]["baseline"], 2)
    gains = [s["gain"] for s in scenarios]
    return {"valid": True, "nominal_score": r["score"], "nominal_gain": round(r["score"]-base["score"], 2),
            "min_score": min(s["score"] for s in scenarios), "max_score": max(s["score"] for s in scenarios),
            "min_gain": min(gains), "max_gain": max(gains), "robust": min(gains) > 0, "scenarios": scenarios,
            "method": "OECD/JRC 2008, шаг «robustness & sensitivity»: возмущение весов направлений ±20% с перенормировкой суммы весов к 1"}

def equity(result: dict, base: dict) -> dict:
    """Равенство между районами: разрыв, коэффициент вариации, Джини по оценкам районов, критические значения."""
    def stats(scores: dict):
        vals = sorted(scores.values()); n = len(vals); mean = sum(vals)/n
        cv = (sum((v-mean)**2 for v in vals)/n) ** 0.5 / mean
        gini = sum(abs(a-b) for a in vals for b in vals) / (2*n*n*mean)
        return {"min": round(vals[0],2), "max": round(vals[-1],2), "gap": round(vals[-1]-vals[0],2),
                "cv": round(cv,4), "gini": round(gini,4)}
    before, after = stats(base["district_scores"]), stats(result["district_scores"])
    weakest_before = min(base["district_scores"], key=base["district_scores"].get)
    weakest_after = min(result["district_scores"], key=result["district_scores"].get)
    return {"before": before, "after": after, "gap_change": round(after["gap"]-before["gap"],2),
            "gini_change": round(after["gini"]-before["gini"],4), "weakest_before": weakest_before, "weakest_after": weakest_after,
            "n_crit_before": base["n_crit"], "n_crit_after": result["n_crit"], "critical_after": result["critical"],
            "note": "Формула Score уже содержит роулсианский член 0.3×min(D) и штраф за значения <40 (непокомпенсаторная логика, OECD/JRC 2008)."}

def cost_effectiveness(decisions: list[Decision], districts: dict | None = None) -> list[dict]:
    """Вклад каждой меры в Score (приближённая атрибуция: 0.7×взвешенный по населению вклад в D_avg
    + 0.3×вклад в оценку слабейшего района) и стоимость единицы результата."""
    districts = districts or DISTRICTS
    r = engine.simulate(decisions, districts)
    if not r["valid"]:
        return []
    weakest = min(r["district_scores"], key=r["district_scores"].get)
    out = []
    for d in decisions:
        m = MEASURES[d.measure]
        contrib_avg = contrib_min = 0.0
        for mid, dist, k, delta in r["contributions"]:
            if mid == m.id or (mid.startswith("синергия") and m.id in mid):
                share = 0.5 if mid.startswith("синергия") else 1.0  # синергию делим между парой
                contrib_avg += districts[dist][0] * WEIGHTS[k] * delta * share
                if dist == weakest:
                    contrib_min += WEIGHTS[k] * delta * share
        # снятие штрафа: критические значения базы (<40), которые набор поднял выше порога
        penalty_credit = 0.0
        base_crit = set(map(tuple, engine.baseline(districts)["critical"]))
        fixed = base_crit - set(map(tuple, r["critical"]))
        for dist, k in fixed:
            lifters = [c for c in r["contributions"] if c[1] == dist and c[2] == k and c[3] > 0]
            total = sum(c[3] for c in lifters)
            for mid, _, _, delta in lifters:
                if mid == m.id: penalty_credit += delta/total
        gain = 0.7*contrib_avg + 0.3*contrib_min + penalty_credit
        out.append({"measure": m.id, "name": m.name, "district": d.district, "cost": m.cost, "penalty_credit": round(penalty_credit,3),
                    "score_gain": round(gain, 3), "gain_per_unit": round(gain/m.cost, 4), "lag": m.lag,
                    "effect_share": round((engine.H - m.lag)/engine.H, 3)})
    out.sort(key=lambda x: -x["gain_per_unit"])
    return out

def _all_valid_results():
    """Полный перебор (кэшируется в data/pareto.json)."""
    import optimizer
    for decisions in optimizer.enumerate_valid():
        r = engine.simulate(decisions)
        yield r["score"], r["cost"], [{"measure": d.measure, "district": d.district} for d in decisions]

def build_pareto_cache() -> dict:
    best_by_cost: dict[int, tuple] = {}
    n = 0
    for score, cost, dec in _all_valid_results():
        n += 1
        if cost not in best_by_cost or score > best_by_cost[cost][0]:
            best_by_cost[cost] = (score, dec)
    front = []
    best_so_far = -1
    for cost in sorted(best_by_cost):
        score, dec = best_by_cost[cost]
        if score > best_so_far:
            front.append({"cost": cost, "score": score, "decisions": dec}); best_so_far = score
    best_under = {}
    running = None
    for cap in range(0, engine.BUDGET + 1):
        cands = [(s, c, d) for c, (s, d) in best_by_cost.items() if c <= cap]
        if cands:
            s, c, d = max(cands, key=lambda x: (x[0], -x[1]))
            best_under[str(cap)] = {"score": s, "cost": c, "decisions": d}
    cache = {"evaluated": n, "front": front, "best_under_budget": best_under,
             "method": "полный перебор всех допустимых наборов; фронт Парето — недоминируемые точки «стоимость - Score»"}
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "pareto.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return cache

def load_pareto() -> dict | None:
    p = DATA / "pareto.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def best_under_budget(cap: int, focus_district: str | None = None, pareto: dict | None = None) -> dict | None:
    pareto = pareto or load_pareto()
    if not pareto: return None
    if not focus_district:
        return pareto["best_under_budget"].get(str(max(0, min(engine.BUDGET, int(cap)))))
    # с фокусом на район: лучший набор по фронту/кэшу, где >=2 меры адресуют район (или городские)
    best = None
    for item in pareto["front"]:
        if item["cost"] > cap: continue
        touches = sum(1 for d in item["decisions"] if d["district"] == focus_district or d["district"] is None)
        if touches >= 3 and (best is None or item["score"] > best["score"]):
            best = item
    return best or pareto["best_under_budget"].get(str(int(cap)))

def analyze(decisions: list[Decision], districts: dict | None = None) -> dict:
    r = engine.simulate(decisions, districts)
    if not r["valid"]:
        return {"valid": False, "errors": r["errors"]}
    base = engine.baseline(districts)
    return {"valid": True, "result": r, "baseline": base, "sensitivity": sensitivity(decisions, districts),
            "equity": equity(r, base), "cost_effectiveness": cost_effectiveness(decisions, districts)}

"""Поиск лучших допустимых наборов решений полным перебором (~700 тыс. вариантов, ~1 мин)."""
from itertools import combinations, product
import time
from engine import MEASURES, DISTRICTS, Decision, validate, simulate, BUDGET, N_DECISIONS

def enumerate_valid():
    ids = list(MEASURES); dists = list(DISTRICTS)
    for combo in combinations(ids, N_DECISIONS):
        if sum(MEASURES[i].cost for i in combo) > BUDGET: continue
        dirs = {}
        for i in combo: dirs[MEASURES[i].direction] = dirs.get(MEASURES[i].direction,0)+1
        if max(dirs.values()) > 2: continue
        if "M1" in combo and "M3" in combo: continue
        district_slots = [i for i in combo if MEASURES[i].scope == "Район"]
        for assign in product(dists, repeat=len(district_slots)):
            amap = dict(zip(district_slots, assign))
            decisions = [Decision(i, amap.get(i)) for i in combo]
            if validate(decisions): continue
            yield decisions

def top_k(k=10, min_budget_left=None):
    best = []; n = 0
    for decisions in enumerate_valid():
        n += 1
        r = simulate(decisions)
        if min_budget_left is not None and r["budget_left"] < min_budget_left: continue
        best.append((r["score"], r["cost"], [(d.measure, d.district) for d in decisions]))
    best.sort(key=lambda x: (-x[0], x[1]))
    return best[:k], n

if __name__ == "__main__":
    t = time.time(); res, n = top_k(5)
    print(f"перебрано валидных наборов: {n}, время {time.time()-t:.1f}s")
    for s,c,d in res: print(s, c, d)

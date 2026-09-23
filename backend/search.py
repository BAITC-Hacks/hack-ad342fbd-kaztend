"""Полный поиск с независимым кэшем для события и приоритетов пользователя."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import heapq
import json
import threading
import engine
import events
import optimizer

DATA = Path(__file__).resolve().parent.parent / "data"
_locks = {}
_locks_guard = threading.Lock()


def _fingerprint(event, focus, directions):
    # Кэш не переживает изменение расчётной логики или исходных данных.
    sources = [Path(__file__).with_name(name).read_bytes()
               for name in ("engine.py", "events.py", "optimizer.py", "constraints.py", "search.py")]
    return sha256(b"".join(sources) + json.dumps([event, focus, directions]).encode()).hexdigest()


def _build(event=None, focus=None, directions=()):
    districts = events.apply_event(events.get_event(event)) if event else None
    best_by_cost, top = {}, []
    count = 0
    for decisions in optimizer.enumerate_valid(focus, directions):
        # enumerate_valid уже проверил правила; используем ту же формулу без отчёта.
        r = engine._simulate_effects(decisions, districts, details=False)
        count += 1
        score, cost = r["score"], r["cost"]
        # Сериализуем только кандидатов, которые попадут в результаты.
        if cost not in best_by_cost or score > best_by_cost[cost]["score"] or len(top) < 20 or (score, -cost) > top[0][:2]:
            item = {"score": score, "cost": cost,
                    "decisions": [{"measure": d.measure, "district": d.district} for d in decisions]}
            if cost not in best_by_cost or score > best_by_cost[cost]["score"]:
                best_by_cost[cost] = item
            entry = (score, -cost, -count, item)
            if len(top) < 20:
                heapq.heappush(top, entry)
            elif entry[:2] > top[0][:2]:
                heapq.heapreplace(top, entry)
    front, best_under = [], {}
    best = None
    for cap in range(engine.BUDGET + 1):
        candidate = best_by_cost.get(cap)
        if candidate and (best is None or candidate["score"] > best["score"]):
            best = candidate
            front.append(candidate)
        if best:
            best_under[str(cap)] = best
    return {"event": event, "focus_district": focus, "directions": list(directions),
            "evaluated": count, "front": front, "best_under_budget": best_under,
            "minimum_cost": min(best_by_cost, default=None),
            "sets": [x[3] for x in sorted(top, key=lambda x: x[:3], reverse=True)],
            "method": "полный перебор допустимых наборов для выбранного события и ограничений"}


@lru_cache(maxsize=64)
def get_cache(event=None, focus=None, directions=()):
    if event:
        events.get_event(event)  # неизвестные события не превращаются в базовый сценарий
    if focus and focus not in engine.DISTRICTS:
        raise ValueError("Неизвестный район")
    if any(d not in {m.direction for m in engine.MEASURES.values()} for d in directions):
        raise ValueError("Неизвестное направление")
    if not event and not focus and not directions:
        pareto, top = DATA / "pareto.json", DATA / "top_sets.json"
        if pareto.exists() and top.exists():
            out = json.loads(pareto.read_text(encoding="utf-8"))
            out.update(json.loads(top.read_text(encoding="utf-8")))
            out.update(event=None, focus_district=None, directions=[], minimum_cost=min(x["cost"] for x in out["front"]))
            return out
    key = _fingerprint(event, focus, directions)
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        path = DATA / "search_cache" / f"{key}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        out = _build(event, focus, directions)
        # Отсутствие прав на запись кэша не мешает работе симулятора.
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            from uuid import uuid4
            temp = path.with_suffix(f".{uuid4().hex}.tmp")
            temp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except OSError:
            pass
        return out

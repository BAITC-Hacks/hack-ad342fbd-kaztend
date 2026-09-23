"""Сохранённые сценарии / лидерборд команд: файл data/scenarios.json (без внешних БД, работает офлайн)."""
import json, threading, time, uuid
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "data"
FILE = DATA / "scenarios.json"
_lock = threading.Lock()

def _read() -> list:
    if not FILE.exists(): return []
    try: return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception: return []

def _write(items: list):
    DATA.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

def list_scenarios() -> list:
    with _lock:
        items = _read()
    return sorted(items, key=lambda x: (-x["score"], x["cost"]))

def add_scenario(team: str, decisions: list, score: float, cost: int, event: str | None = None) -> dict:
    item = {"id": uuid.uuid4().hex[:8], "team": team.strip()[:40] or "Без названия", "decisions": decisions,
            "score": score, "cost": cost, "event": event, "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with _lock:
        items = _read(); items.append(item); _write(items)
    return item

def delete_scenario(sid: str) -> bool:
    with _lock:
        items = _read(); new = [i for i in items if i["id"] != sid]; _write(new)
    return len(new) != len(items)

def clear():
    with _lock: _write([])

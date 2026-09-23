"""Неожиданные городские события: шок по исходным показателям ДО применения мер (опция ТЗ)."""
import random
from engine import DISTRICTS, INDICATORS

EVENTS = [
 {"id":"winter","name":"Аварийная зима","description":"Серия аварий на теплосетях в морозы −35°C: падает надёжность ЖКХ и скорость реакции на обращения.",
  "shocks":[{"district":"Алматы","indicator":"C1","delta":-8},{"district":"Алматы","indicator":"C2","delta":-4},{"district":"Сарыарка","indicator":"C1","delta":-4}]},
 {"id":"smog","name":"Смоговый сезон","description":"Безветренная зима и печное отопление частного сектора: качество воздуха резко падает.",
  "shocks":[{"district":"Сарыарка","indicator":"E2","delta":-10},{"district":"Байконур","indicator":"E2","delta":-5}]},
 {"id":"influx","name":"Приток населения","description":"Ускоренная миграция (+100 тыс. в год): перегружены школы, поликлиники и дороги в новых кварталах.",
  "shocks":[{"district":"Нура","indicator":"S1","delta":-6},{"district":"Нура","indicator":"T1","delta":-4},{"district":"Есиль","indicator":"S1","delta":-5}]},
 {"id":"flood","name":"Весенний паводок","description":"Разлив Есиля: подтоплены дороги и сети на левом берегу.",
  "shocks":[{"district":"Есиль","indicator":"C1","delta":-6},{"district":"Есиль","indicator":"B2","delta":-4},{"district":"Есиль","indicator":"T1","delta":-3}]},
 {"id":"heat","name":"Аномальная жара","description":"Засушливое лето: страдают зелёные насаждения и водоснабжение.",
  "shocks":[{"district":"Сарыарка","indicator":"E1","delta":-6},{"district":"Нура","indicator":"E1","delta":-5},{"district":"Алматы","indicator":"C1","delta":-3}]},
]

def get_event(event_id: str | None = None, seed: int | None = None) -> dict:
    if event_id:
        for e in EVENTS:
            if e["id"] == event_id: return e
        raise KeyError(event_id)
    rng = random.Random(seed)
    return rng.choice(EVENTS)

def apply_event(event: dict) -> dict:
    """Возвращает копию DISTRICTS с применённым шоком (значения ограничены 0..100)."""
    out = {d: (p, list(v)) for d, (p, v) in DISTRICTS.items()}
    for s in event["shocks"]:
        p, v = out[s["district"]]
        i = INDICATORS.index(s["indicator"])
        v[i] = max(0, min(100, v[i] + s["delta"]))
    return out

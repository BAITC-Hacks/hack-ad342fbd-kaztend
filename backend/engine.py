"""Движок симулятора «Аким на 5 часов» (HackAlem AI, спец-трек Astana Innovations).
Детерминированный расчёт Astana Quality of Life Score по ТЗ. LLM числа не считает."""
from __future__ import annotations
from dataclasses import dataclass

H = 8
BUDGET = 100
N_DECISIONS = 5
MAX_PER_DIRECTION = 2
CRIT_THRESHOLD = 40

INDICATORS = ["T1","T2","E1","E2","S1","S2","B1","B2","C1","C2"]
WEIGHTS = dict(zip(INDICATORS, [0.10,0.10,0.09,0.11,0.11,0.11,0.09,0.09,0.10,0.10]))
INDICATOR_NAMES = {
 "T1":"Разгрузка дорог","T2":"Доступность общественного транспорта","E1":"Озеленение","E2":"Качество воздуха",
 "S1":"Школы и детсады","S2":"Поликлиники и первичная медпомощь","B1":"Безопасность улиц",
 "B2":"Безопасность дорожного движения","C1":"Надёжность ЖКХ","C2":"Скорость решения обращений жителей"}

DISTRICTS = {
 "Есиль":    (0.27, [45,62,68,72,48,55,78,60,75,70]),
 "Алматы":   (0.24, [40,75,50,55,60,65,62,52,50,60]),
 "Сарыарка": (0.20, [50,70,42,40,62,68,58,55,45,55]),
 "Байконур": (0.13, [52,68,55,50,58,60,52,58,55,58]),
 "Нура":     (0.16, [55,40,45,65,38,35,55,50,60,50]),
}
DISTRICT_PROFILES = {
 "Есиль":"богатый, но с пробками на мостах и переполненными школами",
 "Алматы":"старый ЖКХ и пробки","Сарыарка":"смог от частного сектора, слабое озеленение",
 "Байконур":"середняк без ярких перекосов","Нура":"главный «аутсайдер» по соцсфере и транспорту"}

@dataclass(frozen=True)
class Measure:
    id: str; direction: str; name: str; scope: str; cost: int; lag: int; effects: dict

MEASURES = {m.id: m for m in [
 Measure("M1","Транспорт","Выделенные полосы для автобусов","Район",18,2,{"T1":6,"T2":9}),
 Measure("M2","Транспорт","Умные светофоры (адаптивное управление)","Город",22,2,{"T1":4,"B2":3}),
 Measure("M3","Транспорт","Линия ЛРТ / расширение","Район",30,4,{"T1":16,"T2":20,"E2":4}),
 Measure("M4","Экология","Парк / сквер","Район",15,2,{"E1":12,"E2":3,"B1":2}),
 Measure("M5","Экология","Перевод частного сектора на чистое топливо","Район",25,3,{"E2":14,"C1":4}),
 Measure("M6","Экология","Городская программа озеленения и ветрозащитных полос","Город",20,4,{"E1":5,"E2":3}),
 Measure("M7","Соцсфера","Школа + детсад (модульное строительство)","Район",24,3,{"S1":16}),
 Measure("M8","Соцсфера","Центр семейного здоровья / поликлиника","Район",20,3,{"S2":14}),
 Measure("M9","Соцсфера","Дворовые спорт-хабы","Район",10,1,{"S1":3,"S2":3,"B1":3}),
 Measure("M10","Безопасность","Освещение и камеры (расширение Safe City)","Район",12,1,{"B1":12,"B2":2}),
 Measure("M11","Безопасность","Безопасные переходы и школьные зоны","Район",10,1,{"B2":12,"T1":-2}),
 Measure("M12","Сервисы","Единая цифровая платформа обращений","Город",14,1,{"C2":5}),
 Measure("M13","Сервисы","Модернизация тепло- и водосетей","Район",28,4,{"C1":18,"E2":2}),
 Measure("M14","Сервисы","Аварийные бригады ЖКХ + раннее оповещение","Город",16,1,{"C1":5,"C2":2}),
]}
SYNERGIES = {("M1","M2"):("T1",2), ("M10","M12"):("B1",2), ("M5","M6"):("E2",2)}
INCOMPAT_ANY = [("M1","M3")]
INCOMPAT_SAME_DISTRICT = [("M4","M7"),("M5","M13")]

@dataclass
class Decision:
    measure: str
    district: str | None = None

def validate(decisions: list[Decision]) -> list[str]:
    errs = []
    ids = [d.measure for d in decisions]
    if len(decisions) != N_DECISIONS:
        errs.append(f"Решений должно быть ровно {N_DECISIONS}, сейчас {len(decisions)}")
    for d in decisions:
        if d.measure not in MEASURES:
            errs.append(f"Неизвестное мероприятие {d.measure}"); continue
        m = MEASURES[d.measure]
        if m.scope == "Район" and d.district not in DISTRICTS:
            errs.append(f"{m.id} ({m.name}): нужно указать район")
        if m.scope == "Город" and d.district:
            errs.append(f"{m.id} ({m.name}): мера городская, район не указывается")
    if len(set(ids)) != len(ids):
        errs.append("Повторы запрещены: каждое мероприятие максимум один раз")
    cost = sum(MEASURES[i].cost for i in ids if i in MEASURES)
    if cost > BUDGET:
        errs.append(f"Превышен бюджет: {cost} > {BUDGET}")
    dirs: dict[str,int] = {}
    for i in ids:
        if i in MEASURES: dirs[MEASURES[i].direction] = dirs.get(MEASURES[i].direction,0)+1
    for k,v in dirs.items():
        if v > MAX_PER_DIRECTION: errs.append(f"Не более {MAX_PER_DIRECTION} мер из направления «{k}» (выбрано {v})")
    for a,b in INCOMPAT_ANY:
        if a in ids and b in ids: errs.append(f"Несовместимы {a} и {b} (либо BRT, либо ЛРТ)")
    by_id = {d.measure: d for d in decisions}
    for a,b in INCOMPAT_SAME_DISTRICT:
        if a in by_id and b in by_id and by_id[a].district == by_id[b].district:
            errs.append(f"Несовместимы {a} и {b} в одном районе ({by_id[a].district})")
    return errs

def simulate(decisions: list[Decision]) -> dict:
    errs = validate(decisions)
    if errs:
        return {"valid": False, "errors": errs}
    new = {d: list(v) for d,(_,v) in DISTRICTS.items()}
    contrib = []
    by_id = {d.measure: d for d in decisions}
    for d in decisions:
        m = MEASURES[d.measure]; share = (H - m.lag)/H
        targets = [d.district] if m.scope == "Район" else list(DISTRICTS)
        for dist in targets:
            for k,eff in m.effects.items():
                delta = eff*share
                new[dist][INDICATORS.index(k)] += delta
                contrib.append((m.id, dist, k, round(delta,3)))
    for (a,b),(k,bonus) in SYNERGIES.items():
        if a in by_id and b in by_id:
            dist = by_id[a].district if MEASURES[a].scope=="Район" else None
            targets = [dist] if dist else list(DISTRICTS)
            for t in targets:
                new[t][INDICATORS.index(k)] += bonus
                contrib.append((f"синергия {a}+{b}", t, k, bonus))
    for dist in new:
        new[dist] = [min(100,max(0,x)) for x in new[dist]]
    d_scores = {dist: sum(WEIGHTS[k]*new[dist][i] for i,k in enumerate(INDICATORS)) for dist in new}
    d_avg = sum(DISTRICTS[dist][0]*d_scores[dist] for dist in new)
    d_min = min(d_scores.values())
    n_crit = sum(1 for dist in new for x in new[dist] if x < CRIT_THRESHOLD)
    crit = [(dist,k) for dist in new for i,k in enumerate(INDICATORS) if new[dist][i] < CRIT_THRESHOLD]
    score = 0.7*d_avg + 0.3*d_min - 1.0*n_crit
    cost = sum(MEASURES[d.measure].cost for d in decisions)
    return {"valid": True, "score": round(score,2), "cost": cost, "budget_left": BUDGET-cost,
            "d_avg": round(d_avg,2), "d_min": round(d_min,2), "n_crit": n_crit, "critical": crit,
            "district_scores": {k: round(v,2) for k,v in d_scores.items()},
            "indicators": {d: dict(zip(INDICATORS,[round(x,2) for x in v])) for d,v in new.items()},
            "contributions": contrib}

def baseline() -> dict:
    d_scores = {d: sum(WEIGHTS[k]*v[i] for i,k in enumerate(INDICATORS)) for d,(_,v) in DISTRICTS.items()}
    d_avg = sum(DISTRICTS[d][0]*d_scores[d] for d in d_scores)
    n_crit = sum(1 for _,v in DISTRICTS.values() for x in v if x < CRIT_THRESHOLD)
    return {"score": round(0.7*d_avg+0.3*min(d_scores.values())-n_crit,2), "d_avg": round(d_avg,2),
            "d_min": round(min(d_scores.values()),2), "n_crit": n_crit, "district_scores": {k:round(v,2) for k,v in d_scores.items()}}

if __name__ == "__main__":
    print("BASE:", baseline())
    sample = [Decision("M7","Нура"),Decision("M8","Нура"),Decision("M10","Нура"),Decision("M12"),Decision("M5","Сарыарка")]
    r = simulate(sample); print("SAMPLE (ТЗ: cost 95, Score~56.5):", r["cost"], r["score"], r["district_scores"])

"""Брифинг для акима по сценарию — Markdown (опция ТЗ «автоматическая генерация краткой презентации»)."""
import engine, analytics
from engine import MEASURES, INDICATOR_NAMES

def scenario_report(decisions, explanation: dict | None = None, event: dict | None = None, districts=None, team: str = "") -> str:
    a = analytics.analyze(decisions, districts)
    if not a["valid"]:
        return "# Сценарий недопустим\n\n" + "\n".join(f"- {e}" for e in a["errors"])
    r, b, eq, sens, ce = a["result"], a["baseline"], a["equity"], a["sensitivity"], a["cost_effectiveness"]
    lines = [f"# Брифинг: сценарий развития Астаны{(' — команда ' + team) if team else ''}", ""]
    if event:
        lines += [f"**Событие:** {event['name']} — {event['description']}", ""]
    lines += ["## Итог", f"- Astana Quality of Life Score: **{r['score']}** (база {b['score']}, {r['score']-b['score']:+.2f})",
              f"- Стоимость: {r['cost']} из {engine.BUDGET} у.е., остаток {r['budget_left']}",
              f"- Средний по городу D_avg: {r['d_avg']} · слабейший район: {eq['weakest_after']} ({r['d_min']}) · критических значений: {r['n_crit']} (было {b['n_crit']})", "",
              "## Решения", "| # | Мера | Район | Стоимость | Лаг | Вклад в Score | Score на у.е. |", "|---|---|---|---|---|---|---|"]
    for i, c in enumerate(sorted(ce, key=lambda x: int(x["measure"][1:])), 1):
        lines.append(f"| {i} | {c['measure']} {c['name']} | {c['district'] or 'город'} | {c['cost']} | {c['lag']} кв. | {c['score_gain']:+.3f} | {c['gain_per_unit']:.4f} |")
    lines += ["", "## Районы", "| Район | До | После | Δ |", "|---|---|---|---|"]
    for d in r["district_scores"]:
        lines.append(f"| {d} | {b['district_scores'][d]} | {r['district_scores'][d]} | {r['district_scores'][d]-b['district_scores'][d]:+.2f} |")
    lines += ["", "## Равенство и робастность",
              f"- Разрыв между лучшим и худшим районом: {eq['before']['gap']} → {eq['after']['gap']} ({eq['gap_change']:+.2f}); Джини {eq['before']['gini']} → {eq['after']['gini']}",
              f"- Устойчивость к весам (OECD/JRC, ±20% по направлениям): выигрыш от {sens['min_gain']:+.2f} до {sens['max_gain']:+.2f} — {'устойчив' if sens['robust'] else 'НЕ устойчив'}", ""]
    if r["critical"]:
        lines += ["## Критические значения после мер", *[f"- {d}: {INDICATOR_NAMES[k]}" for d, k in r["critical"]], ""]
    if explanation:
        lines += ["## AI-анализ", explanation.get("summary", ""), ""]
        for title, key in (("Сильные стороны", "strengths"), ("Риски", "risks"), ("Последствия", "consequences"), ("Компромиссы", "tradeoffs")):
            if explanation.get(key): lines += [f"**{title}**", *[f"- {x}" for x in explanation[key]], ""]
        if explanation.get("recommendation"): lines += ["**Рекомендация**", explanation["recommendation"], ""]
    lines += ["---", "Методология: детерминированная модель по ТЗ (линейная агрегация 0.7·D_avg + роулсианский член 0.3·min D − штраф за значения <40), "
              "робастность по OECD/JRC Handbook on Constructing Composite Indicators (2008), индикаторы соотнесены с темами ISO 37120:2018."]
    return "\n".join(lines)

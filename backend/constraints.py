"""Ограничения советника поверх неизменных правил ТЗ."""
import re
import engine

DISTRICT_PATTERNS = {
    "Нура": r"\b(?:нур|нұр)[\w]*",
    "Есиль": r"\b(?:есил|есіл)[\w]*",
    "Алматы": r"\bалмат[\w]*",
    "Сарыарка": r"\bсарыар[кқ][\w]*",
    "Байконур": r"\b(?:байкон|байқоң)[\w]*",
}
DIRECTION_PATTERNS = {
    "Транспорт": r"транспорт|\bдорог(?:а|и|у|е|ой|ах|ам)?\b|автобус|көлік|жолдар",
    "Экология": r"эколог|воздух|озелен|ауаның|ауа сапа|көгал",
    "Соцсфера": r"соцсфер|школ|детсад|поликлиник|әлеуметтік|мектеп|емхана",
    "Безопасность": r"безопасност|освещен|қауіпсіз",
    "Сервисы": r"жкх|сервис|теплосет|водосет|ткш|қызмет",
}


def parse_constraints(message, current=None):
    text = message.lower()
    # Число после ограничения, либо перед казахским «аспасын / дейін».
    patterns = [
        r"(?:не\s+(?:больше|более|выше)|не\s+выходить\s+за|максимум|\bдо\b|бюджет\w*|≤|<=)\D{0,12}?(-?\d{1,4})(?!\d)",
        r"(-?\d{1,4})\s*(?:у\.?\s*е\.?|ш\.?\s*б\.?|бірлік)?\s*(?:-?(?:ден|дан|тен|тан|нен|нан))?\s*(?:аспа\w*|дейін)",
        r"(-?\d{1,4})\s*(?:у\.?\s*е\.?|ш\.?\s*б\.?)",
    ]
    budgets = [int(m.group(1)) for pattern in patterns for m in re.finditer(pattern, text)]
    return {
        "budget": max(0, min([engine.BUDGET, *budgets])),
        "focus_district": next((d for d, p in DISTRICT_PATTERNS.items() if re.search(p, text)), None),
        "directions": [d for d, p in DIRECTION_PATTERNS.items() if re.search(p, text)],
        "improve_current": bool(current) and any(w in text for w in ("улучш", "доработ", "жақсарт", "лучше", "оптимиз")),
    }


def matches(decisions, budget=engine.BUDGET, focus_district=None, directions=()):
    """Фокус = минимум две районные меры; направление = хотя бы одна мера.

    Если заданы и район, и направление, соответствующая мера адресует этот район.
    Эти условия видны в интерфейсе и не меняют правила допустимости ТЗ.
    """
    if sum(engine.MEASURES[d.measure].cost for d in decisions) > budget:
        return False
    if focus_district and sum(d.district == focus_district for d in decisions) < 2:
        return False
    for direction in directions:
        if not any(engine.MEASURES[d.measure].direction == direction
                   and (not focus_district or d.district == focus_district) for d in decisions):
            return False
    return True


def errors(decisions, constraints):
    out = engine.validate(decisions)
    if out:
        return out
    if not matches(decisions, constraints["budget"], constraints.get("focus_district"), constraints.get("directions", ())):
        out.append("Набор не соответствует бюджету, району или направлениям из условий пользователя.")
    return out

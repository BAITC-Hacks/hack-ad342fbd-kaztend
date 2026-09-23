"""Проверка движка на контрольных числах из ТЗ Astana Innovations."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from engine import Decision, simulate, baseline, validate

def test_baseline_matches_tz():
    b = baseline()
    assert b["score"] == 52.56 and b["d_avg"] == 56.86 and b["d_min"] == 49.18 and b["n_crit"] == 2
    assert b["district_scores"] == {"Есиль":62.99,"Алматы":57.06,"Сарыарка":54.65,"Байконур":56.63,"Нура":49.18}

def test_sample_set_from_tz():
    s = [Decision("M7","Нура"),Decision("M8","Нура"),Decision("M10","Нура"),Decision("M12"),Decision("M5","Сарыарка")]
    r = simulate(s)
    assert r["valid"] and r["cost"] == 95 and abs(r["score"] - 56.5) < 0.1
    assert any(c[0] == "синергия M10+M12" for c in r["contributions"])

def test_cheapest_valid_set():
    s = [Decision("M9","Нура"),Decision("M11","Нура"),Decision("M10","Нура"),Decision("M12"),Decision("M4","Нура")]
    r = simulate(s); assert r["valid"] and r["cost"] == 61

def test_rules():
    assert validate([Decision("M1","Есиль"),Decision("M3","Нура"),Decision("M12"),Decision("M14"),Decision("M9","Нура")])
    assert validate([Decision("M4","Нура"),Decision("M7","Нура"),Decision("M12"),Decision("M14"),Decision("M9","Есиль")])  # M4+M7 один район
    assert validate([Decision("M3","Нура"),Decision("M13","Нура"),Decision("M5","Есиль"),Decision("M7","Нура"),Decision("M8","Нура")])  # бюджет 127
    assert validate([Decision("M7","Нура"),Decision("M8","Нура"),Decision("M9","Нура"),Decision("M12"),Decision("M14")])  # 3 меры соцсферы
    assert validate([Decision("M12"),Decision("M14"),Decision("M2"),Decision("M6")])  # 4 решения
    assert validate([Decision("M12","Нура"),Decision("M14"),Decision("M2"),Decision("M6"),Decision("M9","Нура")])  # район у городской меры
    assert not validate([Decision("M2"),Decision("M3","Нура"),Decision("M8","Нура"),Decision("M9","Нура"),Decision("M14")])

def test_score_changes_with_decisions():
    a = simulate([Decision("M7","Нура"),Decision("M8","Нура"),Decision("M10","Нура"),Decision("M12"),Decision("M5","Сарыарка")])["score"]
    b = simulate([Decision("M7","Есиль"),Decision("M8","Нура"),Decision("M10","Нура"),Decision("M12"),Decision("M5","Сарыарка")])["score"]
    assert a != b

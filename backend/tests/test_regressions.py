import asyncio
import json
from itertools import islice
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
import engine
import analytics
import agent
import constraints
import events
import optimizer
import search
import app as app_module

SAMPLE = [engine.Decision("M7", "Нура"), engine.Decision("M8", "Нура"),
          engine.Decision("M10", "Нура"), engine.Decision("M12"), engine.Decision("M5", "Сарыарка")]


def payload(decisions=SAMPLE, event=None):
    return {"decisions": [vars(d) for d in decisions], "event": event}


@pytest.mark.parametrize("message,budget,focus,directions", [
    ("не больше 5", 5, None, []),
    ("бюджет -5", 0, None, []),
    ("Подбери более дорогие меры, до 95", 95, None, []),
    ("не выходить за 85 у.е.", 85, None, []),
    ("Улучши мой набор, не больше 80", 80, None, []),
    ("Нұраға көмектес, 80-нен аспасын", 80, "Нура", []),
    ("Приоритет — экология и качество воздуха в Сарыарке, бюджет 100", 100, "Сарыарка", ["Экология"]),
    ("Школы в Есиле, до 90", 90, "Есиль", ["Соцсфера"]),
    ("Алматы, бюджет 60", 60, "Алматы", []),
])
def test_understands_user_constraints(message, budget, focus, directions):
    c = constraints.parse_constraints(message, SAMPLE)
    assert (c["budget"], c["focus_district"], c["directions"]) == (budget, focus, directions)


@pytest.mark.parametrize("event", [None, *[e["id"] for e in events.EVENTS]])
@pytest.mark.parametrize("decisions", [
    SAMPLE,
    [engine.Decision("M7", "Нура"), engine.Decision("M8", "Нура"), engine.Decision("M11", "Алматы"), engine.Decision("M12"), engine.Decision("M14")],
    [engine.Decision("M1", "Нура"), engine.Decision("M8", "Нура"), engine.Decision("M9", "Нура"), engine.Decision("M10", "Нура"), engine.Decision("M12")],
])
def test_attribution_reconciles_and_is_order_independent(event, decisions):
    districts = events.apply_event(events.get_event(event)) if event else None
    result, base = engine.simulate(decisions, districts), engine.baseline(districts)
    ce = analytics.cost_effectiveness(decisions, districts)
    assert sum(c["score_gain"] for c in ce) == pytest.approx(result["score"]-base["score"], abs=0.001)
    reversed_ce = analytics.cost_effectiveness(list(reversed(decisions)), districts)
    assert {c["measure"]: c["score_gain"] for c in ce} == {c["measure"]: c["score_gain"] for c in reversed_ce}


def test_new_penalty_is_charged_to_responsible_measure():
    ds = [engine.Decision("M7", "Нура"), engine.Decision("M8", "Нура"), engine.Decision("M11", "Алматы"), engine.Decision("M12"), engine.Decision("M14")]
    ce = {c["measure"]: c for c in analytics.cost_effectiveness(ds)}
    assert ce["M11"]["penalty_credit"] == -1
    assert ce["M11"]["score_gain"] < 0
    assert sum(c["score_gain"] for c in ce.values()) == pytest.approx(3.03)
    assert engine.simulate(ds[:4])["valid"] is False


def test_attribution_handles_clipping():
    districts = {d: (p, [99.0]*10) for d, (p, _) in engine.DISTRICTS.items()}
    ds = [engine.Decision("M2"), engine.Decision("M6"), engine.Decision("M12"), engine.Decision("M14"), engine.Decision("M11", "Нура")]
    ce = analytics.cost_effectiveness(ds, districts)
    assert sum(c["score_gain"] for c in ce) == pytest.approx(engine.simulate(ds, districts)["score"]-engine.baseline(districts)["score"], abs=0.001)


def test_attribution_handles_change_of_weakest():
    districts = {d: (p, [v+4 if d == "Нура" else v for v in values]) for d, (p, values) in engine.DISTRICTS.items()}
    before = engine.baseline(districts)
    after = engine.simulate(SAMPLE, districts)
    assert min(before["district_scores"], key=before["district_scores"].get) != min(after["district_scores"], key=after["district_scores"].get)
    assert sum(c["score_gain"] for c in analytics.cost_effectiveness(SAMPLE, districts)) == pytest.approx(after["score"]-before["score"], abs=0.001)


@pytest.fixture
def small_search(monkeypatch, tmp_path):
    """Небольшое пространство с настоящими расчётами для проверки маршрутизации/поиска."""
    data = json.loads((Path(__file__).resolve().parents[2]/"data/pareto.json").read_text(encoding="utf-8"))
    candidates = [[engine.Decision(**d) for d in item["decisions"]] for item in data["front"]]
    candidates += [SAMPLE, [engine.Decision("M4", "Сарыарка"), engine.Decision("M5", "Сарыарка"),
                           engine.Decision("M8", "Нура"), engine.Decision("M9", "Нура"), engine.Decision("M12")]]
    def enumerate_small(focus=None, directions=()):
        yield from (ds for ds in candidates if constraints.matches(ds, focus_district=focus, directions=directions))
    monkeypatch.setattr(optimizer, "enumerate_valid", enumerate_small)
    monkeypatch.setattr(search, "DATA", tmp_path)
    search.get_cache.cache_clear()
    yield candidates
    search.get_cache.cache_clear()


def test_search_and_cache_are_specific_to_event_and_priorities(small_search):
    for event in [None, *[e["id"] for e in events.EVENTS]]:
        districts = events.apply_event(events.get_event(event)) if event else None
        cache = search.get_cache(event)
        expected = max(engine.simulate(ds, districts)["score"] for ds in small_search)
        assert cache["best_under_budget"]["100"]["score"] == expected
        assert cache["event"] == event
        for item in cache["sets"] + cache["front"]:
            assert engine.simulate([engine.Decision(**d) for d in item["decisions"]], districts)["score"] == item["score"]
    focused = search.get_cache("smog", "Сарыарка", ("Экология",))
    for item in focused["front"]:
        assert constraints.matches([engine.Decision(**d) for d in item["decisions"]], focus_district="Сарыарка", directions=["Экология"])
    search.get_cache.cache_clear()
    assert search.get_cache("smog", "Сарыарка", ("Экология",)) == focused


def test_api_propagates_events_and_constraints(small_search):
    with TestClient(app_module.app) as client:
        for event in ["winter", "smog"]:
            districts = events.apply_event(events.get_event(event))
            advice = client.post("/api/advise", json=payload(event=event)).json()
            pareto = client.get("/api/pareto", params={"event": event, "budget": 80}).json()
            reply = client.post("/api/agent", json={"message": "не больше 80", "event": event}).json()
            assert reply["event"]["id"] == event and reply["result"]["cost"] <= 80
            assert reply["result"] == json.loads(json.dumps(engine.simulate([engine.Decision(**d) for d in reply["decisions"]], districts)))
            for item in advice["top_sets"]["sets"] + pareto["front"]:
                assert item["score"] == engine.simulate([engine.Decision(**d) for d in item["decisions"]], districts)["score"]
        for path in ["/api/agent", "/api/advise"]:
            assert client.post(path, json={**payload(event="missing"), "message": "test"}).status_code == 404
        assert client.get("/api/pareto?event=missing").status_code == 404


def test_improvement_never_relaxes_user_budget(small_search):
    reply = agent.fallback("Улучши мой набор, не больше 80", payload()["decisions"])
    assert engine.simulate([engine.Decision(**d) for d in reply["decisions"]])["cost"] <= 80
    for item in next(t for t in reply["trace"] if t["tool"] == "improve")["output"]["improvements"]:
        assert item["cost"] <= 80


def test_impossible_budget_is_not_reported_as_missing_cache():
    reply = agent.fallback("не больше 60", None)
    assert reply["decisions"] == [] and reply["minimum_cost"] == 61
    assert "кэш" not in reply["answer"]


def test_llm_final_cannot_bypass_constraints(monkeypatch, small_search):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(agent, "openai_key", lambda: "test-only")
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs):
            assert kwargs["json"]["input"][0]["content"]
            class Response:
                def raise_for_status(self): pass
                def json(self):
                    final = {"decisions": payload()["decisions"], "answer": "Стоимость 95", "rationale": "", "tradeoffs": []}
                    return {"output": [{"content": [{"type": "output_text", "text": json.dumps(final)}]}]}
            return Response()
    monkeypatch.setattr(agent.httpx, "AsyncClient", Client)
    out = asyncio.run(agent.run_agent("не больше 80", None, event="smog"))
    assert out["source"] == "deterministic"
    ds = [engine.Decision(**d) for d in out["decisions"]]
    assert engine.simulate(ds)["cost"] <= 80


def test_manual_constraints_and_report_snapshot(small_search):
    with TestClient(app_module.app) as client:
        reply = client.post("/api/agent", json={"message": "максимум", "event": "smog",
            "constraints": {"budget": 90, "focus_district": "Сарыарка", "directions": ["Экология"]}}).json()
        assert reply["result"]["valid"] and reply["result"]["cost"] <= 90
        assert sum(d["district"] == "Сарыарка" for d in reply["decisions"]) >= 2
        explained = client.post("/api/explain", json=payload()).json()
        report = {**payload(), "explanation": explained["explanation"], "explanation_scenario_id": explained["scenario_id"]}
        assert client.post("/api/report", json=report).status_code == 200
        assert client.post("/api/report", json={**report, "event": "winter"}).status_code == 409
        changed = json.loads(json.dumps(report)); changed["decisions"][0]["district"] = "Есиль"
        assert client.post("/api/report", json=changed).status_code == 409
        assert client.post("/api/agent", json={"message": "test", "constraints": {"budget": 101}}).status_code == 422
        assert client.post("/api/agent", json={"message": "test", "constraints": {"focus_district": "unknown"}}).status_code == 422

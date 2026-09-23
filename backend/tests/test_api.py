import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fastapi.testclient import TestClient
import app as app_module

SAMPLE = {"decisions": [{"measure":"M7","district":"Нура"},{"measure":"M8","district":"Нура"},{"measure":"M10","district":"Нура"},{"measure":"M12"},{"measure":"M5","district":"Сарыарка"}]}
BAD = {"decisions": [{"measure":"M1","district":"Есиль"},{"measure":"M3","district":"Нура"},{"measure":"M12"},{"measure":"M14"},{"measure":"M9","district":"Нура"}]}

def client():
    return TestClient(app_module.app)

def test_catalog():
    with client() as c:
        r = c.get("/api/catalog"); assert r.status_code == 200
        j = r.json(); assert len(j["measures"]) == 14 and len(j["districts"]) == 5 and j["baseline"]["score"] == 52.56
        assert j["indicators"][0]["iso37120"] and j["measures"][0]["analog"] and len(j["events"]) >= 4

def test_simulate_sample_from_tz():
    with client() as c:
        r = c.post("/api/simulate", json=SAMPLE).json()
        assert r["valid"] and r["cost"] == 95 and 56.4 <= r["score"] <= 56.6 and r["baseline"]["score"] == 52.56

def test_invalid_set():
    with client() as c:
        v = c.post("/api/validate", json=BAD).json(); assert not v["valid"] and v["errors"]
        s = c.post("/api/simulate", json=BAD).json(); assert not s["valid"]

def test_budget_cannot_be_exceeded():
    with client() as c:
        over = {"decisions": [{"measure":"M3","district":"Нура"},{"measure":"M13","district":"Есиль"},{"measure":"M5","district":"Сарыарка"},{"measure":"M7","district":"Нура"},{"measure":"M8","district":"Алматы"}]}
        v = c.post("/api/validate", json=over).json(); assert not v["valid"] and any("бюджет" in e.lower() for e in v["errors"])

def test_explain_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with client() as c:
        r = c.post("/api/explain", json=SAMPLE).json()
        assert r["valid"] and r["explanation"]["summary"] and r["explanation"]["source"] == "deterministic"

def test_analyze():
    with client() as c:
        a = c.post("/api/analyze", json=SAMPLE).json()
        assert a["valid"] and a["sensitivity"]["robust"] and a["equity"]["after"]["gini"] < a["equity"]["before"]["gini"]
        assert len(a["cost_effectiveness"]) == 5 and abs(sum(x["score_gain"] for x in a["cost_effectiveness"]) - 3.98) < 0.05

def test_event_changes_score():
    with client() as c:
        ev = c.post("/api/simulate", json={**SAMPLE, "event": "winter"}).json()
        assert ev["valid"] and ev["event"]["id"] == "winter" and ev["score"] != 56.54 and ev["baseline"]["score"] < 52.56
        assert c.post("/api/simulate", json={**SAMPLE, "event": "nope"}).status_code == 404

def test_advise_and_pareto():
    with client() as c:
        r = c.post("/api/advise", json=SAMPLE).json()
        assert isinstance(r["improvements"], list)
        p = c.get("/api/pareto?budget=80").json()
        if p["ready"]:
            assert p["best_under_budget"]["cost"] <= 80 and p["front"][0]["cost"] <= p["front"][-1]["cost"]

def test_agent_fallback(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with client() as c:
        r = c.post("/api/agent", json={"message": "Помоги району Нура, потрать не больше 80"}).json()
        assert r["source"] == "deterministic" and len(r["decisions"]) == 5 and r["result"]["valid"] and r["result"]["cost"] <= 80
        assert any(t["tool"] == "best_under_budget" for t in r["trace"])

def test_scenarios_and_report(tmp_path, monkeypatch):
    import store
    monkeypatch.setattr(store, "FILE", tmp_path / "scenarios.json"); monkeypatch.setattr(store, "DATA", tmp_path)
    with client() as c:
        s = c.post("/api/scenarios", json={"team": "Kaztend", **SAMPLE}).json(); assert s["score"] == 56.54
        assert c.get("/api/scenarios").json()["scenarios"][0]["team"] == "Kaztend"
        assert c.post("/api/scenarios", json={"team": "x", **BAD}).status_code == 400
        rep = c.post("/api/report", json={"team": "Kaztend", **SAMPLE}).text
        assert "56.54" in rep and "Равенство" in rep

def test_frontend_served():
    with client() as c:
        r = c.get("/"); assert r.status_code == 200 and "Аким" in r.text

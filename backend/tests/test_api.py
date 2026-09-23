import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from fastapi.testclient import TestClient
import app as app_module

client = TestClient(app_module.app)
SAMPLE = {"decisions": [{"measure":"M7","district":"Нура"},{"measure":"M8","district":"Нура"},{"measure":"M10","district":"Нура"},{"measure":"M12"},{"measure":"M5","district":"Сарыарка"}]}

def test_catalog():
    r = client.get("/api/catalog"); assert r.status_code == 200
    c = r.json(); assert len(c["measures"]) == 14 and len(c["districts"]) == 5 and c["baseline"]["score"] == 52.56

def test_simulate_sample():
    r = client.post("/api/simulate", json=SAMPLE).json()
    assert r["valid"] and r["cost"] == 95 and 56.4 <= r["score"] <= 56.6

def test_invalid_set():
    bad = {"decisions": [{"measure":"M1","district":"Есиль"},{"measure":"M3","district":"Нура"},{"measure":"M12"},{"measure":"M14"},{"measure":"M9","district":"Нура"}]}
    r = client.post("/api/validate", json=bad).json(); assert not r["valid"] and r["errors"]
    s = client.post("/api/simulate", json=bad).json(); assert not s["valid"]

def test_explain_demo_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    r = client.post("/api/explain", json=SAMPLE).json()
    assert r["valid"] and r["explanation"]["summary"] and r["explanation"]["source"] == "deterministic"

def test_advise_improvements():
    r = client.post("/api/advise", json=SAMPLE).json()
    assert isinstance(r["improvements"], list) and (not r["improvements"] or r["improvements"][0]["score"] > 56.54)

def test_frontend_served():
    r = client.get("/"); assert r.status_code == 200 and "Аким" in r.text

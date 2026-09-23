import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")

#!/usr/bin/env bash
cd "$(dirname "$0")/.."
PYTHON=python
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi
exec "$PYTHON" -m pytest -q backend/tests

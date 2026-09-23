#!/usr/bin/env bash
cd "$(dirname "$0")/.."
PYTHON=python
if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; fi
exec "$PYTHON" -m uvicorn backend.app:app --reload --port "${APP_PORT:-8000}"

#!/usr/bin/env bash
cd "$(dirname "$0")/.."
python -m uvicorn backend.app:app --reload --port ${APP_PORT:-8000}

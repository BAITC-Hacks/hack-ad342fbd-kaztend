#!/usr/bin/env bash
cd "$(dirname "$0")/.."
python -m pytest -q backend/tests

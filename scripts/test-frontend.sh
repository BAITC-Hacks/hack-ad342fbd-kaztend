#!/usr/bin/env bash
cd "$(dirname "$0")/.."
exec node --test tests/frontend-state.test.cjs

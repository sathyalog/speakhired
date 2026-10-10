#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
# Ollama is only used in Offline mode, so it is started only if it is installed
if command -v ollama >/dev/null; then (ollama list >/dev/null 2>&1 || (ollama serve >/dev/null 2>&1 &)); fi
trap 'kill 0' EXIT
uv run uvicorn speakhired.main:app --app-dir apps/api --host 127.0.0.1 --port 8100 &
(cd apps/web && npm run dev -- --host 127.0.0.1) &
wait

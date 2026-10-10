#!/usr/bin/env bash
# One-command setup.   ./scripts/setup.sh            Offline mode: Ollama on this computer (default)
#                      ./scripts/setup.sh --online   Online mode: Groq or Grok with your own key, no Ollama needed
set -euo pipefail
cd "$(dirname "$0")/.."
MODE=offline
for arg in "$@"; do
  case "$arg" in
    --online) MODE=online ;;
    --offline) MODE=offline ;;
    -h|--help) sed -n 2,4p "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (use --online or --offline)"; exit 1 ;;
  esac
done

command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }
command -v node >/dev/null || { echo "Install Node 20+ first: https://nodejs.org"; exit 1; }
if [ "$MODE" = offline ]; then
  command -v ollama >/dev/null || { echo "Offline mode needs Ollama: https://ollama.com  (or run ./scripts/setup.sh --online to use Groq or Grok instead)"; exit 1; }
fi

[ -f .env ] || cp .env.example .env
uv sync --extra voice --extra dev
(cd apps/web && npm install)
mkdir -p data

if [ "$MODE" = offline ]; then
  echo '{"mode": "offline"}' > data/mode.json
  uv run python -m speakhired.doctor
  MODEL=$(grep '^OLLAMA_MODEL=' .env | cut -d= -f2)
  ollama pull "${MODEL:-qwen3:4b}"
  echo "Done (Offline mode). Start with: ./scripts/run.sh"
else
  echo '{"mode": "online"}' > data/mode.json
  uv run python -m speakhired.doctor
  if ! grep -Eq '^EXTERNAL_API_KEY=.+' .env; then
    echo
    echo "One more step for Online mode: add your key to .env"
    echo "  1. Get a free key at https://console.groq.com (Groq), or https://console.x.ai (Grok)"
    echo "  2. Open .env and set EXTERNAL_API_KEY=your-key"
    echo "     (Groq is already the default address and model; for Grok, see the comments in .env)"
  fi
  echo "Done (Online mode). Start with: ./scripts/run.sh"
fi

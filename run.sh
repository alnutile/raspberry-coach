#!/usr/bin/env bash
# One command to launch the raspberry-coach UI. Sets up the environment on first
# run, then starts the local web app. Re-run it any time.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Install it first:"
  echo "  brew install uv        # macOS"
  echo "  curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux"
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "warning: ffmpeg not found on PATH — frame extraction will fail."
  echo "  install it with: brew install ffmpeg"
fi

# Self-contained Python + deps (skips work if already set up).
uv venv --python 3.12 .venv >/dev/null 2>&1 || true
uv pip install -q -r requirements.txt

# Make sure there's somewhere to put the API key.
if [ ! -f .env ]; then
  cp .env.example .env
  echo
  echo ">> Created .env — open it and paste your ANTHROPIC_API_KEY, then re-run ./run.sh"
  echo "   (get a key at https://console.anthropic.com)"
  exit 0
fi

if ! grep -q "sk-ant-" .env 2>/dev/null; then
  echo ">> Heads up: .env doesn't look like it has a real ANTHROPIC_API_KEY yet."
fi

echo
echo ">> Starting raspberry-coach at http://localhost:8000  (Ctrl-C to stop)"
echo
exec uv run uvicorn ui.app:app --host 127.0.0.1 --port 8000

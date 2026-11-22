#!/usr/bin/env bash
# Start the REAL (non-demo) Iran Tutor stack in GitHub Codespaces.
# Run from the repository root: bash scripts/run-codespaces-real.sh
#
# Required Codespaces secrets:
#   SECRET_KEY, AUTH_SECRET, ADMIN_PASSWORD, POSTGRES_PASSWORD
#
# Add AI provider URLs, models and API keys through the encrypted /admin vault.
# Do not put provider API keys in this script, .env files, or Git.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

for name in SECRET_KEY AUTH_SECRET ADMIN_PASSWORD POSTGRES_PASSWORD; do
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required Codespaces secret $name is missing from this terminal environment." >&2
    exit 1
  fi
done

if [[ "${#SECRET_KEY}" -lt 32 ]]; then
  echo "ERROR: SECRET_KEY must contain at least 32 characters." >&2
  exit 1
fi
if [[ "${#ADMIN_PASSWORD}" -lt 12 ]]; then
  echo "ERROR: ADMIN_PASSWORD must contain at least 12 characters." >&2
  exit 1
fi
if [[ "$SECRET_KEY" == "$AUTH_SECRET" ]]; then
  echo "ERROR: SECRET_KEY and AUTH_SECRET must be different values." >&2
  exit 1
fi

export APP_ENV="${APP_ENV:-local}"
export DEMO_MODE=false
export ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
# URL-encode the password because PostgreSQL URLs use reserved characters.
export DATABASE_URL="${DATABASE_URL:-$(python3 -c 'import os; from urllib.parse import quote; print("postgresql+asyncpg://iran_tutor:" + quote(os.environ["POSTGRES_PASSWORD"], safe="") + "@127.0.0.1:5432/iran_tutor")')}"
export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:6333}"
export VECTOR_BACKEND="${VECTOR_BACKEND:-qdrant}"
export EMBEDDING_DIMENSION="${EMBEDDING_DIMENSION:-1536}"

if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  export NEXT_ALLOWED_DEV_ORIGINS="${CODESPACE_NAME}-${FRONTEND_PORT}.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
fi

# Do not inherit an old Demo or legacy single-provider .env by accident.
# Managed endpoints, API keys and model names are configured through /admin.
export LLM_BASE_URL=""
export LLM_API_KEY=""
export TUTOR_MODEL=""
export VISION_MODEL_A=""
export VISION_MODEL_B=""
export VISION_MODEL_PRIMARY=""
export VISION_MODEL_ESCALATION=""
export SPEECH_TO_TEXT_MODEL=""
export SPEECH_SYNTHESIS_MODEL=""
export AUDIO_BASE_URL=""
export AUDIO_API_KEY=""
export EMBEDDING_BASE_URL=""
export EMBEDDING_API_KEY=""
export EMBEDDING_MODEL="${EMBEDDING_MODEL:-text-embedding-3-small}"

cd "$ROOT"

# Docker Compose reads the root .env. Write it with restrictive permissions.
# Single-quoted dotenv values prevent '$' and '#' from being interpreted.
umask 077
python3 - <<'PY'
import os
from pathlib import Path

password = os.environ["POSTGRES_PASSWORD"]
if "\n" in password or "\r" in password:
    raise SystemExit("POSTGRES_PASSWORD must not contain a newline")

escaped = password.replace("\\", "\\\\").replace("'", "\\'")
lines = [
    "POSTGRES_USER=iran_tutor",
    "POSTGRES_PASSWORD='" + escaped + "'",
    "POSTGRES_DB=iran_tutor",
]
Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
chmod 600 "$ROOT/.env"

echo "==> Starting PostgreSQL, Qdrant and Redis"
docker compose up -d --wait

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  echo "==> Creating backend virtual environment"
  python3 -m venv "$ROOT/backend/.venv"
fi

echo "==> Installing/verifying Python dependencies"
"$ROOT/backend/.venv/bin/python" -m pip install --upgrade pip
"$ROOT/backend/.venv/bin/python" -m pip install -r "$ROOT/backend/requirements.txt"

if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "==> Installing frontend dependencies"
  (cd "$ROOT/frontend" && npm ci --no-audit --no-fund)
fi

echo "==> Applying database migrations"
(cd "$ROOT/backend" && "$ROOT/backend/.venv/bin/alembic" upgrade head)

pids=()
cleanup() {
  echo
  echo "==> Stopping Iran Tutor application processes"
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]:-}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "==> Starting FastAPI on port $BACKEND_PORT"
(
  cd "$ROOT/backend"
  "$ROOT/backend/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port "$BACKEND_PORT"
) &
pids+=("$!")

echo "==> Starting Next.js on port $FRONTEND_PORT"
(
  cd "$ROOT/frontend"
  BACKEND_ORIGIN="http://127.0.0.1:$BACKEND_PORT" npm run dev -- --port "$FRONTEND_PORT"
) &
pids+=("$!")

echo
echo "Iran Tutor is running in REAL mode (DEMO_MODE=false)."
echo "Frontend: port $FRONTEND_PORT"
echo "Backend:  port $BACKEND_PORT (keep this port private)"
echo "After startup, open /admin and configure AI providers and feature routes."
echo "Use Ctrl+C to stop the application processes; Docker services remain running."
wait

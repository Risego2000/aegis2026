#!/usr/bin/env bash
# Arranque local completo (sin Docker): compila el cliente y sirve todo desde
# FastAPI en un único puerto -> http://localhost:8000
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> dependencias Python"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r backend/requirements.txt

echo "==> cliente Next.js"
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci --no-audit --no-fund)
fi
(cd frontend && npm run build)

echo "==> servidor"
cd backend
exec ../.venv/bin/python -m uvicorn app.main:app --host "${HOST:-0.0.0.0}" --port "${PORT:-8000}"

#!/usr/bin/env bash
# AEGIS · supervisor del backend
#
# El servidor de este proyecto es un proceso de larga vida. Si el entorno lo
# mata (suspensión del sandbox, OOM, un error no capturado en un pipeline),
# el puerto 8000 se queda vacío y la web "no carga". Este script lo mantiene
# vivo: reinicia uvicorn cuando sale, escribe logs con marca de tiempo y
# comprueba /api/health en cada vuelta.
#
#   bash scripts/serve.sh              # primer plano (Ctrl-C para parar)
#   nohup bash scripts/serve.sh &      # en segundo plano
#
# Variables: PORT (8000), HOST (0.0.0.0), LOG (logs/server.log)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
LOG="${LOG:-logs/server.log}"
mkdir -p "$(dirname "$LOG")"

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" | tee -a "$LOG" >&2; }

trap 'log "SIGTERM recibido, parando supervisor"; [ -n "${CHILD:-}" ] && kill "$CHILD" 2>/dev/null; exit 0' INT TERM

CRASHES=0
while true; do
  log "arrancando uvicorn en ${HOST}:${PORT} (reinicio nº${CRASHES})"
  ( cd backend && exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT" --log-level warning ) >>"$LOG" 2>&1 &
  CHILD=$!

  # espera a que el puerto responda (máx. 40 s)
  for _ in $(seq 1 40); do
    if curl -fsS -m 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      log "listo · http://127.0.0.1:${PORT}"
      break
    fi
    sleep 1
  done

  wait "$CHILD"
  CODE=$?
  CHILD=""
  if [ "$CODE" -eq 0 ]; then
    log "uvicorn terminó limpiamente (código 0); supervisor sale"
    exit 0
  fi
  CRASHES=$((CRASHES + 1))
  BACKOFF=$(( CRASHES > 5 ? 10 : 2 ))
  log "uvicorn cayó con código ${CODE}; reinicio en ${BACKOFF}s"
  sleep "$BACKOFF"
done

#!/usr/bin/env bash
# AEGIS · segundo túnel (dominio alternativo)
#
# Los Quick Tunnel de Cloudflare se cortan cada pocos minutos en este entorno
# (el connector pierde el edge y tarda 10-20 s en volver). Este script mantiene
# un túnel SSH independiente contra localhost.run, que usa otro transporte
# (SSH sobre TCP/22) y otro dominio (lhr.life), de modo que si Cloudflare falla
# el usuario tiene una segunda puerta que no comparte cuello de botella.
#
#   bash scripts/tunnel_backup.sh
#
# Variables: PORT (8000), URLFILE (LINK_LHR.txt), LOG (/tmp/lhr.log)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PORT="${PORT:-8000}"
URLFILE="${URLFILE:-LINK_LHR.txt}"
LOG="${LOG:-/tmp/lhr.log}"

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

for _ in $(seq 1 100); do
  # --- espera al backend --- #
  if ! curl -fsS -m 5 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    say "backend no disponible en :${PORT}; espero 5 s"
    sleep 5
    continue
  fi

  say "abriendo túnel SSH hacia localhost.run"
  : > "$LOG"
  ssh -T -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
      -o ExitOnForwardFailure=yes -o ConnectTimeout=20 \
      -R 80:localhost:"${PORT}" nokey@localhost.run >>"$LOG" 2>&1 &
  SSH=$!

  URL=""
  for _ in $(seq 1 45); do
    URL=$(grep -oE 'https://[a-z0-9]+\.(app\.)?lhr\.life' "$LOG" 2>/dev/null | head -1)
    [ -n "$URL" ] && break
    kill -0 "$SSH" 2>/dev/null || break
    sleep 1
  done

  if [ -z "$URL" ]; then
    say "localhost.run no dio URL; reintento en 5 s"
    kill "$SSH" 2>/dev/null; wait "$SSH" 2>/dev/null; sleep 5
    continue
  fi

  printf '%s\n' "$URL" > "$URLFILE"
  say "URL alternativa: $URL  (en $URLFILE)"

  # --- vigilancia: si el túnel SSH muere o deja de servir, se recicla --- #
  fails=0
  while kill -0 "$SSH" 2>/dev/null; do
    sleep 15
    kill -0 "$SSH" 2>/dev/null || break
    if curl -s -o /dev/null -m 12 -w '%{http_code}' "$URL/" | grep -q '^200$'; then
      [ "$fails" -gt 0 ] && say "alternativo recuperado"
      fails=0
    else
      fails=$((fails + 1))
      say "alternativo sin respuesta (fallo $fails)"
      if [ "$fails" -ge 4 ]; then
        say "recyclo el túnel SSH (cambiará la URL)"; kill "$SSH" 2>/dev/null; sleep 2; kill -9 "$SSH" 2>/dev/null; break
      fi
    fi
  done
  wait "$SSH" 2>/dev/null
  say "túnel SSH terminado; reabro en 3 s"
  sleep 3
done

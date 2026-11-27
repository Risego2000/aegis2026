#!/usr/bin/env bash
# AEGIS · túnel público con vigilancia
#
# Los Quick Tunnel de Cloudflare se caen de vez en cuando desde este entorno:
# la conexión con el edge muere en silencio (típico "Error 1033" en el navegador)
# y cloudflared tarda ~1-2 min en notarlo y reconectar. Ese reconnect NO cambia
# la URL, así que lo normal es que el enlace vuelva solo.
#
# Este script:
#   1. arranca cloudflared y escribe la URL vigente en TUNNEL_URL.txt
#   2. sondea la URL pública cada 15 s y registra los cortes
#   3. solo recicla el proceso si de verdad ha muerto o lleva >3 min caído
#      (reciclar implica URL nueva, por eso se espera al auto-reconnect)
#
#   bash scripts/tunnel_watch.sh
#
# Variables: PORT (8000), URLFILE (TUNNEL_URL.txt), LOG (/tmp/cloudflared.log)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PORT="${PORT:-8000}"
BIN="${CLOUDFLARED_BIN:-/tmp/cloudflared}"
URLFILE="${URLFILE:-LINK_CLOUDFLARE.txt}"
LOG="${LOG:-/tmp/cloudflared.log}"

say() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

if [ ! -x "$BIN" ]; then
  say "descargando cloudflared"
  curl -fsSL -o "$BIN" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x "$BIN" || { say "no se pudo descargar cloudflared"; exit 1; }
fi

probe() { # $1 = url
  local code
  code=$(curl -s -o /dev/null -m 12 -w '%{http_code}' "$1/")
  [ "$code" = "200" ]
}

while true; do
  if ! curl -fsS -m 5 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    say "el backend no responde aún en :${PORT}; espero 5 s"
    sleep 5
  else
    say "abriendo túnel hacia http://127.0.0.1:${PORT}"
    # Ojo: --region eu NO funciona con Quick Tunnels (_eu-v2-origintunneld no
    # resuelve y cloudflared sale con código 1). Se deja la región global.
    "$BIN" tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate \
      --http-host-header "localhost:${PORT}" \
      --protocol http2 --retries 10 >"$LOG" 2>&1 &
    CF=$!

    URL=""
    for _ in $(seq 1 40); do
      URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)
      [ -n "$URL" ] && break
      kill -0 "$CF" 2>/dev/null || break
      sleep 1
    done

    if [ -n "$URL" ]; then
      printf '%s\n' "$URL" > "$URLFILE"
      say "URL pública: $URL  (guardada en $URLFILE)"
    else
      say "cloudflared no dio URL; reintento en 5 s"
      kill "$CF" 2>/dev/null; wait "$CF" 2>/dev/null; sleep 5; continue
    fi

    # --- vigilancia -------------------------------------------------------
    fails=0
    while kill -0 "$CF" 2>/dev/null; do
      sleep 15
      kill -0 "$CF" 2>/dev/null || break
      if probe "$URL"; then
        [ "$fails" -gt 0 ] && say "recuperado tras ${fails} fallo(s)"
        fails=0
      else
        fails=$((fails + 1))
        say "la URL no responde (fallo ${fails}); cloudflared debería reconectar solo"
        if [ "$fails" -ge 12 ]; then       # ~3 min caído: reciclar
          say "3 min sin servicio: reciclo el túnel (la URL cambiará)"
          kill "$CF" 2>/dev/null; sleep 3; kill -9 "$CF" 2>/dev/null
          break
        fi
      fi
    done
    wait "$CF" 2>/dev/null
    say "cloudflared terminó (código $?); reabro en 3 s"
    sleep 3
  fi
done

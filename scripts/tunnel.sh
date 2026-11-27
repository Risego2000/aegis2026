#!/usr/bin/env bash
# AEGIS · túnel público temporal (para abrir la app desde el móvil o fuera de
# la red local). Usa Quick Tunnel de Cloudflare: no requiere cuenta ni dominio,
# pero la URL caduca cuando se para el proceso (y cambia en cada arranque).
#
#   bash scripts/tunnel.sh            # imprime la URL pública y la mantiene viva
#
# Requisitos: salida a internet. El binario se descarga solo en /tmp.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

PORT="${PORT:-8000}"
BIN="${CLOUDFLARED_BIN:-/tmp/cloudflared}"

if ! curl -fsS -m 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "El backend no responde en :${PORT}. Arráncalo primero:  make serve" >&2
  exit 1
fi

if [ ! -x "$BIN" ]; then
  echo "==> descargando cloudflared" >&2
  curl -fsSL -o "$BIN" \
    https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
    && chmod +x "$BIN" || { echo "no se pudo descargar cloudflared" >&2; exit 1; }
fi

echo "==> abriendo túnel hacia http://127.0.0.1:${PORT}" >&2
# Los Quick Tunnel (sin cuenta) no dan garantías de disponibilidad: con una
# sola conexión y QUIC sobre UDP inestable aparecen 1033 intermitentes.
# Cuatro conexiones redundantes y HTTP/2 sobre TCP lo estabilizan.
exec "$BIN" tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate \
  --http-host-header "localhost:${PORT}" \
  --ha-connections 4 --protocol http2 --retries 10

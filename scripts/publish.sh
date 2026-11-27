#!/usr/bin/env bash
# Publica el proyecto en el repositorio Aegis de risego2000.
#
#   TOKEN=ghp_xxx bash scripts/publish.sh          # con token (recomendado)
#   bash scripts/publish.sh                        # con tu clave SSH ya cargada
#
# El token necesita permiso "repo" (o "Contents: read and write" si es un token
# de grano fino). No se guarda en ningún sitio: solo se usa en la URL de push.
set -euo pipefail

OWNER="${OWNER:-risego2000}"
REPO="${REPO:-Aegis}"
BRANCH="${BRANCH:-main}"

cd "$(dirname "$0")/.."

echo "· repositorio: $OWNER/$REPO (rama $BRANCH)"

if [ -n "${TOKEN:-}" ]; then
  # el token va en la URL pero NO se escribe en .git/config
  git push "https://${OWNER}:${TOKEN}@github.com/${OWNER}/${REPO}.git" "HEAD:${BRANCH}"
else
  if [ -z "$(git remote get-url origin 2>/dev/null || true)" ]; then
    git remote add origin "git@github.com:${OWNER}/${REPO}.git"
  fi
  git push -u origin "HEAD:${BRANCH}"
fi

echo
echo "hecho. Comprueba en https://github.com/${OWNER}/${REPO}"

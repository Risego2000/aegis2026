#!/usr/bin/env python3
"""Comprobación de Browserless: abre una página pública en un navegador remoto.

Es el flujo de Playwright del proyecto contra Browserless (Chrome gestionado):
no lanza ningún navegador en local, se conecta por CDP al servicio y navega a
una página pública para confirmar que el token y la salida a Internet funcionan.

    export BROWSERLESS_TOKEN=...          # https://browserless.io/account/
    .venv/bin/python scripts/check_browserless.py
    .venv/bin/python scripts/check_browserless.py --url https://example.org

Códigos de salida: 0 si Browserless responde y la página carga, 1 si falta el
token o la página no carga, 2 si no se puede conectar al servicio. El token se
lee de BROWSERLESS_TOKEN y nunca se imprime.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:  # misma comodidad que backend/app/config.py: .env si está
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # pragma: no cover
    pass

# Región por defecto del quick start de Browserless (US Oeste). Se puede cambiar
# con --endpoint o BROWSERLESS_ENDPOINT (ver /baas/connection-url-patterns).
DEFAULT_ENDPOINT = "wss://production-sfo.browserless.io"
DEFAULT_URL = "https://example.com/"


def scrub(text: str, secret: str) -> str:
    """Quita el token de cualquier mensaje antes de imprimirlo."""
    return text.replace(secret, "***") if secret else text


def main() -> int:
    parser = argparse.ArgumentParser(description="Abre una página pública en un navegador remoto de Browserless.")
    parser.add_argument("--url", default=DEFAULT_URL, help=f"página a visitar (por defecto {DEFAULT_URL})")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("BROWSERLESS_ENDPOINT") or DEFAULT_ENDPOINT,
        help=f"endpoint CDP de Browserless (por defecto {DEFAULT_ENDPOINT})",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="segundos de espera por paso")
    args = parser.parse_args()

    token = (os.environ.get("BROWSERLESS_TOKEN") or "").strip()
    if not token:
        print("falta BROWSERLESS_TOKEN: crea un token en https://browserless.io/account/")
        print("y ponlo en .env (BROWSERLESS_TOKEN=...) o expórtalo en la shell.")
        return 1

    from playwright.sync_api import sync_playwright

    separator = "&" if "?" in args.endpoint else "?"
    endpoint = f"{args.endpoint.rstrip('/')}{separator}token={token}"
    timeout_ms = args.timeout * 1000

    with sync_playwright() as playwright:
        print(f"conectando a {args.endpoint} ...")
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint, timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            print(f"sin conexión con Browserless: {type(exc).__name__}: {scrub(str(exc), token)[:300]}")
            print("→ revisa el token, la cuota de la cuenta y la salida de red de esta máquina.")
            return 2

        try:
            context = browser.new_context()
            page = context.new_page()
            response = page.goto(args.url, wait_until="domcontentloaded", timeout=timeout_ms)
            print(f"HTTP {response.status if response else '?'} · {page.url}")
            print(f"título: {page.title()}")
        except Exception as exc:  # noqa: BLE001
            print(f"la página no cargó: {type(exc).__name__}: {scrub(str(exc), token)[:300]}")
            return 1
        finally:
            browser.close()

    print("→ Browserless respondió y el navegador remoto cargó la página.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

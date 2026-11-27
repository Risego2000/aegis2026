#!/usr/bin/env python3
"""Guardián de enlaces: comprueba desde fuera que las URLs públicas sirven.

Los túneles gratuitos se regeneran solos tras una caída, pero hasta ahora nadie
verificaba que el enlace que el usuario abre responde de verdad. Este vigilante
lo hace cada minuto:

  · sonda la raíz y /api/health de cada enlace de LINK_CLOUDFLARE.txt y LINK_LHR.txt;
  · mantiene el estado en data/health_links.json (para el panel de la app);
  · escribe data/alertas_enlace.log cuando un enlace falla o vuelve;
  · si un enlace falla 3 veces seguidas, lo marca y avisa por stdout;
  · una vez al día hace una copia consistente de la base de datos
    (data/backups/) y conserva las 7 últimas.

Uso:
    python3 scripts/guardian.py            # bucle continuo (cada 60 s)
    python3 scripts/guardian.py --once     # una sola pasada
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [ROOT / "LINK_CLOUDFLARE.txt", ROOT / "LINK_LHR.txt"]
STATE = ROOT / "data" / "health_links.json"
LOG = ROOT / "data" / "alertas_enlace.log"
INTERVAL = int(os.environ.get("GUARDIAN_INTERVAL", "60"))
TIMEOUT = float(os.environ.get("GUARDIAN_TIMEOUT", "20"))
DB = ROOT / "data" / "osint.db"
BACKUPS = ROOT / "data" / "backups"
KEEP_BACKUPS = 1
LAST_BACKUP = ROOT / "data" / ".last_backup"


def read_links() -> dict[str, str]:
    out: dict[str, str] = {}
    for f in FILES:
        try:
            url = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if url.startswith("http"):
            out[f.stem] = url
    return out


def probe(url: str, path: str = "/") -> tuple[bool, int, int]:
    started = time.perf_counter()
    try:
        req = urllib.request.Request(url.rstrip("/") + path, headers={"User-Agent": "AEGIS-Guardian/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = resp.read(4096)
            return True, resp.status, int((time.perf_counter() - started) * 1000)
    except Exception:  # noqa: BLE001
        return False, 0, int((time.perf_counter() - started) * 1000)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"links": {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def log(line: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {line}\n")


def backup_daily() -> None:
    """Copia consistente de SQLite (API de backup), comprimida y rotada.

    Se guarda solo la última y en gzip: la base ocupa 62 MB y el proyecto entero
    no puede pasar de 128 MB.
    """
    if not DB.exists():
        return
    try:
        today = time.strftime("%Y-%m-%d")
        if LAST_BACKUP.exists() and LAST_BACKUP.read_text().strip() == today:
            return
        import gzip

        BACKUPS.mkdir(parents=True, exist_ok=True)
        tmp = BACKUPS / f"osint-{today}.db"
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        dst = sqlite3.connect(tmp)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        gz = BACKUPS / f"osint-{today}.db.gz"
        with tmp.open("rb") as fin, gzip.open(gz, "wb", compresslevel=6) as fout:
            while chunk := fin.read(4 * 1024 * 1024):
                fout.write(chunk)
        tmp.unlink(missing_ok=True)
        # rotación: solo las más recientes (gzip incluido)
        old = sorted(BACKUPS.glob("osint-*.db*"))[:-KEEP_BACKUPS]
        for f in old:
            f.unlink(missing_ok=True)
        LAST_BACKUP.write_text(today)
        size_mb = gz.stat().st_size / 1e6
        log(f"copia de la base: {gz.name} ({size_mb:.1f} MB) · quedan {len(list(BACKUPS.glob('osint-*.db*')))}")
    except Exception as exc:  # noqa: BLE001
        log(f"copia de la base FALLÓ: {exc}")


def cycle(state: dict) -> bool:
    links = read_links()
    changed = False
    for name, url in links.items():
        ok_root, status, ms = probe(url, "/")
        ok_api, api_status, api_ms = probe(url, "/api/health") if ok_root else (False, 0, 0)
        entry = state["links"].setdefault(name, {"url": url, "ok": True, "fails": 0})
        was_ok = entry.get("ok", True)
        entry.update({
            "url": url,
            "ok": bool(ok_root and ok_api),
            "root_status": status,
            "api_status": api_status,
            "ms": ms,
            "api_ms": api_ms,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        if ok_root and ok_api:
            entry["fails"] = 0
            if not was_ok:
                log(f"{name} vuelve a responder · {url}")
                changed = True
        else:
            entry["fails"] = int(entry.get("fails", 0)) + 1
            if entry["fails"] >= 3 and was_ok:
                log(f"{name} NO responde ({entry['fails']} intentos, http {status}/{api_status}) · {url}")
                changed = True
        entry["ok"] = bool(ok_root and ok_api)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    save_state(state)
    return changed


def main() -> int:
    once = "--once" in sys.argv
    state = load_state()
    while True:
        try:
            cycle(state)
            backup_daily()
        except Exception as exc:  # noqa: BLE001
            log(f"guardian: {exc}")
        if once:
            print(json.dumps(state, ensure_ascii=False, indent=1))
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    sys.exit(main())

"""GDELT 2.0 — the 15-minute event stream, geolocated and de-duplicated.

Pipeline: poll `lastupdate.txt` -> download the current `.export.CSV.zip`
(~50-400 KB) -> parse the 61-column tab-separated CAMEO records -> keep only
events that (a) carry an ActionGeo point and (b) are material/verbal conflict
(QuadClass 3-4) or coercion/protest/violence root codes -> hand them to the
dedup layer, which fuses the same event reported by 40 outlets into a single
map pin with a mention counter.

Fields used: 26 EventCode, 28 EventRootCode, 29 QuadClass, 30 GoldsteinScale,
31 NumMentions, 32 NumSources, 34 AvgTone, 52 ActionGeo_Fullname,
56/57 ActionGeo lat/lon, 59 DATEADDED, 60 SOURCEURL.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from ..models import EventRecord, parse_dt
from .client import Fetcher
from .es import ACTOR_ES, ROOT_LABELS_ES, _actor_es, es_gdelt_title  # noqa: F401

log = logging.getLogger("aegis.gdelt")

LASTUPDATE = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"

ROOT_CODES = {
    "01": ("news", "public statement"),
    "02": ("news", "appeal"),
    "03": ("diplomacy", "intent to cooperate"),
    "04": ("diplomacy", "consultation"),
    "05": ("diplomacy", "diplomatic cooperation"),
    "06": ("economy", "material cooperation"),
    "07": ("economy", "provide aid"),
    "08": ("economy", "yield"),
    "09": ("diplomacy", "investigate"),
    "10": ("economy", "demand"),
    "11": ("economy", "disapprove"),
    "12": ("economy", "reject"),
    "13": ("conflict", "threaten"),
    "14": ("protest", "protest"),
    "15": ("military", "force posture"),
    "16": ("military", "reduce force posture"),
    "17": ("conflict", "coerce"),
    "18": ("conflict", "assault"),
    "19": ("conflict", "armed clash"),
    "20": ("conflict", "mass violence"),
}

# Etiquetas en español para los códigos raíz CAMEO: los titulares y los
# resúmenes se muestran en la interfaz, así que se redactan en español.
# Root codes that are interesting even when QuadClass says "verbal cooperation"
ALWAYS_KEEP = {"13", "14", "15", "16", "17", "18", "19", "20"}
MIN_QUADCLASS = 3

COUNTRY_ISO3 = {}  # FIPS -> ISO3 is not 1:1; we surface the FIPS code instead


def _f(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_export(text: str) -> list[EventRecord]:
    records: list[EventRecord] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 61:
            continue
        root = parts[28]
        quad = parts[29]
        try:
            quad_i = int(quad)
        except ValueError:
            quad_i = 0
        if quad_i < MIN_QUADCLASS and root not in ALWAYS_KEEP:
            continue
        lat, lon = _f(parts[56]), _f(parts[57])
        if lat is None or lon is None or (lat == 0 and lon == 0):
            continue
        url = parts[60].strip()
        if not url:
            continue
        place = parts[52] or parts[35]
        country = parts[53]
        actor1 = parts[6] or parts[5] or "?"
        actor2 = parts[16] or parts[15] or ""
        category, label = ROOT_CODES.get(root, ("news", "event"))
        when = parse_dt(parts[59]) or parse_dt(parts[1]) or datetime.now(timezone.utc)
        mentions = int(_f(parts[31]) or 1)
        sources = int(_f(parts[32]) or 1)
        tone = _f(parts[34]) or 0.0
        goldstein = _f(parts[30]) or 0.0

        place_short = place.split(",")[0].strip() if place else ""
        actors_part = ""
        if actor1 and actor1 != "?":
            actors_part = _actor_es(actor1) + (f" → {_actor_es(actor2)}" if actor2 else "")
        label_es = ROOT_LABELS_ES.get(label, label.title())
        title = f"{label_es}: {actors_part}".strip()
        if place_short:
            title = f"{title} · {place_short}" if actors_part else f"{label_es}: {place_short}"

        # Structural identity of the event, used by the dedup layer so that two
        # *different* CAMEO events in the same city never collapse into one.
        signature = f"{root}|{parts[5] or actor1}|{parts[15] or actor2}|{lat:.1f}|{lon:.1f}"

        summary = (
            f"CAMEO {parts[26]} ({label_es}) · Goldstein {goldstein:+.1f} · tono {tone:+.1f}"
            f" · {mentions} menciones / {sources} fuentes · {place or 'sin ubicación'}"
        )

        records.append(
            EventRecord(
                uid=f"gdelt:{parts[0]}",
                source="gdelt",
                category=category,
                subtype=label_es,
                title=title[:300],
                summary=summary,
                lat=lat,
                lon=lon,
                severity=abs(goldstein) if goldstein else None,
                severity_label="critical" if root in ("19", "20") else ("high" if root in ("17", "18") else "info"),
                country=place or "",
                event_time=when,
                url=url,
                payload={
                    "eventcode": parts[26],
                    "rootcode": root,
                    "quadclass": quad_i,
                    "goldstein": goldstein,
                    "tone": tone,
                    "mentions": mentions,
                    "sources": sources,
                    "actors": [parts[5] or parts[6], parts[15] or parts[16]],
                    "fips": country,
                    "place": place,
                    "signature": signature,
                },
            )
        )
    return records


async def fetch(fetcher: Fetcher, *, max_events: int = 2500) -> list[EventRecord]:
    listing = await fetcher.get_text(LASTUPDATE)
    export_url = ""
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 3 and "export" in fields[2]:
            export_url = fields[2]
            break
    if not export_url:
        raise RuntimeError("GDELT lastupdate.txt sin fichero export")
    export_url = export_url.replace("http://", "https://", 1)

    # GDELT publica en diferido: el fichero que anuncia lastupdate.txt puede
    # tardar unos minutos en estar disponible (404). Retrocedemos en pasos de
    # 15 min hasta encontrar un export real; nunca dependemos del reloj local.
    stem = export_url.rsplit("/", 1)[-1]
    try:
        stamp = datetime.strptime(stem[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        stamp = None

    blob = b""
    last_err: Exception | None = None
    attempts = 8 if stamp else 1
    for i in range(attempts):
        if stamp is not None:
            slot = stamp - timedelta(minutes=15 * i)
            export_url = (
                "https://data.gdeltproject.org/gdeltv2/"
                + slot.strftime("%Y%m%d%H%M%S")
                + ".export.CSV.zip"
            )
        try:
            blob = await fetcher.get_bytes(export_url)
            if i:
                log.info("gdelt: el fichero más reciente no estaba; usando %s", stamp and (stamp - timedelta(minutes=15 * i)).isoformat())
            break
        except Exception as exc:  # 404 en el slot más nuevo
            last_err = exc
            continue
    if not blob:
        raise RuntimeError(f"GDELT sin export disponible en los últimos {attempts * 15} min: {last_err}")
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = zf.namelist()[0]
        raw = zf.read(name).decode("latin-1", errors="replace")
    records = parse_export(raw)
    if len(records) > max_events:
        records.sort(key=lambda r: (r.payload.get("mentions", 1)), reverse=True)
        records = records[:max_events]
    log.info("gdelt %s -> %d eventos geolocalizados", export_url.rsplit("/", 1)[-1], len(records))
    return records

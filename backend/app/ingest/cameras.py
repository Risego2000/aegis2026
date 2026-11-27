"""Cámaras públicas abiertas de tráfico.

Redes cubiertas: DGT (España, ~1.900 cámaras de la red de carreteras del
Estado), Euskadi (Gobierno Vasco), TfL (Londres), Caltrans (California), NYC TMC
(Nueva York) y Digitraffic (Finlandia).

Todas son de titularidad pública y publican catálogo e imagen sin clave ni
registro. El catálogo se refresca cada 30 min (las posiciones son fijas) y las
imágenes se piden a demanda a través del proxy del backend.
"""
from __future__ import annotations

import asyncio
import logging

from .client import Fetcher

log = logging.getLogger("aegis.cameras")

TFL_URL = "https://api.tfl.gov.uk/Place/Type/JamCam"
CALTRANS_URL = "https://cwwp2.dot.ca.gov/data/d{d}/cctv/cctvStatusD{d:02d}.json"
NYC_URL = "https://webcams.nyctmc.org/api/cameras"
DIGITRAFFIC_URL = "https://tie.digitraffic.fi/api/weathercam/v1/stations"
EUSKADI_URL = "https://api.euskadi.eus/traffic/v1.0/cameras?_page={page}&_elements=20"
# Catálogo oficial de la DGT que alimenta su visor público de cámaras
# (https://www.dgt.es/conoce-el-estado-del-trafico/camaras-de-trafico/):
# JSON estático, sin clave, con id, coordenadas, carretera, pk y provincia.
# Las imágenes cuelgan de https://etraffic.dgt.es/camarasEtraffic/<id>.jpg
DGT_URL = "https://www.dgt.es/.content/.assets/json/camaras.json"
DGT_IMAGE = "https://etraffic.dgt.es/camarasEtraffic/{cid}.jpg"
DGT_SOURCE = "https://www.dgt.es/conoce-el-estado-del-trafico/camaras-de-trafico/"
# CCTV municipal de Madrid: el catálogo oficial (KML con coordenadas y URL de
# imagen) lo publica informo.madrid.es y datos.madrid.es lo redistribuye como
# conjunto de datos abierto "Tráfico. Cámaras" (202088-0-trafico-camaras.kml).
MADRID_KML = "https://informo.madrid.es/informo/tmadrid/CCTV.kml"
# Servei Català de Trànsit: dades obertes de la Generalitat. KML con nombre de
# vía, punto kilométrico, municipio, coordenadas y URL de la imagen (servida por
# mct.gencat.cat, que redirige a un JPEG en vivo).
CAT_KML = "https://www.gencat.cat/transit/opendata/cameres.kml"

# Código INE de provincia -> nombre. La DGT publica el código, no el nombre.
DGT_PROVINCES = {
    1: "Álava", 2: "Albacete", 3: "Alicante", 4: "Almería", 5: "Ávila",
    6: "Badajoz", 7: "Baleares", 8: "Barcelona", 9: "Burgos", 10: "Cáceres",
    11: "Cádiz", 12: "Castellón", 13: "Ciudad Real", 14: "Córdoba",
    15: "A Coruña", 16: "Cuenca", 17: "Girona", 18: "Granada", 19: "Guadalajara",
    20: "Gipuzkoa", 21: "Huelva", 22: "Huesca", 23: "Jaén", 24: "León",
    25: "Lleida", 26: "La Rioja", 27: "Lugo", 28: "Madrid", 29: "Málaga",
    30: "Murcia", 31: "Navarra", 32: "Ourense", 33: "Asturias", 34: "Palencia",
    35: "Las Palmas", 36: "Pontevedra", 37: "Salamanca", 38: "S. C. Tenerife",
    39: "Cantabria", 40: "Segovia", 41: "Sevilla", 42: "Soria", 43: "Tarragona",
    44: "Teruel", 45: "Toledo", 46: "Valencia", 47: "Valladolid", 48: "Bizkaia",
    49: "Zamora", 50: "Zaragoza", 51: "Ceuta", 52: "Melilla",
}

NETWORK_LABELS = {
    "cat": "SCT · Catalunya",
    "madrid": "Madrid · Ayto. (CCTV)",
    "dgt": "DGT · España",
    "euskadi": "Euskadi · Tráfico",
    "tfl": "TfL · Londres",
    "caltrans": "Caltrans · California",
    "nyc": "NYC TMC · Nueva York",
    "digitraffic": "Digitraffic · Finlandia",
}


def utm30n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """UTM zona 30N (EPSG:25830) -> lat/lon WGS84.

    El open data de Euskadi publica coordenadas proyectadas; el mapa trabaja en
    grados, así que se aplica la inversa estándar de la proyección transversa de
    Mercator (Snyder), sin dependencias externas.
    """
    import math

    a, f = 6378137.0, 1 / 298.257223563
    k0, lon0 = 0.9996, math.radians(-3.0)
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)

    x = easting - 500000.0
    y = northing

    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    c1 = ep2 * math.cos(phi1) ** 2
    t1 = math.tan(phi1) ** 2
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)

    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lon)


def _props(place: list[dict]) -> dict[str, str]:
    return {p.get("key", ""): p.get("value", "") for p in place or []}


def _dgt_num(value: object) -> float | None:
    """La DGT mezcla formatos en el mismo JSON: "40.507211", "39,4335965" y
    basura tipo ".-0.7883173". Se rescata el primer número válido."""
    import re

    if value is None:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).strip().replace(",", "."))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


async def fetch_dgt(fetcher: Fetcher) -> list[dict]:
    """DGT (España): ~1.900 cámaras de la red de carreteras del Estado.

    El visor público de la DGT se nutre de un JSON estático sin clave ni
    registro (`/.content/.assets/json/camaras.json`) y las imágenes se sirven
    como JPEG abierto desde etraffic.dgt.es. Se descartan las coordenadas que
    caen fuera de España (el origen tiene alguna con el signo cambiado).
    """
    payload = await fetcher.get_json(
        DGT_URL, retries=2, timeout=60,
        headers={"Accept": "application/json", "Referer": DGT_SOURCE},
    )
    rows = payload.get("camaras") if isinstance(payload, dict) else payload
    out: list[dict] = []
    dropped = 0
    for cam in rows or []:
        cid = str(cam.get("id") or "").strip()
        lat = _dgt_num(cam.get("latitud"))
        lon = _dgt_num(cam.get("longitud"))
        if not cid or lat is None or lon is None:
            dropped += 1
            continue
        if not (27.0 <= lat <= 44.5 and -19.0 <= lon <= 4.5):
            dropped += 1
            continue
        try:
            province = DGT_PROVINCES.get(int(str(cam.get("provincia") or "0").strip()))
        except ValueError:
            province = None
        road = (cam.get("carretera") or "").strip()
        pk = (cam.get("pk") or "").strip()
        sentido = {"+": "creciente", "-": "decreciente"}.get(
            (cam.get("sentido") or "").strip(), ""
        )
        title = " · ".join(x for x in (road, f"km {pk}" if pk else "", province) if x)
        out.append(
            {
                "id": f"dgt:{cid}",
                "name": title or f"Cámara DGT {cid}",
                "lat": lat,
                "lon": lon,
                "image": (cam.get("imagen") or DGT_IMAGE.format(cid=cid)).strip(),
                "kind": "tráfico",
                "online": True,
                "place": province or "",
                "route": road,
                "direction": sentido,
                "km": pk,
                "source_url": DGT_SOURCE,
                "operator": "DGT · Dirección General de Tráfico",
                "country": "ES",
                "network_label": NETWORK_LABELS["dgt"],
            }
        )

    # ids repetidos en el origen: nos quedamos con la primera aparición
    unique: dict[str, dict] = {}
    for cam in out:
        unique.setdefault(cam["id"], cam)
    log.info("dgt: %d filas → %d cámaras (descartadas %d)",
             len(rows or []), len(unique), dropped)
    return list(unique.values())


async def fetch_tfl(fetcher: Fetcher) -> list[dict]:
    places = await fetcher.get_json(TFL_URL, retries=2, timeout=40)
    out: list[dict] = []
    for place in places or []:
        props = _props(place.get("additionalProperties") or [])
        image = props.get("imageUrl") or ""
        lat, lon = place.get("lat"), place.get("lon")
        if not image or lat is None or lon is None:
            continue
        out.append(
            {
                "id": f"tfl:{place.get('id')}",
                "name": place.get("commonName") or place.get("id"),
                "lat": float(lat),
                "lon": float(lon),
                "image": image,
                "kind": "tráfico",
                "online": props.get("available", "true").lower() == "true",
                "place": props.get("currentState", "") or "Londres",
                "source_url": f"https://tfl.gov.uk/traffic/status/camera?cameraId={place.get('id', '')}",
                "operator": "Transport for London",
                "country": "GB",
                "network_label": NETWORK_LABELS["tfl"],
            }
        )
    return out


async def fetch_caltrans(fetcher: Fetcher) -> list[dict]:
    out: list[dict] = []

    async def one(district: int) -> list[dict]:
        url = CALTRANS_URL.format(d=district)
        try:
            payload = await fetcher.get_json(url, retries=1, timeout=30)
        except Exception as exc:  # noqa: BLE001 - un distrito caído no rompe el resto
            log.debug("caltrans D%02d: %s", district, exc)
            return []
        rows = []
        for entry in payload.get("data") or []:
            cctv = entry.get("cctv") or {}
            loc = cctv.get("location") or {}
            image = ((cctv.get("imageData") or {}).get("static") or {}).get("currentImageURL") or ""
            try:
                lat = float(loc.get("latitude"))
                lon = float(loc.get("longitude"))
            except (TypeError, ValueError):
                continue
            if not image:
                continue
            rows.append(
                {
                    "id": f"caltrans:{loc.get('district')}-{cctv.get('index')}",
                    "name": loc.get("locationName") or f"Cámara D{loc.get('district')}",
                    "lat": lat,
                    "lon": lon,
                    "image": image,
                    "kind": "tráfico",
                    "online": str(cctv.get("inService", "true")).lower() != "false",
                    "place": loc.get("nearbyPlace") or "",
                    "route": loc.get("route") or "",
                    "source_url": "https://cwwp2.dot.ca.gov/vm/iframemap.htm",
                    "operator": "Caltrans",
                    "country": "US",
                    "network_label": NETWORK_LABELS["caltrans"],
                }
            )
        return rows

    for chunk in (range(1, 7), range(7, 13)):
        for part in await asyncio.gather(*(one(d) for d in chunk), return_exceptions=True):
            if isinstance(part, list):
                out.extend(part)
            elif isinstance(part, Exception):
                log.debug("caltrans: %s", part)
    return out


async def fetch_nyc(fetcher: Fetcher) -> list[dict]:
    rows = await fetcher.get_json(NYC_URL, retries=2, timeout=40)
    out = []
    for cam in rows or []:
        try:
            lat = float(cam.get("latitude"))
            lon = float(cam.get("longitude"))
        except (TypeError, ValueError):
            continue
        image = cam.get("imageUrl") or ""
        if not image:
            continue
        out.append(
            {
                "id": f"nyc:{cam.get('id')}",
                "name": cam.get("name") or cam.get("id"),
                "lat": lat,
                "lon": lon,
                "image": image,
                "kind": "tráfico",
                "online": str(cam.get("isOnline", "true")).lower() == "true",
                "place": cam.get("area") or "",
                "source_url": "https://webcams.nyctmc.org/map",
                "operator": "NYC DOT",
                "country": "US",
                "network_label": NETWORK_LABELS["nyc"],
            }
        )
    return out


async def fetch_digitraffic(fetcher: Fetcher) -> list[dict]:
    payload = await fetcher.get_json(
        DIGITRAFFIC_URL, retries=2, timeout=60,
        headers={"Accept-Encoding": "gzip", "Digitraffic-User": "AEGIS/1.0"},
    )
    out = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        presets = [p for p in props.get("presets") or [] if p.get("inCollection")]
        if not presets or len(coords) < 2:
            continue
        preset = presets[0].get("id")
        out.append(
            {
                "id": f"digitraffic:{props.get('id')}",
                "name": props.get("name") or props.get("id"),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "image": f"https://weathercam.digitraffic.fi/{preset}.jpg",
                "kind": "meteorológica",
                "online": props.get("collectionStatus") == "GATHERING",
                "place": "Finlandia",
                "source_url": "https://www.digitraffic.fi/tieliikenne/",
                "operator": "Fintraffic",
                "country": "FI",
                "network_label": NETWORK_LABELS["digitraffic"],
                "updated_at": props.get("dataUpdatedTime"),
            }
        )
    return out


async def fetch_euskadi(fetcher: Fetcher) -> list[dict]:
    """Tráfico de Euskadi (Gobierno Vasco): 489 cámaras de la red de carreteras,
    390 con imagen JPEG en vivo. Coordenadas en UTM 30N."""
    out: list[dict] = []

    async def page(n: int) -> list[dict]:
        try:
            payload = await fetcher.get_json(EUSKADI_URL.format(page=n), retries=2, timeout=30)
        except Exception as exc:  # noqa: BLE001 - una página caída no invalida el resto
            log.warning("euskadi p%s: %s", n, exc)
            return []
        rows: list[dict] = []
        for cam in payload.get("cameras") or []:
            image = (cam.get("urlImage") or "").strip()
            try:
                east = float(cam.get("longitude"))
                north = float(cam.get("latitude"))
            except (TypeError, ValueError):
                continue
            # el origen mezcla dos formatos: parte del catálogo viene en grados y
            # parte en UTM 30N (metros). Se distingue por magnitud.
            if abs(east) <= 180 and abs(north) <= 90:
                lat, lon = north, east          # ya en grados
            else:
                lat, lon = utm30n_to_wgs84(east, north)
            if not (42.0 < lat < 43.7 and -3.6 < lon < -1.6):
                continue
            rows.append(
                {
                    "id": f"euskadi:{cam.get('cameraId')}",
                    "name": cam.get("cameraName") or f"Cámara {cam.get('cameraId')}",
                    "lat": lat,
                    "lon": lon,
                    "image": image,
                    "kind": "tráfico",
                    "online": bool(image),
                    "place": cam.get("address") or "",
                    "route": cam.get("road") or "",
                    "source_url": "https://www.trafikoa.eus/",
                    "operator": "Gobierno Vasco · Tráfico",
                    "country": "ES",
                    "network_label": NETWORK_LABELS["euskadi"],
                }
            )
        return rows

    # de 5 en 5: 25 peticiones simultáneas agotan el pool compartido (12 conexiones)
    # y el origen empieza a cerrar conexiones, dejando cámaras sin indexar
    for start in range(1, 26, 5):
        chunk = await asyncio.gather(*(page(n) for n in range(start, start + 5)))
        for rows in chunk:
            out.extend(rows)

    # el origen repite cada cámara una vez por fuente (≈3 veces, 489 filas para
    # 175 cámaras) y no todas las copias traen URL de imagen: nos quedamos con la
    # mejor de cada id.
    best: dict[str, dict] = {}
    for cam in out:
        prev = best.get(cam["id"])
        if prev is None or (bool(cam["image"]), bool(cam["place"])) > (bool(prev["image"]), bool(prev["place"])):
            best[cam["id"]] = cam
    merged = list(best.values())
    log.info("euskadi: %d filas → %d cámaras (%d con imagen)",
             len(out), len(merged), sum(1 for c in merged if c["image"]))
    return merged


async def fetch_madrid(fetcher: Fetcher) -> list[dict]:
    """CCTV del Ayuntamiento de Madrid: 357 cámaras de tráfico del callejero.

    Fuente: KML oficial `informo.madrid.es/informo/tmadrid/CCTV.kml`, el mismo
    que publica datos.madrid.es como «Tráfico. Cámaras». Cada Placemark trae
    nombre, número de cámara, coordenadas y la URL del JPEG en vivo.
    """
    import re
    import xml.etree.ElementTree as ET

    body = await fetcher.get_bytes(MADRID_KML, retries=2, timeout=45)
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:  # noqa: PERF203 - origen corrupto: no se rompe el resto
        raise ValueError(f"KML de Madrid ilegible: {exc}") from exc

    out: list[dict] = []
    for placemark in root.iter():
        if not placemark.tag.endswith("Placemark"):
            continue
        fields: dict[str, str] = {}
        image = ""
        coords = ""
        for node in placemark.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "Data":
                fields[(node.get("name") or "").strip()] = (node.text or "").strip()
                for child in node:
                    if child.tag.endswith("Value"):
                        fields[(node.get("name") or "").strip()] = (child.text or "").strip()
            elif tag == "description":
                text = (node.text or "")
                match = re.search(r'src=["\']?([^"\' >]+)', text)
                if match:
                    image = match.group(1)
            elif tag == "coordinates":
                coords = (node.text or "").strip()
        if not image or not coords:
            continue
        try:
            lon_s, lat_s = coords.split(",")[:2]
            lat, lon = float(lat_s), float(lon_s)
        except ValueError:
            continue
        if not (40.2 <= lat <= 40.6 and -3.9 <= lon <= -3.4):
            continue
        numero = fields.get("Numero") or ""
        nombre = fields.get("Nombre") or f"Cámara {numero}"
        out.append(
            {
                "id": f"madrid:{numero or nombre[:24]}",
                "name": nombre.title(),
                "lat": lat,
                "lon": lon,
                "image": image,
                "kind": "tráfico",
                "online": True,
                "place": "Madrid",
                "route": "",
                "source_url": "https://informo.madrid.es/#/realtime?panel=live",
                "operator": "Ayuntamiento de Madrid · Informo",
                "country": "ES",
                "network_label": NETWORK_LABELS["madrid"],
            }
        )
    log.info("madrid: %d cámaras CCTV municipales", len(out))
    return out


async def fetch_catalunya(fetcher: Fetcher) -> list[dict]:
    """Servei Català de Trànsit: cámaras de las carreteras catalanas.

    Fuente oficial: `gencat.cat/transit/opendata/cameres.kml` (dades obertes de
    la Generalitat, sin clave). El KML trae 38 cámaras con vía, pk, municipio,
    coordenadas y la URL de imagen de mct.gencat.cat (http, se reescribe a
    https: el origen redirige a un JPEG en vivo y así el proxy no sale en claro).
    """
    import re

    import html as _html

    body = await fetcher.get_bytes(CAT_KML, retries=2, timeout=45)
    text = body.decode("utf-8", errors="replace")
    out: list[dict] = []
    # la <description> va con el HTML escapado (&lt;strong&gt;…): se desescapa
    # para poder leer municipio y título con expresiones normales.
    for block in re.findall(r"<Placemark>(.*?)</Placemark>", text, re.S):
        block = _html.unescape(block)
        coords = re.search(r"<coordinates>\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", block)
        img = re.search(r'src="([^"]+)"', block)
        title = re.search(r"<name>([^<]+)</name>", block)
        municipality = re.search(r"Municipi:\s*</strong>\s*([^<]+)<", block)
        if not (coords and img):
            continue
        lon, lat = float(coords.group(1)), float(coords.group(2))
        if not (40.4 <= lat <= 42.9 and 0.1 <= lon <= 3.4):
            continue
        image = img.group(1).replace("http://", "https://", 1)
        cam_id = re.search(r"sctidcam=([a-zA-Z0-9]+)", image)
        name = (title.group(1) if title else "").strip() or "Càmera SCT"
        place = (municipality.group(1) if municipality else "").strip().title()
        road = name.split(" - ")[0] if " - " in name else ""
        out.append(
            {
                "id": f"cat:{cam_id.group(1) if cam_id else name[:20]}",
                "name": name,
                "lat": lat,
                "lon": lon,
                "image": image,
                "kind": "tráfico",
                "online": True,
                "place": place,
                "route": road,
                "source_url": "https://www.gencat.cat/transit/opendata/cameres.kml",
                "operator": "Servei Català de Trànsit · Generalitat",
                "country": "ES",
                "network_label": NETWORK_LABELS["cat"],
            }
        )
    unique: dict[str, dict] = {}
    for cam in out:
        unique.setdefault(cam["id"], cam)
    log.info("catalunya: %d cámaras SCT", len(unique))
    return list(unique.values())


PROVIDERS = {
    "dgt": fetch_dgt,
    "madrid": fetch_madrid,
    "cat": fetch_catalunya,
    "euskadi": fetch_euskadi,
    "tfl": fetch_tfl,
    "caltrans": fetch_caltrans,
    "nyc": fetch_nyc,
    "digitraffic": fetch_digitraffic,
}


async def refresh(fetcher: Fetcher) -> int:
    """Refresca las cuatro redes en paralelo; devuelve el total de cámaras."""
    from ..cameras import CAMERAS

    # En serie, no en paralelo: cada red satura el pool de 12 conexiones por sí
    # sola (Caltrans abre 12 distritos, Euskadi 25 páginas) y al competir entre
    # ellas el origen cierra conexiones y se pierden cámaras en silencio.
    # El coste total es de ~4 s cada 30 min.
    for name, fn in PROVIDERS.items():
        try:
            result = await fn(fetcher)
        except Exception as exc:  # noqa: BLE001 - una red caída no tumba el catálogo
            CAMERAS.fail(name, str(exc))
            log.warning("cámaras %s: %s", name, exc)
            continue
        CAMERAS.merge(result, name)
        log.info("cámaras %s: %d", name, len(result))
    return len(CAMERAS.items)

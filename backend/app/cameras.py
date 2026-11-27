"""Catálogo de cámaras públicas abiertas.

Cuatro redes de titularidad pública publican sus cámaras sin clave ni registro:
TfL (Londres), Caltrans (California), NYC TMC (Nueva York) y Digitraffic
(Finlandia). Sumadas son ~5.000 cámaras con imagen JPEG en vivo.

Este módulo guarda el catálogo en memoria (posiciones estáticas, no hace falta
persistirlas) y sirve la GeoJSON que consume el mapa. La imagen no se reenvía al
navegador tal cual: se proxya desde `/api/cameras/{id}/frame` para evitar
contenido mixto, CORS y fugas de referrer.
"""
from __future__ import annotations

import time
from typing import Any

from .models import utcnow


class CameraCatalogue:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.updated_at: float = 0.0
        self.runs: int = 0
        self.failures: int = 0
        self.network_errors: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    def merge(self, cameras: list[dict[str, Any]], network: str) -> int:
        """Sustituye las cámaras de una red y conserva las de las demás."""
        keep = {cid: cam for cid, cam in self.items.items() if cam.get("network") != network}
        fresh = {}
        now = time.time()
        for cam in cameras:
            cid = str(cam.get("id") or "").strip()
            if not cid or cam.get("lat") is None or cam.get("lon") is None:
                continue
            cam["network"] = network
            cam["_ts"] = now
            fresh[cid] = cam
        self.items = {**keep, **fresh}
        self.updated_at = now
        self.runs += 1
        self.network_errors.pop(network, None)
        return len(fresh)

    def fail(self, network: str, message: str) -> None:
        self.failures += 1
        self.network_errors[network] = message[:200]

    # ------------------------------------------------------------------ #
    def get(self, cid: str) -> dict[str, Any] | None:
        cam = self.items.get(cid)
        if cam is None:
            return None
        out = {k: v for k, v in cam.items() if not k.startswith("_")}
        out["age_s"] = round(time.time() - cam.get("_ts", time.time()), 1)
        return out

    def networks(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cam in self.items.values():
            key = str(cam.get("network"))
            row = out.setdefault(
                key,
                {"network": key, "label": cam.get("network_label", key),
                 "country": cam.get("country", ""), "count": 0, "online": 0},
            )
            row["count"] += 1
            if cam.get("online", True):
                row["online"] += 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]["count"]))

    def geojson(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        network: str | None = None,
        limit: int = 20000,
    ) -> dict[str, Any]:
        features = []
        for cid, cam in self.items.items():
            if network and cam.get("network") != network:
                continue
            lat, lon = cam.get("lat"), cam.get("lon")
            if lat is None or lon is None:
                continue
            if bbox:
                w, s, e, n = bbox
                if not (w <= lon <= e and s <= lat <= n):
                    continue
            # Solo lo que el mapa necesita para pintar y abrir la ficha: el
            # catálogo lleva ~8 800 cámaras y cada campo de más se multiplica
            # por 8 800 en la respuesta (4,5 MB antes de este recorte).
            CAMPOS = ("name", "network", "network_label", "kind", "place", "online", "image", "country")
            props = {k: cam.get(k) for k in CAMPOS if cam.get(k) is not None}
            props["id"] = cid
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": props,
                }
            )
            if len(features) >= limit:
                break
        return {
            "type": "FeatureCollection",
            "count": len(features),
            "updated_at": (
                utcnow().fromtimestamp(self.updated_at).isoformat(timespec="seconds")
                if self.updated_at
                else None
            ),
            "networks": list(self.networks().values()),
            "features": features,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "count": len(self.items),
            "networks": self.networks(),
            "updated_at": (
                utcnow().fromtimestamp(self.updated_at).isoformat(timespec="seconds")
                if self.updated_at
                else None
            ),
            "runs": self.runs,
            "failures": self.failures,
            "errors": dict(self.network_errors),
        }


CAMERAS = CameraCatalogue()

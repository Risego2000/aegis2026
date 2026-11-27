"""Límite de peticiones en proceso para las rutas caras.

La API es pública y sin claves: sin freno, cualquiera puede pedir exportaciones
completas, fotogramas de cámara o un informe de IA (que gasta cuota del
proveedor) en bucle. Una ventana deslizante por IP y ruta basta para el uso
humano normal y corta los scripts abusivos sin dependencias ni estado externo.

No autentica nada: el control de mutaciones sigue siendo `AEGIS_TOKEN` en
`/api/ingest/*`; esto solo acota el daño de un cliente insistente.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

WINDOW_S = 60.0
MAX_BUCKETS = 20_000


@dataclass(frozen=True)
class Rule:
    """Método + prefijo de ruta + tope de peticiones por minuto."""

    method: str
    prefix: str
    per_minute: int
    suffix: str = ""


# Solo las rutas que cuestan CPU, red o cuota. El resto (eventos, capas vivas)
# va servido de memoria o de SQLite y tiene sus propios topes de `limit`.
RULES: tuple[Rule, ...] = (
    Rule("POST", "/api/ai/briefing", 8),
    Rule("POST", "/api/ingest/", 20),
    Rule("POST", "/api/fences", 30),
    Rule("GET", "/api/export/", 30),
    Rule("GET", "/api/cameras/", 120, suffix="/frame"),
    Rule("GET", "/api/media/", 120),
)


class SlidingWindow:
    """Contador por clave (ip + ruta) en una ventana de tiempo deslizante."""

    def __init__(self, window_s: float = WINDOW_S) -> None:
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int, now: float | None = None) -> tuple[bool, int, int]:
        """Devuelve (permitido, restantes, segundos_para_reintentar)."""
        now = time.time() if now is None else now
        bucket = self._hits.setdefault(key, deque())
        edge = now - self.window_s
        while bucket and bucket[0] < edge:
            bucket.popleft()
        if len(bucket) >= limit:
            retry = max(1, int(round(bucket[0] + self.window_s - now)))
            return False, 0, retry
        bucket.append(now)
        if len(self._hits) > MAX_BUCKETS:  # poda: fuera las cubetas ya vacías
            self._compact(now)
        return True, limit - len(bucket), 0

    def _compact(self, now: float) -> None:
        edge = now - self.window_s
        for key in [k for k, v in self._hits.items() if not v or v[-1] < edge]:
            self._hits.pop(key, None)

    def reset(self) -> None:
        self._hits.clear()


LIMITER = SlidingWindow()


def match_rule(method: str, path: str) -> Rule | None:
    for rule in RULES:
        if method != rule.method or not path.startswith(rule.prefix):
            continue
        if rule.suffix and not path.endswith(rule.suffix):
            continue
        return rule
    return None


def check(method: str, path: str, client: str) -> tuple[int, int] | None:
    """(reintentar_en_s, límite) si la petición se pasa del tope; None si vale."""
    rule = match_rule(method, path)
    if rule is None:
        return None
    allowed, _, retry = LIMITER.hit(
        f"{client}|{rule.method}|{rule.prefix}{rule.suffix}", rule.per_minute
    )
    return None if allowed else (retry, rule.per_minute)

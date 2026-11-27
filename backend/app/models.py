"""Domain model shared by every ingestor, storage backend and the API."""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str:
    if dt is None:
        return utcnow().isoformat(timespec="seconds")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        # heuristics: ms vs s epoch
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d"):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(text)
            else:
                dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------- #
# Geo helpers
# --------------------------------------------------------------------------- #

EARTH_R = 6_371_008.8  # mean radius, metres


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Index-friendly bounding box for a radius query (west, south, east, north).

    This is what lets a radius search use a spatial index instead of scanning:
    the box is the cheap index probe, the exact metre distance is the residual
    predicate. Mirrors PostGIS `ST_DWithin` with a GiST index.
    """
    dlat = radius_m / 111_320.0
    coslat = max(0.05, math.cos(math.radians(lat)))
    dlon = radius_m / (111_320.0 * coslat)
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def clamp_lat(v: float) -> float:
    return max(-90.0, min(90.0, v))


def clamp_lon(v: float) -> float:
    v = (v + 180.0) % 360.0 - 180.0
    return v


# --------------------------------------------------------------------------- #
# Text similarity: dependency-free local embedder (signed hashing / random
# projection). Deterministic, offline, ~2 µs per document. Swap for
# Ollama/Gemini embeddings by setting AI_PROVIDER — the interface is identical.
# --------------------------------------------------------------------------- #

EMBED_DIM = 192
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "are", "was", "were", "with", "from", "by", "as", "after", "over", "new",
    "says", "said", "el", "la", "los", "las", "de", "del", "en", "y", "que",
}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(normalize_text(text)) if t not in _STOP and len(t) > 1]


def _hash(token: str) -> tuple[int, int]:
    h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(h[:4], "little"), (1 if h[4] & 1 else -1)


def embed(text: str) -> list[float]:
    """Signed-hashing bag of words + character trigrams, L2-normalised."""
    vec = [0.0] * EMBED_DIM
    toks = tokens(text)
    for tok in toks:
        idx, sign = _hash(tok)
        vec[idx % EMBED_DIM] += sign / math.sqrt(1.0 + 0.35 * len(tok))
        padded = f"#{tok}#"
        for i in range(0, max(1, len(padded) - 2)):
            tri = padded[i : i + 3]
            tidx, tsign = _hash("3:" + tri)
            vec[tidx % EMBED_DIM] += 0.35 * tsign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a, b = list(a), list(b)
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot))


def jaccard(a_text: str, b_text: str) -> float:
    a, b = set(tokens(a_text)), set(tokens(b_text))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --------------------------------------------------------------------------- #
# Event record
# --------------------------------------------------------------------------- #

CATEGORIES = (
    "earthquake",
    "disaster",          # cyclones, floods, volcanoes, drought (GDACS)
    "wildfire",          # NASA FIRMS thermal anomalies
    "conflict",          # GDELT material conflict / attacks
    "protest",
    "diplomacy",
    "economy",
    "news",              # generic geolocated news
    "military",
)

SEVERITY_ORDER = {"green": 1, "info": 1, "yellow": 2, "orange": 3, "red": 4, "critical": 5}


@dataclass
class EventRecord:
    """One normalised intelligence item, ready for dedup + persistence."""

    uid: str                       # stable id: "<source>:<source_id>"
    source: str
    category: str
    title: str
    lat: float
    lon: float
    event_time: datetime
    summary: str = ""
    subtype: str = ""
    depth_km: float | None = None
    severity: float | None = None
    severity_label: str = ""
    country: str = ""
    iso3: str = ""
    url: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    geometry: dict[str, Any] | None = None   # polygon/line for area events
    embedding: list[float] = field(default_factory=list)

    def text_blob(self) -> str:
        parts = [self.title, self.subtype, self.country, self.summary[:400]]
        return " ".join(p for p in parts if p)

    def to_row(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_time"] = iso(self.event_time)
        return data


@dataclass
class Event:
    """Persisted, de-duplicated intelligence event returned by the API."""

    id: str
    cluster_id: str
    source: str
    sources: list[str]
    category: str
    subtype: str
    title: str
    summary: str
    lat: float
    lon: float
    depth_km: float | None
    severity: float | None
    severity_label: str
    country: str
    iso3: str
    event_time: str
    first_seen: str
    updated_at: str
    url: str
    mentions: int
    sources_count: int
    confidence: float
    payload: dict[str, Any]
    geometry: dict[str, Any] | None
    embedding: list[float] = field(default_factory=list)  # internal, never serialised


@dataclass
class InfraHit:
    id: str
    name: str
    kind: str
    subtype: str
    country: str
    iso3: str
    lat: float
    lon: float
    population: float
    distance_m: float

"""Minimal Tile38 client (RESP protocol, no third-party dependency).

Tile38 is used exactly as the architecture demands: objects are written with
`SET key id POINT lat lon`, and live geofence notifications are consumed from a
streaming `FENCE ... DETECT enter,exit,inside NEARBY ...` channel.

    TILE38_URL=tile38://localhost:9851

When the URL is empty the in-process engine in `engine.py` is used instead —
same semantics, no extra service.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

DETECT_MODES = ("enter", "exit", "cross", "inside", "outside")


def _encode(args: list[str]) -> bytes:
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        raw = str(arg).encode()
        out.append(f"${len(raw)}\r\n".encode())
        out.append(raw + b"\r\n")
    return b"".join(out)


class Tile38Error(RuntimeError):
    pass


class Tile38Client:
    def __init__(self, url: str, timeout: float = 10.0):
        parsed = urlparse(url if "://" in url else f"tile38://{url}")
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 9851
        self.timeout = timeout
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def close(self) -> None:
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass

    # ---------------------------- RESP ---------------------------------- #
    async def _read(self) -> Any:
        assert self.reader is not None
        line = await self.reader.readuntil(b"\r\n")
        prefix, body = line[:1], line[1:-2]
        if prefix == b"+":
            return body.decode()
        if prefix == b"-":
            raise Tile38Error(body.decode())
        if prefix == b":":
            return int(body)
        if prefix == b"$":
            length = int(body)
            if length == -1:
                return None
            data = await self.reader.readexactly(length + 2)
            return self._maybe_json(data[:-2].decode())
        if prefix == b"*":
            count = int(body)
            return [await self._read() for _ in range(count)]
        raise Tile38Error(f"unexpected RESP prefix {prefix!r}")

    @staticmethod
    def _maybe_json(text: str) -> Any:
        stripped = text.strip()
        if stripped[:1] in "{[":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return text
        return text

    async def execute(self, *args: Any) -> Any:
        if self.writer is None:
            await self.connect()
        async with self._lock:
            assert self.writer is not None
            self.writer.write(_encode([str(a) for a in args]))
            await self.writer.drain()
            return await asyncio.wait_for(self._read(), self.timeout)

    # --------------------------- commands ------------------------------- #
    async def set_point(self, key: str, obj_id: str, lat: float, lon: float,
                        fields: dict[str, Any] | None = None) -> Any:
        args: list[Any] = ["SET", key, obj_id, "POINT", lat, lon]
        if fields:
            for name, value in fields.items():
                if isinstance(value, bool):
                    continue
                args.extend(["FIELD", name, value])
        return await self.execute(*args)

    async def nearby(self, collection: str, lat: float, lon: float, radius_m: float) -> Any:
        return await self.execute("NEARBY", collection, "POINT", lat, lon, radius_m)

    async def drop(self, key: str) -> Any:
        return await self.execute("DROP", key)

    async def fence(self, key: str, lat: float, lon: float, radius_m: float,
                    detect: tuple[str, ...] = ("enter", "exit", "inside"),
                    collection: str = "aircraft") -> AsyncIterator[dict[str, Any]]:
        """Stream FENCE messages as dicts: {detect, key, id, object}."""
        for mode in detect:
            if mode not in DETECT_MODES:
                raise ValueError(f"invalid DETECT mode: {mode}")
        if self.writer is None:
            await self.connect()
        assert self.writer is not None and self.reader is not None
        self.writer.write(
            _encode(["FENCE", "DETECT", ",".join(detect), "NEARBY", collection,
                     "POINT", lat, lon, radius_m])
        )
        await self.writer.drain()
        while True:
            message = await self._read()
            if isinstance(message, dict):
                yield message
            elif isinstance(message, list):
                for item in message:
                    if isinstance(item, dict):
                        yield item

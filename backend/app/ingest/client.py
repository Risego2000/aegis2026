"""Shared HTTP helper: connection reuse, retries with jitter, sane UA.

Every upstream is a free, keyless (or free-key) public endpoint, so being a
polite client matters: we keep one pooled AsyncClient per process, retry 429/5xx
with backoff, and never hammer an endpoint in parallel.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

log = logging.getLogger("aegis.http")

UA = "AegisOSINT/1.0 (+https://github.com/; open-source OSINT super app)"


class Fetcher:
    def __init__(self, timeout: float = 30.0):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=8),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(self, method: str, url: str, *, retries: int = 3,
                      **kwargs: Any) -> httpx.Response:
        delay = 1.5
        last: Exception | None = None
        for attempt in range(retries):
            try:
                resp = await self.client.request(method, url, **kwargs)
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(
                        f"upstream {resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt == retries - 1:
                    break
                await asyncio.sleep(delay + random.random())
                delay *= 2
        raise RuntimeError(f"GET {url} failed after {retries} attempts: {last}")

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.request("GET", url, **kwargs)
        return resp.json()

    async def get_bytes(self, url: str, **kwargs: Any) -> bytes:
        resp = await self.request("GET", url, **kwargs)
        return resp.content

    async def get_text(self, url: str, **kwargs: Any) -> str:
        resp = await self.request("GET", url, **kwargs)
        return resp.text

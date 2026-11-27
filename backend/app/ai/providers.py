"""Zero-cost LLM layer: local Ollama first, free Gemini Flash second.

`AI_PROVIDER=auto` probes, in order:
  1. Ollama on localhost:11434 (fully local, no quota, no data egress)
  2. Google Gemini Flash free tier (15 req/min, 1M tokens/day — free key)
  3. deterministic local analyst (always available, no network)

Every path returns the same shape, so the briefing endpoint never fails.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from ..config import settings

log = logging.getLogger("aegis.ai")


@dataclass
class AIStatus:
    provider: str
    model: str
    available: bool
    detail: str = ""


_cache: dict[str, object] = {}


async def probe(force: bool = False) -> AIStatus:
    if not force and "status" in _cache:
        return _cache["status"]  # type: ignore[return-value]

    choice = settings.ai_provider.lower()
    if choice in ("auto", "ollama"):
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(f"{settings.ollama_url}/api/tags")
                resp.raise_for_status()
                models = [m.get("name") for m in resp.json().get("models", [])]
            if models:
                model = settings.ollama_model if settings.ollama_model in models else models[0]
                status = AIStatus("ollama", model, True, f"local, {len(models)} modelos instalados")
                _cache["status"] = status
                return status
            if choice == "ollama":
                status = AIStatus("ollama", settings.ollama_model, False, "Ollama sin modelos (ollama pull llama3.2)")
                _cache["status"] = status
                return status
        except Exception as exc:  # noqa: BLE001
            if choice == "ollama":
                status = AIStatus("ollama", settings.ollama_model, False, f"sin conexión: {exc}"[:120])
                _cache["status"] = status
                return status

    if choice in ("auto", "gemini") and settings.gemini_api_key:
        status = AIStatus("gemini", settings.gemini_model, True, "free tier")
        _cache["status"] = status
        return status

    status = AIStatus(
        "local", "analista determinista", True,
        "Sin LLM: se usa el generador local de expedientes (configura OLLAMA_URL o GEMINI_API_KEY)",
    )
    _cache["status"] = status
    return status


async def chat(prompt: str, system: str | None = None, max_tokens: int = 1400) -> tuple[str, str]:
    """Return (text, provider_label). Falls back to '' when no LLM is usable."""
    status = await probe()
    if status.provider == "ollama" and status.available:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{settings.ollama_url}/api/generate",
                    json={
                        "model": status.model,
                        "prompt": f"{system}\n\n{prompt}" if system else prompt,
                        "stream": False,
                        "options": {"temperature": 0.25, "num_predict": max_tokens},
                    },
                )
                resp.raise_for_status()
                return (resp.json().get("response") or "").strip(), f"ollama:{status.model}"
        except Exception as exc:  # noqa: BLE001
            log.warning("ollama generation failed: %s", exc)

    if status.provider == "gemini" and settings.gemini_api_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.gemini_model}:generateContent"
            )
            body = {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": max_tokens},
            }
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(url, params={"key": settings.gemini_api_key}, json=body)
                resp.raise_for_status()
                data = resp.json()
            text = "".join(
                part.get("text", "")
                for cand in data.get("candidates", [])
                for part in cand.get("content", {}).get("parts", [])
            )
            return text.strip(), f"gemini:{settings.gemini_model}"
        except Exception as exc:  # noqa: BLE001
            log.warning("gemini generation failed: %s", exc)

    return "", "local:analista"

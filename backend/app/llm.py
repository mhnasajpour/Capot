"""Thin OpenAI-compatible LLM client with an on-disk cache.

Two rules govern everything here:

1. **Cache first, always.** Every prompt is hashed and its JSON response stored
   under data/llm_cache/. The cache is committed to the repo, so the app — and
   the demo recording — runs correctly with the network unplugged. LLM calls are
   a build-time cost, not a request-time dependency.

2. **Never fail the request.** If the key is missing, the proxy is down, or the
   model returns unparseable output, we return None and the caller falls back to
   deterministic logic. An AI feature that takes the page down with it is worse
   than no AI feature.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_client: Any = None
_client_failed = False


def _get_client() -> Any:
    """Lazily build the OpenAI client; returns None if unusable."""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    if not settings.llm_enabled:
        _client_failed = True
        return None
    try:
        from openai import OpenAI

        _client = OpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout,
        )
    except Exception as exc:  # noqa: BLE001 - any client-construction failure is non-fatal
        log.warning("LLM client unavailable, running cache-only: %s", exc)
        _client_failed = True
        _client = None
    return _client


def cache_key(system: str, prompt: str, model: str) -> str:
    blob = json.dumps([system, prompt, model], ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _cache_path(key: str) -> Path:
    return settings.cache_dir / f"{key}.json"


def read_cache(key: str) -> dict | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def write_cache(key: str, value: dict) -> None:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        _cache_path(key).write_text(
            json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("could not write cache %s: %s", key, exc)


def complete_json(
    system: str,
    prompt: str,
    *,
    model: str | None = None,
    temperature: float = 0.0,
    allow_live: bool = True,
) -> dict | None:
    """Ask the model for a JSON object. Cache-first, None on any failure.

    `allow_live=False` forces cache-only, which is how request-path code should
    call this — live calls belong in the batch enrichment job.
    """
    model = model or settings.llm_model
    key = cache_key(system, prompt, model)

    cached = read_cache(key)
    if cached is not None:
        return cached

    if not allow_live:
        return None

    client = _get_client()
    if client is None:
        return None

    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        content = resp.choices[0].message.content or ""
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            log.warning("LLM returned non-object JSON; ignoring")
            return None
        write_cache(key, parsed)
        return parsed
    except json.JSONDecodeError:
        log.warning("LLM returned unparseable JSON; falling back")
        return None
    except Exception as exc:  # noqa: BLE001 - network/quota/model errors are all non-fatal
        log.warning("LLM call failed, falling back: %s", exc)
        return None


def cache_stats() -> dict[str, Any]:
    cache_dir = settings.cache_dir
    files = list(cache_dir.glob("*.json")) if cache_dir.exists() else []
    return {
        "cached_responses": len(files),
        "live_enabled": settings.llm_enabled,
        "model": settings.llm_model,
        "base_url": settings.llm_base_url,
    }

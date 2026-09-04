"""Async client for Bama.ir's public JSON API.

Bama exposes an unauthenticated JSON API that backs its own web app. We use the
two endpoints that matter:

    GET /cad/api/search?pageIndex=N[&cursor=…][&brand=…]  -> ~30 ads per page
    GET /cad/api/detail/{code}                            -> full specs for one ad

Pagination is by `pageIndex` alone. The payload also carries an opaque `cursor`
(on the first ad of each page only), but passing it back gives *worse* dedup
than plain page indexing, so we don't. `total_count` in the response metadata is
cumulative-so-far rather than a corpus size, so we stop on an empty page instead
of trusting it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

import httpx

from ..normalize import Listing, normalize_ad
from .base import USER_AGENT, Source, register

log = logging.getLogger(__name__)

BASE_URL = "https://bama.ir/cad/api"

# Be a polite guest: this is a public endpoint and we only need a few thousand
# rows, once. Keep concurrency at 1 for search and a small pool for details.
SEARCH_DELAY_S = 1.0
DETAIL_DELAY_S = 0.4


class BamaClient:
    def __init__(self, timeout: float = 25.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "BamaClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict | None:
        """GET with a couple of retries. Returns None rather than raising so a
        single bad page never aborts a long crawl."""
        for attempt in range(3):
            try:
                resp = await self._client.get(f"{BASE_URL}{path}", params=params)
                if resp.status_code == 200:
                    return resp.json()
                # 429/5xx are worth backing off for; 4xx generally are not.
                if resp.status_code in (429, 500, 502, 503, 504):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                log.warning("GET %s -> HTTP %s", path, resp.status_code)
                return None
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("GET %s failed (attempt %d): %s", path, attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def search_pages(
        self,
        max_pages: int,
        brand: str | None = None,
        delay: float = SEARCH_DELAY_S,
    ) -> AsyncIterator[dict]:
        """Walk the search feed, yielding raw ad dicts.

        Only `type == "ad"` entries are real listings; the feed is interleaved
        with `type == "banner"` promo slots which we drop here.
        """
        for page in range(max_pages):
            params: dict[str, Any] = {"pageIndex": page}
            if brand:
                params["brand"] = brand

            payload = await self._get("/search", params)
            if not payload:
                log.warning("stopping %s at page %d: no payload", brand or "all", page)
                return

            ads = [a for a in payload.get("data", {}).get("ads", []) if a.get("type") == "ad"]
            if not ads:
                return

            for ad in ads:
                yield ad

            await asyncio.sleep(delay)

    async def detail(self, code: str) -> dict | None:
        """Fetch one listing's detail record (specs, life_styles, dealer tenure)."""
        payload = await self._get(f"/detail/{code}")
        if not payload:
            return None
        return payload.get("data")

    async def details(self, codes: list[str], delay: float = DETAIL_DELAY_S) -> dict[str, dict]:
        """Fetch details sequentially with a delay. Sequential is deliberate —
        a few hundred enrichments is plenty and hammering the host is not worth
        the risk of an IP block mid-build."""
        out: dict[str, dict] = {}
        for i, code in enumerate(codes):
            data = await self.detail(code)
            if data:
                out[code] = data
            if i % 25 == 0 and i:
                log.info("details: %d/%d", i, len(codes))
            await asyncio.sleep(delay)
        return out


@register
class BamaSource(Source):
    """Bama behind the shared Source interface.

    Wraps `BamaClient` rather than replacing it — the pagination behaviour here
    was hard-won (the payload's `cursor` is a trap; `pageIndex` alone paginates
    correctly) and is left exactly as it was.
    """

    name = "bama"
    delay = SEARCH_DELAY_S

    async def iter_raw(
        self,
        *,
        max_pages: int,
        brands: list[str] | None = None,
        skip_ids: set[str] | None = None,
        **options: Any,
    ) -> AsyncIterator[dict]:
        seen: set[str] = set(skip_ids or ())

        async with BamaClient() as client:
            async for ad in client.search_pages(max_pages=max_pages):
                code = (ad.get("detail") or {}).get("code")
                if code and code not in seen:
                    seen.add(code)
                    yield {"_id": code, "_source": self.name, "ad": ad}

            for brand in brands or []:
                stale = 0
                async for ad in client.search_pages(max_pages=max_pages, brand=brand):
                    code = (ad.get("detail") or {}).get("code")
                    if not code or code in seen:
                        stale += 1
                        if stale >= 90:
                            break
                        continue
                    stale = 0
                    seen.add(code)
                    yield {"_id": code, "_source": self.name, "ad": ad}

    def normalize(self, raw: dict) -> "Listing | None":
        # Accepts both the wrapped form and a bare ad, so the Phase 1 raw file
        # still parses without re-crawling.
        ad = raw.get("ad") if "ad" in raw else raw
        return normalize_ad(ad) if isinstance(ad, dict) else None

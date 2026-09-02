"""Source adapter interface.

Phase 1 crawled one site, so parsing lived inside the crawler. With several
sources that no longer works: each site has its own pagination, its own field
names, and its own idea of what a price is. A source therefore owns two things
and nothing else —

    iter_raw()   fetch records, changing nothing
    normalize()  turn one record into the shared `Listing`

Everything downstream (pricing, health, search) sees only `Listing`, so adding a
site never touches the product logic.

Raw records are written to `data/{source}_raw.jsonl` untouched, so re-parsing
after a normalization fix never means re-crawling — the rule that saved a lot of
time in Phase 1.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from ..normalize import Listing, make_code

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


__all__ = ["Source", "make_code", "register", "get_source", "available", "USER_AGENT"]


#: How many times to try one request before giving up on it.
ATTEMPTS = 5
#: Ceiling on the extra pause a run of 429s can impose.
MAX_THROTTLE_S = 8.0


class Source(ABC):
    """One website."""

    name: str = "unknown"
    #: Seconds between requests. Politeness, not performance.
    delay: float = 1.0

    def __init__(self, timeout: float = 25.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        #: Extra seconds added before every request, grown by 429s and decayed
        #: by success. See `_request`.
        self._throttle = 0.0

    async def __aenter__(self) -> "Source":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> dict | None:
        """One request with retries. Returns None instead of raising so a single
        bad page can never abort a long crawl.

        Rate limits are handled by slowing the *whole* source down, not just by
        retrying the one request that tripped them. Divar's detail endpoint
        answers in about 70ms but limits bursts rather than a steady rate: it
        serves roughly thirty requests and then returns 429 until it refills.
        Retrying such a request a fixed three times just burns the budget and
        then drops the listing — silently, because a dropped detail is
        indistinguishable from a car that failed to parse.

        So a 429 raises `_throttle`, which every subsequent request waits out,
        and a success decays it again. The crawl finds the site's pace instead
        of being told one that may be wrong for the day.
        """
        for attempt in range(ATTEMPTS):
            if self._throttle:
                await asyncio.sleep(self._throttle)
            try:
                resp = await self._client.request(method, url, params=params, json=json_body)
                if resp.status_code == 200:
                    # Decay slowly. Shedding the throttle in two or three
                    # successes just walks straight back into the limit; the
                    # point is to settle near the site's pace, not to sprint at
                    # it again the moment one request gets through.
                    self._throttle = self._throttle * 0.92 if self._throttle > 0.05 else 0.0
                    return resp.json()
                if resp.status_code == 429:
                    self._throttle = min(MAX_THROTTLE_S, max(1.0, self._throttle * 2))
                    log.debug("[%s] 429; throttle now %.2fs", self.name, self._throttle)
                    continue
                if resp.status_code in (500, 502, 503, 504):
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                log.warning("[%s] %s %s -> HTTP %s", self.name, method, url, resp.status_code)
                return None
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("[%s] %s failed (attempt %d): %s", self.name, url, attempt + 1, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
        log.warning("[%s] gave up on %s after %d attempts", self.name, url, ATTEMPTS)
        return None

    @abstractmethod
    async def iter_raw(self, *, max_pages: int, **options: Any) -> AsyncIterator[dict]:
        """Yield raw records exactly as the site returned them."""
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw: dict) -> Listing | None:
        """Convert one raw record into a Listing, or None if unusable."""
        raise NotImplementedError

    @staticmethod
    def raw_id(raw: dict) -> str | None:
        """Native id for deduplication during the crawl."""
        return raw.get("_id")


_REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    _REGISTRY[cls.name] = cls
    return cls


def get_source(name: str) -> type[Source]:
    if name not in _REGISTRY:
        raise KeyError(f"unknown source {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def available() -> list[str]:
    return sorted(_REGISTRY)

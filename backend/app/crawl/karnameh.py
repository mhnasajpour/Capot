"""Karnameh adapter.

Karnameh is a curated, inspection-led used-car marketplace rather than open
classifieds, and it is small: `total` reads 346 across 18 pages, and the
brand-scoped routes return subsets of that same pool rather than adding to it.
It is here for data quality, not volume.

There is no public REST API, but the site is a Next.js pages-router app, so the
data its own pages are built from is served as JSON:

    GET /buy-used-cars                              -> scrape "buildId"
    GET /_next/data/{buildId}/buy-used-cars.json    -> pageProps.firstPage

Two quirks, both found the hard way:

  * `?page=1` returns a redirect stub (`__N_REDIRECT`) and no posts. Page one
    must be requested with no query string at all.
  * `buildId` changes on every deploy, so it cannot be pinned. It is scraped at
    the start of each crawl, and a miss raises rather than quietly yielding zero
    listings — a silent empty crawl is the failure mode worth designing against.

What makes it worth the trouble is the shape of the data. Every other source
here publishes presentation strings; Karnameh publishes typed records:

    year 1402 (int)   usage 32500 (int)   price 1855000000 (int)

Two fields in particular earn their place:

  * `brand_name_en` alongside `brand_name_fa` (and the same for model and trim).
    `canonical.BrandResolver` learns the Persian->latin mapping from sources
    that carry both, which until now meant Bama alone. Karnameh reinforces it,
    and needs no resolution itself.
  * `has_inspection` — Karnameh inspects the cars it lists, which is the thing
    it sells; no other source here carries an inspection flag.

`prepayment_amount` looked like the answer to the down-payment trap `pricing.py`
spends real effort on — a listing whose advertised price is really its deposit.
It is not. Measured over 60 listings it is present on every one and sits at
63-79% of `price` whether or not `is_leasing_available` is set: it is a
financing quote Karnameh computes for every car, not something a seller
advertised. So `price` is always the real full price here, and the prepayment is
deliberately not recorded — folding a derived number into `description` would
put noise into the text that search indexes and `enrich.py` reads.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, AsyncIterator

from ..normalize import CURRENT_GREGORIAN_YEAR, Listing, body_status_grade, parse_year
from .base import Source, make_code, register
from .divar import SELLER_DEALER, SELLER_PRIVATE

log = logging.getLogger(__name__)

SITE = "https://karnameh.com"
LIST_PAGE = f"{SITE}/buy-used-cars"
#: Where a car's own page lives. Note `/used-cars/`, not `/buy-used-cars/`.
DETAIL_PATH = f"{SITE}/used-cars"

BUILD_ID_RE = re.compile(r'"buildId":"([^"]+)"')

TRANSMISSION_MAP = {
    "دنده‌ای": "دنده ای", "دنده ای": "دنده ای", "اتوماتیک": "اتوماتیک",
}


def data_url(build_id: str, page: int) -> str:
    """Page 1 must carry no query string; `?page=1` redirects and yields nothing."""
    base = f"{SITE}/_next/data/{build_id}/buy-used-cars.json"
    return base if page <= 1 else f"{base}?page={page}"


def car_posts(payload: dict) -> list[dict]:
    first_page = (payload.get("pageProps") or {}).get("firstPage") or {}
    return first_page.get("car_posts") or []


def page_count(payload: dict) -> int:
    first_page = (payload.get("pageProps") or {}).get("firstPage") or {}
    return int(first_page.get("pages") or 0)


@register
class KarnamehSource(Source):
    name = "karnameh"
    delay = 1.0

    async def build_id(self) -> str:
        """Scrape the current Next.js build id.

        Deliberately raises instead of returning None: a wrong or missing build
        id produces a crawl that succeeds with zero records, which is far more
        expensive to notice than a crash.
        """
        response = await self._client.get(LIST_PAGE, headers={"Accept": "text/html"})
        match = BUILD_ID_RE.search(response.text)
        if not match:
            raise RuntimeError(
                f"karnameh: no buildId in {LIST_PAGE} — the site's build layout "
                "changed and the adapter needs revisiting"
            )
        return match.group(1)

    async def iter_raw(
        self,
        *,
        max_pages: int,
        skip_ids: set[str] | None = None,
        **options: Any,
    ) -> AsyncIterator[dict]:
        seen: set[str] = set(skip_ids or ())
        build = await self.build_id()
        log.info("[karnameh] buildId %s", build)

        total_pages = max_pages
        for page in range(1, max_pages + 1):
            if page > total_pages:
                break
            payload = await self._request(data_url(build, page))
            if not payload:
                break

            if page == 1 and page_count(payload):
                # The site knows how many pages it has; past the last one it
                # serves redirect stubs rather than an empty list.
                total_pages = min(max_pages, page_count(payload))
                log.info("[karnameh] %d pages advertised", page_count(payload))

            posts = car_posts(payload)
            if not posts:
                break

            for post in posts:
                token = post.get("concierge_sale_token")
                if not token or token in seen:
                    continue
                seen.add(token)
                yield {"_id": token, "_source": self.name, "post": post}

            await asyncio.sleep(self.delay)

        log.info("[karnameh] %d listings", len(seen))

    def normalize(self, raw: dict) -> Listing | None:
        post = raw.get("post") or {}
        token = raw.get("_id") or post.get("concierge_sale_token")
        if not token:
            return None

        brand_fa = post.get("brand_name_fa")
        brand_en = (post.get("brand_name_en") or "").lower() or None
        if not brand_fa and not brand_en:
            return None  # without a brand it can't join any price cohort

        # `year` is a bare integer in whichever calendar the seller used.
        raw_year = post.get("year")
        year, calendar = parse_year(raw_year)

        price = post.get("price")
        negotiable = not price

        return Listing(
            code=make_code(self.name, str(token)),
            url=f"{DETAIL_PATH}/{token}",
            title=(post.get("title") or "").strip(),
            # Karnameh publishes both halves, so unlike Divar and Sheypoor it
            # needs no resolution — and teaches the mapping instead.
            brand=brand_en,
            brand_fa=brand_fa,
            model=(post.get("model_name_en") or "").lower() or None,
            trim=post.get("type_name_fa"),
            trim_en=(post.get("type_name_en") or "").lower() or None,
            year=year,
            year_display=raw_year if isinstance(raw_year, int) else None,
            year_calendar=calendar,
            age=(CURRENT_GREGORIAN_YEAR - year) if year else None,
            mileage_km=post.get("usage"),
            price_toman=price or None,
            is_negotiable=negotiable,
            price_type="negotiable" if negotiable else "lumpsum",
            # Karnameh states no paint condition; the inspection report it sells
            # is the thing it has instead. `body_status_grade(None)` is the
            # documented middling default rather than an invented grade — and
            # it must not be left as None, because the paint filter reads a
            # missing grade as `or 0` and would drop every Karnameh car as if
            # it were a wreck.
            body_status=None,
            body_grade=body_status_grade(None),
            body_type=None,
            body_type_fa=None,
            transmission=TRANSMISSION_MAP.get((post.get("gearbox_name_fa") or "").strip()),
            fuel=None,
            body_color=post.get("color") or None,
            inside_color=None,
            seller=SELLER_DEALER if post.get("is_professional") else SELLER_PRIVATE,
            dealer_name=None,
            dealer_score=None,
            dealer_ad_count=None,
            authenticated=bool(post.get("is_authentic") or post.get("has_inspection")),
            city=post.get("city_name_fa"),
            location=None,
            # Karnameh carries no seller prose — the title is all the free text
            # there is. `prepayment_amount` is not appended: see the module
            # docstring for why that number is not what it looks like.
            description=(post.get("title") or "").strip() or None,
            image=post.get("image"),
            image_count=post.get("image_count") or 0,
            engine_volume_l=None,
            power_hp=None,
            acceleration_s=None,
            consumption_l100=None,
            modified_date=None,
            life_styles=[],
            source=self.name,
            model_fa=post.get("model_name_fa"),
            insurance_months=None,
            chassis_status=None,
        )

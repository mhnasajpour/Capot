"""Divar adapter.

Divar is Iran's largest classifieds site. Its web API is public and needs no
key, but it returns *presentation* data rather than clean records — prices and
mileages arrive as display strings in Persian digits, and the useful fields live
inside typed UI widgets.

Two endpoints:

    POST /v8/postlist/w/search      24 posts per page, list view only
    GET  /v8/posts-v2/web/{token}   the actual fields, one request per listing

The list view carries no year, brand, model or body condition, so the detail
fetch is mandatory — one request per car, which makes this the most expensive
source per listing. Those fetches run through a small worker pool
(`concurrency`) rather than back to back; sequentially a national crawl takes
the better part of a day. Crawl once to JSONL, never at demo time.

What the detail view gives us, from `GROUP_INFO_ROW` / `UNEXPANDABLE_ROW`
widgets plus the category breadcrumb:

    breadcrumb       وسایل نقلیه › خودرو › پژو › 206 › تیپ ۵   -> brand/model/trim
    کارکرد            ۳۰۰۰۰۰                                    -> mileage
    مدل (سال تولید)   ۱۳۹۰ - ۲۰۱۱                               -> both calendars
    قیمت پایه         ۹۵۵,۰۰۰,۰۰۰ تومان                         -> price
    گیربکس / نوع سوخت / رنگ / وضعیت بدنه
    مهلت بیمهٔ شخص ثالث, معاینه فنی                            -> signals Bama lacks

One gotcha worth recording: `pagination_data.last_post_date` must be RFC3339
with a `Z`. Sending `"0"` returns HTTP 400.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from ..normalize import (
    CURRENT_GREGORIAN_YEAR,
    JALALI_OFFSET,
    Listing,
    body_status_grade,
    fa_to_en_digits,
    infer_body_status,
    parse_mileage,
    parse_number,
)
from .base import Source, make_code, register

log = logging.getLogger(__name__)

API = "https://api.divar.ir/v8"
SEARCH_URL = f"{API}/postlist/w/search"
DETAIL_URL = f"{API}/posts-v2/web"

EPOCH = "1970-01-01T00:00:00Z"

# Divar city ids, verified against GET /v8/places/cities. Tehran dominates the
# market, but crawling it alone was how this source ended up at 1,117 listings
# against Bama's 9,798 — every raw record carried city_persian == 'تهران'.
#
# Note ids 5 and 6: the previous comment here had them the wrong way round.
DEFAULT_CITIES = [
    "1",   # تهران
    "2",   # کرج
    "3",   # مشهد
    "4",   # اصفهان
    "6",   # شیراز
    "5",   # تبریز
    "7",   # اهواز
    "8",   # قم
    "9",   # کرمانشاه
    "10",  # ارومیه
    "12",  # رشت
    "13",  # کرمان
]

# Divar's own vocabulary, mapped onto the shapes the rest of the app expects
# (Bama's wording, since that is what normalize.py and the UI already speak).
TRANSMISSION_MAP = {
    "دنده‌ای": "دنده ای", "دنده ای": "دنده ای", "اتوماتیک": "اتوماتیک",
}
FUEL_MAP = {
    "بنزین": "بنزینی", "بنزینی": "بنزینی", "دوگانه سوز": "دوگانه سوز",
    "دوگانه‌سوز": "دوگانه سوز", "گازوئیل": "دیزلی", "دیزل": "دیزلی",
    "هیبرید": "هیبریدی", "برقی": "برقی",
}
# Divar grades body condition with different phrases from Bama, so they need an
# explicit mapping onto the same 0-100 paint-integrity scale.
BODY_STATUS_MAP = {
    "سالم و بی‌خط و خش": 100,
    "سالم و بی خط و خش": 100,
    "خط و خش جزیی": 80,
    "خط و خش جزئی": 80,
    "صافکاری بدون رنگ": 85,
    "رنگ‌شدگی": 55,
    "رنگ شدگی": 55,
    "دور رنگ": 28,
    "تمام رنگ": 22,
    "تصادفی": 15,
    "اوراقی": 5,
}

SELLER_PRIVATE = "شخصی"
SELLER_DEALER = "نمایشگاه"

# Divar frequently omits وضعیت بدنه entirely — none of the sampled listings
# carried it — so `infer_body_status` reads it out of the title and description
# instead. It lives in `normalize.py` now, beside the declared-field grading it
# mirrors, because the appraisal path reads a car owner's own prose the same
# way. Imported above rather than defined here, so `from .divar import
# infer_body_status` still resolves for this adapter's tests.


def _widgets(payload: dict) -> list[dict]:
    """Flatten every widget in a detail payload, whatever section it sits in."""
    found: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "widget_type" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return found


def extract_fields(detail: dict) -> dict[str, str]:
    """Collect every label/value pair the detail page exposes."""
    fields: dict[str, str] = {}
    for widget in _widgets(detail):
        data = widget.get("data") or {}
        kind = widget.get("widget_type")

        if kind == "GROUP_INFO_ROW":
            for item in data.get("items") or []:
                title, value = item.get("title"), item.get("value")
                if title and value is not None:
                    fields[str(title).strip()] = str(value).strip()

        elif kind in ("UNEXPANDABLE_ROW", "INFO_ROW"):
            title, value = data.get("title"), data.get("value")
            if title and value is not None:
                fields[str(title).strip()] = str(value).strip()

        elif kind == "LEGEND_TITLE_ROW" and data.get("title"):
            fields.setdefault("_title", str(data["title"]).strip())
    return fields


def extract_breadcrumb(detail: dict) -> list[str]:
    """`['وسایل نقلیه','خودرو','خودرو سواری و وانت','پژو','206','تیپ ۵']`."""
    for widget in _widgets(detail):
        items = (widget.get("data") or {}).get("parent_items")
        if items:
            return [str(i.get("title", "")).strip() for i in items if i.get("title")]
    return []


def extract_description(detail: dict) -> str | None:
    """The longest free-text blob on the page is the seller's description."""
    best = ""
    for widget in _widgets(detail):
        if widget.get("widget_type") not in ("DESCRIPTION_ROW", "EXPANDABLE_ROW", "TITLE_ROW"):
            continue
        text = (widget.get("data") or {}).get("text") or ""
        if len(text) > len(best):
            best = text
    return best.strip() or None


def _field(fields: dict[str, str], *names: str) -> str | None:
    """First matching label, tolerant of Divar's punctuation drift."""
    for name in names:
        if name in fields:
            return fields[name]
    for key, value in fields.items():
        for name in names:
            if name in key:
                return value
    return None


def parse_divar_year(raw: str | None) -> tuple[int | None, int | None, str | None]:
    """`'۱۳۹۰ - ۲۰۱۱'` -> (gregorian, displayed, calendar).

    Domestic cars show both calendars; imports usually show only Gregorian.
    """
    if not raw:
        return None, None, None
    numbers = [int(n) for n in fa_to_en_digits(raw).replace(",", "").split() if n.isdigit()]
    numbers = [n for n in numbers if 1200 < n < 2100]
    if not numbers:
        return None, None, None

    jalali = next((n for n in numbers if n < 1500), None)
    gregorian = next((n for n in numbers if n > 1500), None)

    if jalali and gregorian:
        return gregorian, jalali, "jalali"
    if jalali:
        return jalali + JALALI_OFFSET, jalali, "jalali"
    return gregorian, gregorian, "gregorian"


@register
class DivarSource(Source):
    name = "divar"
    #: Seconds a worker waits after its own request, not a global pause.
    #: Lower than the 0.6 this used to run at: the endpoint answers in ~70ms,
    #: so most of that pause was ours, not the site's.
    delay = 0.35
    #: Detail requests in flight at once.
    #:
    #: Two, not more, and the reason is measured rather than cautious. Divar
    #: limits bursts, not throughput: at five workers half the requests come
    #: back 429, and at ten every one does. Raising this does not go faster, it
    #: just converts listings into retries — the first attempt at a five-worker
    #: pool ran 1.2x quicker and lost 8 cars of 48 doing it. The throughput
    #: comes from `delay` and from `Source._request` finding the pace itself.
    concurrency = 2

    async def _detail(self, token: str, sem: "asyncio.Semaphore") -> tuple[str, dict | None]:
        """One detail fetch, holding a worker slot for its own delay."""
        async with sem:
            detail = await self._request(f"{DETAIL_URL}/{token}")
            await asyncio.sleep(self.delay)
            return token, detail

    async def iter_raw(
        self,
        *,
        max_pages: int,
        cities: list[str] | None = None,
        skip_ids: set[str] | None = None,
        concurrency: int | None = None,
        **options: Any,
    ) -> AsyncIterator[dict]:
        """Walk the car category, fetching each listing's detail record."""
        cities = cities or DEFAULT_CITIES
        # Tokens already on disk from an earlier run: skipping them here avoids
        # the per-listing detail request, which is the expensive part.
        seen: set[str] = set(skip_ids or ())
        sem = asyncio.Semaphore(concurrency or self.concurrency)

        for city in cities:
            before = len(seen)
            pagination: dict[str, Any] = {
                "@type": "type.googleapis.com/post_list.PaginationData",
                "last_post_date": EPOCH,
                "page": 1,
                "layer_page": 1,
            }

            for page in range(max_pages):
                body = {
                    "city_ids": [city],
                    "search_data": {
                        "form_data": {
                            "data": {"category": {"str": {"value": "light"}}}
                        }
                    },
                    "pagination_data": pagination,
                }
                payload = await self._request(SEARCH_URL, method="POST", json_body=body)
                if not payload:
                    break

                rows = [
                    w for w in payload.get("list_widgets", [])
                    if w.get("widget_type") == "POST_ROW"
                ]
                if not rows:
                    break

                # Claim tokens before fetching, so a token is never fetched
                # twice even though the fetches themselves now overlap.
                batch: dict[str, dict] = {}
                for row in rows:
                    data = row.get("data") or {}
                    token = ((data.get("action") or {}).get("payload") or {}).get("token")
                    if not token or token in seen:
                        continue
                    seen.add(token)
                    batch[token] = data

                if batch:
                    tasks = [self._detail(token, sem) for token in batch]
                    for coro in asyncio.as_completed(tasks):
                        token, detail = await coro
                        if not detail:
                            continue
                        yield {
                            "_id": token,
                            "_source": self.name,
                            "list": batch[token],
                            "detail": detail,
                        }

                # Divar hands back the cursor for the next page; fall back to a
                # plain page increment if it stops doing so.
                nxt = payload.get("pagination", {}).get("data")
                if isinstance(nxt, dict) and nxt.get("last_post_date"):
                    pagination = {**pagination, **nxt}
                else:
                    pagination = {**pagination, "page": page + 2, "layer_page": page + 2}

            # Per-city yield, so a wrong city id shows up as a zero here rather
            # than silently shrinking the crawl.
            log.info(
                "[divar] city %s done: %d new (%d total)",
                city, len(seen) - before, len(seen),
            )

    def normalize(self, raw: dict) -> Listing | None:
        token = raw.get("_id")
        detail = raw.get("detail") or {}
        listing_row = raw.get("list") or {}
        if not token or not detail:
            return None

        fields = extract_fields(detail)
        crumbs = extract_breadcrumb(detail)

        brand_fa = crumbs[3] if len(crumbs) > 3 else None
        model_fa = crumbs[4] if len(crumbs) > 4 else None
        trim_fa = crumbs[5] if len(crumbs) > 5 else None
        if not brand_fa:
            return None  # without a brand it can't join any price cohort

        title = fields.get("_title") or listing_row.get("title") or ""
        year, year_display, calendar = parse_divar_year(
            _field(fields, "مدل (سال تولید)", "سال تولید", "مدل")
        )

        price_raw = _field(fields, "قیمت پایه", "قیمت کل", "قیمت")
        price = parse_number(price_raw) if price_raw else None
        # Divar hides price as "توافقی" the same way Bama does.
        negotiable = not price or "توافقی" in (price_raw or "")

        mileage = parse_mileage(_field(fields, "کارکرد"))
        body_status = _field(fields, "وضعیت بدنه", "بدنه")
        transmission = TRANSMISSION_MAP.get((_field(fields, "گیربکس") or "").strip())
        fuel = FUEL_MAP.get((_field(fields, "نوع سوخت", "سوخت") or "").strip())

        ownership = _field(fields, "مالکیت خودرو") or ""
        seller = SELLER_PRIVATE if "مالک" in ownership else SELLER_DEALER

        web_info = ((listing_row.get("action") or {}).get("payload") or {}).get("web_info") or {}
        city = web_info.get("city_persian")

        description = extract_description(detail)
        grade = BODY_STATUS_MAP.get((body_status or "").strip())
        if body_status and grade is None:
            grade = body_status_grade(body_status)
        if not body_status:
            # Divar usually omits the field; sellers say it in prose instead.
            inferred, inferred_grade = infer_body_status(title, description)
            if inferred:
                body_status, grade = inferred, inferred_grade
        if grade is None:
            grade = body_status_grade(body_status)

        return Listing(
            code=make_code(self.name, token),
            url=f"https://divar.ir/v/{token}",
            title=title.strip(),
            brand=None,          # resolved later by canonical.py
            brand_fa=brand_fa,
            model=None,
            trim=trim_fa,
            trim_en=None,
            year=year,
            year_display=year_display,
            year_calendar=calendar,
            age=(CURRENT_GREGORIAN_YEAR - year) if year else None,
            mileage_km=mileage,
            price_toman=None if negotiable else price,
            is_negotiable=bool(negotiable),
            price_type="negotiable" if negotiable else "lumpsum",
            body_status=body_status,
            body_grade=grade,
            body_type=None,
            body_type_fa=None,
            transmission=transmission,
            fuel=fuel,
            body_color=_field(fields, "رنگ"),
            inside_color=None,
            seller=seller,
            dealer_name=None,
            dealer_score=None,
            dealer_ad_count=None,
            # Divar has no inspection badge of its own; a valid technical
            # inspection is the closest equivalent signal it offers.
            authenticated=bool(_field(fields, "معاینه فنی")),
            city=city,
            location=web_info.get("district_persian"),
            description=description,
            image=listing_row.get("image_url"),
            image_count=listing_row.get("image_count") or 0,
            engine_volume_l=None,
            power_hp=None,
            acceleration_s=None,
            consumption_l100=None,
            modified_date=None,
            life_styles=[],
            source=self.name,
            model_fa=model_fa,
            insurance_months=parse_number(_field(fields, "بیمهٔ شخص ثالث", "بیمه شخص ثالث", "بیمه")),
        )

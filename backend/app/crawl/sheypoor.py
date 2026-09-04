"""Sheypoor adapter.

Sheypoor is Iran's other large general classifieds site. Its web API is public,
needs no key, and speaks JSON:API — which makes it the cheapest of the four
sources per car by a wide margin:

    GET /api/v10.0.0/search?c=43627&p=N     24 rows per page

`c=43627` is the خودرو category id, taken from `/api/v10.0.0/search/filters/car`
rather than hard-guessed. Getting that filter wrong is not loud: without it the
endpoint happily returns the whole site — `meta.total` reads 739,791 across
every category instead of 64,429 cars — and the rows are apartments. So the
category is asserted at parse time from each row's own breadcrumb, not trusted
from the query.

The reason this source is worth having: **`fullAttributes` ships inside the
search response**, so unlike Divar there is no per-listing detail request. One
HTTP call yields 24 fully-specified cars rather than one. Measured coverage over
60 rows: year, colour, gearbox, fuel and وضعیت بدنه on 60/60, mileage on 59/60.

That وضعیت بدنه column is the point. Divar omits body condition on nearly every
listing, which is why `divar.infer_body_status` has to read it out of prose;
Sheypoor declares it outright, and body condition is the strongest single input
to the health score.

Two things it gives that no other source here does: an explicit chassis
condition (وضعیت شاسی جلو/عقب), and a free-text description on 100% of rows.

Sheypoor's paint vocabulary is its own — 'سالم بدون خط و خش' where Divar says
'سالم و بی‌خط و خش' — so it needs its own phrase table rather than Divar's.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator
from urllib.parse import urlencode

from ..normalize import (
    CURRENT_GREGORIAN_YEAR,
    FUEL_MAP,
    SELLER_DEALER,
    SELLER_PRIVATE,
    TRANSMISSION_MAP,
    Listing,
    body_status_grade,
    parse_mileage,
    parse_number,
    parse_year,
)
from .base import Source, make_code, register

log = logging.getLogger(__name__)

API = "https://www.sheypoor.com/api/v10.0.0"
SEARCH_URL = f"{API}/search"

#: خودرو. From /api/v10.0.0/search/filters/car -> meta.search_variables.c.id
CAR_CATEGORY_ID = "43627"
#: The breadcrumb name that confirms a row really is a car.
CAR_CATEGORY_NAME = "خودرو"

#: Sheypoor's own paint-condition wording, on the same 0-100 scale the rest of
#: the app uses. Only the two 'سالم' phrases are new — 'یک لکه رنگ' and friends
#: already exist in `normalize.BODY_STATUS_GRADE`, so those fall through to it.
BODY_STATUS_MAP = {
    "سالم بدون خط و خش": 100,
    "سالم و بدون خط و خش": 100,
    "سالم با خط و خش": 82,
    "یک لکه رنگ": 70,
    "دو لکه رنگ": 58,
    "چند لکه رنگ": 45,
    "دور رنگ": 28,
    "تمام رنگ": 22,
    "تصادفی": 15,
    "اوراقی": 5,
}

#: Sheypoor's way of saying "the seller didn't answer this", which is not the
#: same as a healthy chassis and must not be recorded as one.
NOT_DECLARED = "اعلام نشده"

#: How many consecutive already-seen pages end a crawl. Generous, because a
#: resumed run walks back over everything it already has before reaching new
#: ground, and because the feed reorders as sellers bump their ads.
STALE_PAGES = 25

# Attribute labels, as they appear in `fullAttributes[].key`.
K_MODEL = "مدل خودرو"
K_YEAR = "سال تولید (چهار رقمی)"
K_MILEAGE = "کیلومتر"
K_BODY = "وضعیت بدنه"
K_GEARBOX = "گیربکس"
K_FUEL = "نوع سوخت"
K_COLOR = "رنگ"
K_CHASSIS_TYPE = "نوع شاسی"
K_CHASSIS_FRONT = "وضعیت شاسی جلو"
K_CHASSIS_REAR = "وضعیت شاسی عقب"


def attributes(row: dict) -> dict[str, str]:
    """`fullAttributes` is a list of {key, value} pairs; we want a lookup."""
    found: dict[str, str] = {}
    for item in row.get("fullAttributes") or []:
        key, value = item.get("key"), item.get("value")
        if key and value not in (None, ""):
            found[str(key).strip()] = str(value).strip()
    return found


def listing_rows(payload: dict) -> list[dict]:
    """The car ads on one page, with the paid furniture dropped.

    A page mixes real ads with `paidEngagement`, `banner`, `nativeAd` and
    `catalogLink` entries, the same way Bama's feed mixes ads with banners.
    `vip` is not a listing either — it is a carousel whose `items` are, so it
    gets unwrapped rather than skipped.
    """
    rows: list[dict] = []
    for entry in payload.get("data") or []:
        kind = entry.get("type")
        if kind == "vip":
            rows.extend(
                item for item in entry.get("items") or []
                if item.get("id") and item.get("attributes")
            )
        # Not `kind in ("normal", "vip")`: the first branch has already taken
        # every vip entry, so that arm could never fire on one.
        elif kind == "normal" and entry.get("id") and entry.get("attributes"):
            rows.append(entry)
    return rows


def parse_price(row_attrs: dict) -> tuple[int | None, bool]:
    """`[{'amount': '1,150,000,000', 'currency': 'تومان'}]` -> (toman, negotiable).

    A hidden price arrives as the literal string 'توافقی' in `amount`. Those
    become NULL, never 0 — they are the listings the product exists to price.
    """
    entries = row_attrs.get("price") or []
    amount = str((entries[0] if entries else {}).get("amount") or "").strip()
    if not amount or "توافقی" in amount:
        return None, True
    value = parse_number(amount)
    return (value, False) if value else (None, True)


def parse_city(location: str | None) -> tuple[str | None, str | None]:
    """'قائم شهر، خیابان تهران' -> ('قائم شهر', 'خیابان تهران').

    Sheypoor separates city from neighbourhood with a Persian comma, where
    Bama uses a slash — so `normalize._city_from_location` does not apply.
    """
    if not location:
        return None, None
    parts = [p.strip() for p in location.split("،") if p.strip()]
    if not parts:
        return None, None
    return parts[0], (parts[1] if len(parts) > 1 else None)


def chassis_condition(fields: dict[str, str]) -> str | None:
    """Combine front and rear chassis condition into one reportable phrase."""
    front = fields.get(K_CHASSIS_FRONT)
    rear = fields.get(K_CHASSIS_REAR)
    parts = [
        f"{label} {value}"
        for label, value in (("جلو", front), ("عقب", rear))
        if value and value != NOT_DECLARED
    ]
    return "، ".join(parts) or None


@register
class SheypoorSource(Source):
    name = "sheypoor"
    #: Measured: a tighter loop than this starts timing out around page 2.
    delay = 1.2

    async def iter_raw(
        self,
        *,
        max_pages: int,
        skip_ids: set[str] | None = None,
        **options: Any,
    ) -> AsyncIterator[dict]:
        """Walk the car category. No detail request — the rows are complete."""
        seen: set[str] = set(skip_ids or ())
        cursor: str | None = None
        # Consecutive pages that yielded nothing new. A resumed crawl re-walks
        # the pages it already has, so stopping at the first stale one would
        # end the run on page 1 and make `--append` useless. Bama's adapter
        # counts a run of stale results for the same reason.
        stale = 0

        for page in range(1, max_pages + 1):
            query = {"c": CAR_CATEGORY_ID, "p": str(page)}
            if cursor:
                query["f"] = cursor
            payload = await self._request(f"{SEARCH_URL}?{urlencode(query)}")
            if not payload:
                break

            rows = listing_rows(payload)
            if not rows:
                break

            fresh = 0
            for row in rows:
                row_id = str(row.get("id"))
                if row_id in seen:
                    continue
                seen.add(row_id)
                fresh += 1
                yield {"_id": row_id, "_source": self.name, "row": row}

            # `meta.f` is the cursor for the next page. `meta.total` is not a
            # corpus size worth trusting — it reported the whole site until the
            # category filter was right — so stop on an empty page instead.
            cursor = (payload.get("meta") or {}).get("f") or cursor
            if page % 25 == 0:
                log.info("[sheypoor] page %d, %d listings so far", page, len(seen))

            stale = stale + 1 if not fresh else 0
            if stale >= STALE_PAGES:
                log.info("[sheypoor] %d pages with nothing new; stopping", stale)
                break
            await asyncio.sleep(self.delay)

    def normalize(self, raw: dict) -> Listing | None:
        row = raw.get("row") or {}
        row_id = raw.get("_id") or row.get("id")
        attrs = row.get("attributes") or {}
        if not row_id or not attrs:
            return None

        crumbs = [c.get("name") for c in attrs.get("categories") or []]
        # The breadcrumb is the check that this is a car at all: a mis-set
        # category filter returns apartments without erroring.
        if CAR_CATEGORY_NAME not in crumbs:
            return None
        brand_fa = crumbs[2] if len(crumbs) > 2 else None
        if not brand_fa:
            return None  # without a brand it can't join any price cohort

        fields = attributes(row)
        price, negotiable = parse_price(attrs)
        year, calendar = parse_year(fields.get(K_YEAR))
        year_display = parse_number(fields.get(K_YEAR))
        city, district = parse_city(attrs.get("location"))

        body_status = fields.get(K_BODY)
        grade = BODY_STATUS_MAP.get((body_status or "").strip())
        if grade is None:
            grade = body_status_grade(body_status)

        images = (attrs.get("images") or {}).get("thumbnails") or {}

        return Listing(
            code=make_code(self.name, str(row_id)),
            url=attrs.get("url"),
            title=(attrs.get("title") or "").strip(),
            brand=None,          # resolved later by canonical.py
            brand_fa=brand_fa,
            model=None,
            trim=None,
            trim_en=None,
            year=year,
            year_display=year_display,
            year_calendar=calendar,
            age=(CURRENT_GREGORIAN_YEAR - year) if year else None,
            mileage_km=parse_mileage(fields.get(K_MILEAGE)),
            price_toman=price,
            is_negotiable=negotiable,
            price_type="negotiable" if negotiable else "lumpsum",
            body_status=body_status,
            body_grade=grade,
            body_type=None,
            body_type_fa=fields.get(K_CHASSIS_TYPE),
            transmission=TRANSMISSION_MAP.get((fields.get(K_GEARBOX) or "").strip()),
            fuel=FUEL_MAP.get((fields.get(K_FUEL) or "").strip()),
            body_color=fields.get(K_COLOR),
            inside_color=None,
            # A shop logo means the ad belongs to a Sheypoor storefront; there
            # is no explicit private/dealer flag on the row.
            seller=SELLER_DEALER if attrs.get("shopLogo") else SELLER_PRIVATE,
            dealer_name=None,
            dealer_score=None,
            dealer_ad_count=None,
            authenticated=bool(attrs.get("isSecurePurchase")),
            city=city,
            location=district,
            description=(row.get("description") or "").strip() or None,
            image=images.get("landscape") or images.get("round"),
            image_count=attrs.get("imageCount") or 0,
            engine_volume_l=None,
            power_hp=None,
            acceleration_s=None,
            consumption_l100=None,
            modified_date=None,
            life_styles=[],
            source=self.name,
            # The parenthesised suffix is trim detail ('131 (بنزینی)',
            # '405 GLX (TU5 بنزینی)'); the cohort join wants the bare model.
            model_fa=(fields.get(K_MODEL) or "").split("(")[0].strip() or None,
            insurance_months=None,
            chassis_status=chassis_condition(fields),
        )

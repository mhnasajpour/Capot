"""Cross-source identity: make two sites agree on what car this is.

Bama and Divar describe the same Peugeot 206 completely differently:

    Bama    brand='peugeot'  model='206ir'   title='پژو، 206'
    Divar   brand=None       model=None      breadcrumb=['پژو', '206', 'تیپ ۵']

Divar gives Persian names only, so without a mapping every Divar car lands in
its own cohort, the fair-price model can't pool comparables across sources, and
the same car listed twice looks like two different cars.

Persian names are the join key, because they're the one thing both sites agree
on. The mapping is *learned from Bama*, which publishes `brand` and `brand_fa`
together for 80-plus marques, so almost nothing is hand-written.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Iterable

from .lexicon import BRAND_ALIASES, fold, split_title
from .normalize import Listing

log = logging.getLogger(__name__)

# Marques whose Persian spelling on Divar differs from Bama's, or that Bama
# doesn't carry. Everything else is derived from the data.
BRAND_FA_OVERRIDES = {
    "بی ام و": "bmw", "بی‌ام‌و": "bmw", "ب ام و": "bmw",
    "مرسدس بنز": "benz", "مرسدس": "benz", "بنز": "benz",
    "ام وی ام": "mvm", "ام‌وی‌ام": "mvm",
    "ایران خودرو": "ikco", "سایپا": "saipa",
    "فولکس واگن": "volkswagen", "فولکس": "volkswagen",
    "هیوندا": "hyundai", "هیوندای": "hyundai",
}

# How close two listings must be to count as the same physical car.
PRICE_TOLERANCE = 0.03
MILEAGE_TOLERANCE = 0.02


class BrandResolver:
    """Persian brand/model names -> the slugs the rest of the app uses."""

    def __init__(self) -> None:
        # Seeded from the search vocabulary first, so a slug learned from a
        # crawl can never contradict the one a buyer's query resolves to.
        #
        # This is not hypothetical. Bama carries no رانا at all, so nothing
        # taught that marque until Karnameh — which calls it 'Runna' — arrived
        # as a source that publishes both name forms. Twenty-six Ranas were
        # then stored under `runna` while «رانا» searched for `rana`, and the
        # query answered "no such car" over all of them. That is the same bug
        # `db._row_to_dict`'s alias backfill was written to fix, reintroduced
        # from the other end.
        self.brand_by_fa: dict[str, str] = {fold(k): v for k, v in BRAND_ALIASES.items()}
        # Hand-written corrections outrank the alias table.
        self.brand_by_fa.update({fold(k): v for k, v in BRAND_FA_OVERRIDES.items()})
        # (brand_slug, folded Persian model) -> most common model slug
        self._model_votes: dict[tuple[str, str], Counter] = defaultdict(Counter)
        self.model_by_fa: dict[tuple[str, str], str] = {}

    def learn(self, rows: Iterable[dict | Listing]) -> "BrandResolver":
        """Learn the mapping from listings that already carry both forms."""
        for row in rows:
            data = row if isinstance(row, dict) else row.to_dict()
            brand = (data.get("brand") or "").lower()
            if not brand:
                continue

            brand_fa, model_fa = split_title(data.get("title"))
            brand_fa = brand_fa or data.get("brand_fa")
            if brand_fa:
                self.brand_by_fa.setdefault(fold(brand_fa), brand)

            model = (data.get("model") or "").lower()
            model_fa = data.get("model_fa") or model_fa
            if model and model_fa:
                self._model_votes[(brand, fold(model_fa))][model] += 1

        # A Persian model name can map to several slugs ('سراتو' -> cerato,
        # ceratoir). Pick the most frequent so cohorts stay stable.
        self.model_by_fa = {
            key: votes.most_common(1)[0][0] for key, votes in self._model_votes.items()
        }
        log.info(
            "canonical: %d brand names, %d model names",
            len(self.brand_by_fa), len(self.model_by_fa),
        )
        return self

    def brand_slug(self, brand_fa: str | None) -> str | None:
        if not brand_fa:
            return None
        return self.brand_by_fa.get(fold(brand_fa))

    def model_slug(self, brand: str | None, model_fa: str | None) -> str | None:
        """Resolve a Persian model name, tolerating decorative extra words."""
        if not brand or not model_fa:
            return None

        for key in self._model_candidates(brand, model_fa):
            if (brand, key) in self.model_by_fa:
                return self.model_by_fa[(brand, key)]

            # Divar's breadcrumb model is often a prefix of Bama's fuller name
            # ('206' vs '206 SD'), or vice versa.
            for (b, name), slug in self.model_by_fa.items():
                if b != brand:
                    continue
                if name.startswith(key) or key.startswith(name):
                    return slug
                # Spacing is not vocabulary: Bama writes '315هاچ بک' where
                # Sheypoor writes '315 هاچ بک'.
                if name.replace(" ", "") == key.replace(" ", ""):
                    return slug
        return None

    def _model_candidates(self, brand: str, model_fa: str) -> list[str]:
        """The forms of a Persian model name worth trying, best first.

        Sites disagree about whether the brand belongs in the model name.
        Sheypoor says 'دنا پلاس' and 'پیکان وانت' where Bama says just 'پلاس'
        and 'وانت' — the same car, named twice. Trying the name with a leading
        brand removed recovers those without hand-writing a single mapping.
        """
        key = fold(model_fa)
        candidates = [key]
        for brand_fa, slug in self.brand_by_fa.items():
            if slug != brand or not brand_fa:
                continue
            if key.startswith(brand_fa + " "):
                stripped = key[len(brand_fa):].strip()
                if stripped:
                    candidates.append(stripped)
        return candidates

    def resolve(self, listing: Listing) -> Listing:
        """Fill in `brand`/`model` on a listing that only has Persian names."""
        if not listing.brand:
            listing.brand = self.brand_slug(listing.brand_fa)
        if not listing.model and listing.brand:
            listing.model = self.model_slug(listing.brand, listing.model_fa)
        # Keep the Persian model name populated for every source; search and
        # dedup both rely on it.
        if not listing.model_fa:
            _, model_fa = split_title(listing.title)
            listing.model_fa = model_fa
        return listing


def dedupe_key(listing: Listing | dict) -> tuple | None:
    """Coarse bucket for duplicate candidates: same car, same year, same shape."""
    data = listing if isinstance(listing, dict) else listing.to_dict()
    brand, model, year = data.get("brand"), data.get("model"), data.get("year")
    if not (brand and model and year):
        return None
    return (brand, model, year)


def _close(a: float | None, b: float | None, tolerance: float) -> bool:
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    largest = max(abs(a), abs(b))
    return largest > 0 and abs(a - b) / largest <= tolerance


def find_duplicates(listings: list[Listing]) -> dict[str, list[str]]:
    """Link listings that are plausibly the same physical car on another site.

    Deliberately conservative — a false merge hides a real listing, which is
    worse than showing the same car twice. Requires the same brand/model/year
    bucket, near-identical mileage *and* price, and two different sources. With
    four sources a car can legitimately appear on three of them, so a listing's
    `duplicate_of` is a list, not a single twin.

    Sorting each bucket by mileage keeps this from becoming the slow part of
    ingest. Every extra source makes the buckets denser and the pair count grows
    with the square of that, but a mileage-sorted bucket can stop early: once
    the gap to `left` exceeds the tolerance it only widens for the rows after,
    so there is nothing further to check.
    """
    buckets: dict[tuple, list[Listing]] = defaultdict(list)
    for listing in listings:
        key = dedupe_key(listing)
        # A listing with no mileage can never satisfy `_close`, so it cannot be
        # matched at all — leaving it out keeps the buckets honest.
        if key and listing.mileage_km is not None:
            buckets[key].append(listing)

    links: dict[str, list[str]] = defaultdict(list)
    for group in buckets.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda item: item.mileage_km or 0)
        for i, left in enumerate(group):
            for right in group[i + 1:]:
                if not _close(left.mileage_km, right.mileage_km, MILEAGE_TOLERANCE):
                    break  # sorted: every later row is further away still
                if left.source == right.source:
                    continue
                if not _close(left.price_toman, right.price_toman, PRICE_TOLERANCE):
                    continue
                links[left.code].append(right.code)
                links[right.code].append(left.code)

    if links:
        log.info("canonical: %d listings cross-listed on more than one site", len(links))
    return dict(links)


def apply_duplicates(listings: list[Listing]) -> list[Listing]:
    """Annotate listings with their cross-site twins."""
    links = find_duplicates(listings)
    for listing in listings:
        listing.duplicate_of = links.get(listing.code, [])
    return listings

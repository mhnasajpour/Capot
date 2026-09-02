"""Brand and model vocabulary, derived from the corpus itself.

The previous search hand-maintained ~24 brand names and no models at all, so
«سراتو» and «۲۰۶» matched nothing and the ranker fell back to "best value
overall" — returning the same cars for every unrecognised query.

Every Bama title is `brand_fa، model_fa` (verified across the whole corpus), so
the vocabulary is already in the data: ~83 Persian brand names and ~440 models,
free and self-updating. Nothing here is hand-written except the alias table for
things buyers say that no listing contains.

Matching is deliberately generous about Persian orthography, which varies far
more than English:

  * Persian vs Arabic yeh/kaf  (ی/ي, ک/ك)
  * zero-width non-joiner       (کم‌مصرف vs کم مصرف)
  * Persian/Arabic vs ASCII digits (۲۰۶ vs 206)
  * decorative suffixes in listing titles ((مونتاژ), صندوق دار, نیو)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Iterable

from .config import DATA_DIR
from .normalize import fa_to_en_digits

log = logging.getLogger(__name__)

LEXICON_PATH = DATA_DIR / "lexicon.json"

# Orthographic folding. Applied to both the vocabulary and the query so the two
# always meet in the same normal form.
_CHAR_FOLD = {
    "ي": "ی",  # Arabic yeh  -> Persian yeh
    "ى": "ی",  # alef maksura -> Persian yeh
    "ك": "ک",  # Arabic kaf  -> Persian kaf
    "أ": "ا",  # alef with hamza above -> alef
    "إ": "ا",  # alef with hamza below -> alef
    "آ": "ا",  # alef madda -> alef
    "ة": "ه",  # teh marbuta -> heh
    "‌": " ",       # ZWNJ -> space
    "‏": " ",       # RTL mark
    "‎": " ",       # LTR mark
    "ً": "", "ٌ": "", "ٍ": "",  # tanween
    "َ": "", "ُ": "", "ِ": "",  # short vowels
    "ّ": "", "ْ": "",                # shadda, sukun
}
_PUNCT = re.compile(r"[،؛,;:!?.()\[\]{}«»\"'’‘/\\|_+*—–-]+")
_WS = re.compile(r"\s+")

# Words that decorate a model name in listing titles but carry no identity.
# Stripped when building the "base" form so «سراتو» reaches «سراتو (مونتاژ)».
# NB: 'پلاس' is NOT noise — «دنا پلاس» is a distinct model from «دنا».
_MODEL_NOISE = (
    "مونتاژ", "وارداتی", "نیو", "قدیم", "جدید", "دنده ای", "اتوماتیک",
    "صندوق دار", "هاچ بک", "هاچبک", "کوپه", "استیشن",
)

# Things buyers type that appear in no listing title. Kept deliberately small —
# everything else comes from the data.
BRAND_ALIASES: dict[str, str] = {
    "بی ام و": "bmw", "بی‌ام‌و": "bmw", "ب ام و": "bmw", "بنز": "benz",
    "مرسدس": "benz", "مرسدس بنز": "benz", "فولکس واگن": "volkswagen",
    "هیوندا": "hyundai", "ایران خودرو": "ikco", "سایپا": "saipa",
    "ام وی ام": "mvm", "ام‌وی‌ام": "mvm", "پژو": "peugeot", "رنو": "renault",
    "تویوتا": "toyota", "کیا": "kia", "مزدا": "mazda", "نیسان": "nissan",
    "سوزوکی": "suzuki", "هوندا": "honda", "چری": "chery", "جک": "jac",
    "لیفان": "lifan", "پراید": "pride", "سمند": "samand", "دنا": "dena",
    "تیبا": "tiba", "شاهین": "shahin", "تارا": "tara", "ساینا": "saina",
    "پیکان": "peykan",
    "کوییک": "quick", "رانا": "rana", "آریسان": "arisun", "فونیکس": "fownix",
}

# Model synonyms buyers use that differ from the listing wording.
MODEL_ALIASES: dict[str, str] = {
    "ال ایکس": "lx", "ال‌ایکس": "lx", "سری 5": "5series", "سری 3": "3series",
    "سری 7": "7series", "تندر": "tondar", "تندر 90": "tondar90",
    "ال 90": "tondar90", "ای ال 90": "tondar90", "پلاس": "plus",
    "پژو پارس": "pars", "سورن": "soren",
}


def fold(text: str | None) -> str:
    """Normalize Persian text to a comparable form."""
    if not text:
        return ""
    out = fa_to_en_digits(str(text))
    out = "".join(_CHAR_FOLD.get(ch, ch) for ch in out)
    out = _PUNCT.sub(" ", out)
    out = _WS.sub(" ", out)
    return out.strip().lower()


def _strip_noise(name: str) -> str:
    """Drop decorative words so a base model name still matches."""
    out = name
    for noise in _MODEL_NOISE:
        out = out.replace(fold(noise), " ")
    return _WS.sub(" ", out).strip()


def split_title(title: str | None) -> tuple[str | None, str | None]:
    """`'کیا، سراتو (مونتاژ)'` -> `('کیا', 'سراتو (مونتاژ)')`."""
    if not title or "،" not in title:
        return None, None
    brand, _, model = title.partition("،")
    return brand.strip() or None, model.strip() or None


@dataclass
class Lexicon:
    """Query-time vocabulary: name -> the entities it can refer to."""

    # folded name -> brand slug
    brands: dict[str, str] = field(default_factory=dict)
    # folded name -> list of (brand_slug, model_slug)
    models: dict[str, list[list[str]]] = field(default_factory=dict)
    # brand slug -> Persian display name
    brand_fa: dict[str, str] = field(default_factory=dict)

    @property
    def brand_keys(self) -> list[str]:
        return list(self.brands)

    @property
    def model_keys(self) -> list[str]:
        return list(self.models)

    # Bumped whenever `build` changes what it derives, so a cache written by an
    # older version is discarded instead of silently outliving the code. The
    # comma-in-a-Divar-title bug survived a fix for exactly this reason: the
    # junk model names were already on disk.
    VERSION = 2

    n_rows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.VERSION, "n_rows": self.n_rows,
            "brands": self.brands, "models": self.models, "brand_fa": self.brand_fa,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Lexicon":
        return cls(
            brands=data.get("brands", {}),
            models=data.get("models", {}),
            brand_fa=data.get("brand_fa", {}),
            n_rows=data.get("n_rows", 0),
        )


def build(rows: Iterable[dict]) -> Lexicon:
    """Derive the vocabulary from listing rows."""
    rows = list(rows)
    n_rows = len(rows)
    lex = Lexicon()
    model_pairs: dict[str, set[tuple[str, str]]] = {}

    def add_model(name: str, brand: str, model: str) -> None:
        key = fold(name)
        if len(key) < 2:
            return
        model_pairs.setdefault(key, set()).add((brand, model))

    for row in rows:
        brand = (row.get("brand") or "").lower()
        model = (row.get("model") or "").lower()
        if not brand:
            continue

        # `split_title` encodes Bama's «brand، model» convention. Divar titles
        # are free text and a dozen of them happen to contain a comma, so
        # «تیگو۷پرو ۱۴۰۱ گارانتی فعال بیرنگ،اقساط» registered «اقساط» as a model
        # name — and «ماشین اقساطی» then fuzzy-matched it and answered an
        # instalment query with five Fownix Tiggos. The row's own `brand_fa` is
        # the authority: when the split disagrees with it, the comma was
        # punctuation, not structure.
        split_brand_fa, model_fa = split_title(row.get("title"))
        row_brand_fa = row.get("brand_fa")
        if split_brand_fa and row_brand_fa and fold(split_brand_fa) != fold(row_brand_fa):
            split_brand_fa, model_fa = None, None
        brand_fa = split_brand_fa or row_brand_fa

        if brand_fa:
            lex.brands[fold(brand_fa)] = brand
            lex.brand_fa.setdefault(brand, brand_fa)
        lex.brands[fold(brand)] = brand

        if not model:
            continue
        # The English slug ('cerato', 's5', '206sd') — users type Latin too.
        add_model(model, brand, model)
        if model_fa:
            add_model(model_fa, brand, model)
            base = _strip_noise(fold(model_fa))
            if base and base != fold(model_fa):
                add_model(base, brand, model)
        # 'ceratoir' -> 'cerato': the assembly suffix is not part of the name.
        if model.endswith("ir") and len(model) > 4:
            add_model(model[:-2], brand, model)

    for name, slug in BRAND_ALIASES.items():
        lex.brands.setdefault(fold(name), slug)

    # Model aliases resolve to whatever entities that slug already covers.
    for name, target in MODEL_ALIASES.items():
        key, target_key = fold(name), fold(target)
        if target_key in model_pairs:
            model_pairs.setdefault(key, set()).update(model_pairs[target_key])

    lex.models = {k: sorted([list(p) for p in v]) for k, v in model_pairs.items()}
    lex.n_rows = n_rows
    log.info("lexicon: %d brand names, %d model names from %d rows",
             len(lex.brands), len(lex.models), n_rows)
    return lex


def load(rows: Iterable[dict] | None = None, *, rebuild: bool = False) -> Lexicon:
    """Load the cached lexicon, building it from `rows` when missing or stale."""
    if not rebuild and LEXICON_PATH.exists():
        try:
            data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
            cached = Lexicon.from_dict(data)
            stale = data.get("version") != Lexicon.VERSION
            if rows is not None and not stale:
                stale = cached.n_rows != len(list(rows))
            if not stale:
                return cached
            log.info("lexicon cache is stale; rebuilding")
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("lexicon cache unreadable (%s); rebuilding", exc)

    if rows is None:
        return Lexicon()

    lex = build(rows)
    save(lex)
    return lex


def save(lex: Lexicon) -> None:
    LEXICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEXICON_PATH.write_text(
        json.dumps(lex.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
    )


@dataclass
class EntityMatch:
    """What the query named."""

    brands: set[str] = field(default_factory=set)
    # (brand_slug, model_slug) pairs the query could mean
    models: set[tuple[str, str]] = field(default_factory=set)
    matched_text: list[str] = field(default_factory=list)
    leftover: str = ""
    fuzzy: bool = False

    @property
    def has_entity(self) -> bool:
        return bool(self.brands or self.models)


# Three kinds of non-entity word, kept apart because search treats them
# differently even though none may ever match a brand or model name.

# Budget, spec and filter vocabulary — fully handled by the structured parser in
# query.py, so a query made only of these needs no relevance signal at all.
CONSTRAINT_WORDS = {
    fold(w) for w in (
        "زیر", "بالای", "تا", "از", "بین", "بودجه", "قیمت", "تومان", "تومن",
        "میلیون", "میلیارد", "مدل", "سال", "کارکرد", "کیلومتر", "هزار",
        "حداکثر", "حداقل", "کمتر", "بیشتر", "اتوماتیک", "دنده", "بدون", "رنگ",
        "کم", "مصرف", "سالم", "تمیز", "خوب",
        # Body styles and fuels double as model names for a few marques
        # ('پراید، هاچ بک'), but in a query they always mean the category.
        "هاچبک", "هاچ بک", "سدان", "کراس اور", "کراس", "شاسی بلند", "وانت",
        "استیشن", "بنزینی", "دوگانه سوز", "دوگانه", "هیبریدی", "برقی", "دیزلی",
    )
}

# Filler that carries no search intent either way.
GENERIC_WORDS = {
    fold(w) for w in (
        "ماشین", "خودرو", "می خوام", "میخوام", "میخام", "با", "و", "برای",
        "یه", "یک", "دنبال", "باشه", "هست", "لطفا",
    )
}

# Real intent that appears in no listing text: «دختر دانشجو» is meaningful to a
# buyer and meaningless to a keyword index. These must reach the semantic stage
# and must never be mistaken for nonsense.
LIFESTYLE_WORDS = {
    fold(w) for w in (
        "خانواده", "خانوادگی", "اولین", "دختر", "پسر", "دانشجو", "شهری",
        "جادار", "اقتصادی", "ارزان", "لوکس", "اسپرت", "کار", "مسافرکشی",
        "اسنپ", "دربست", "تاکسی", "سفر", "جاده", "آفرود", "راحت", "بی دردسر",
        "کم استهلاک", "قطعات", "بی خطر", "ایمن",
        # Membership is tested one token at a time, so a multi-word entry above
        # can never match on its own: «بی دردسر» reaches this set only because
        # «دردسر» is listed here too. Everything below is the same case — real
        # buyer intent that no listing field spells out.
        "دردسر", "استهلاک", "کوچک", "بزرگ", "گران", "ارزون", "مطمئن",
        "مقرون", "صرفه", "شروع", "مبتدی", "نوپا", "پرمصرف", "قوی", "قدرتمند",
        "بادوام", "بی خطر", "امن", "زیبا", "خوشگل", "شیک", "معمولی",
    )
}

# Query words that are never entity names — skipped before fuzzy matching so
# «زیر» or «ماشین» can't be typo-corrected into a brand.
_STOPWORDS = CONSTRAINT_WORDS | GENERIC_WORDS | LIFESTYLE_WORDS

# Units that mark the preceding number as an amount, not a model name. Without
# this, «زیر ۵۰۰ میلیون» matches the Fiat 500.
_AMOUNT_UNITS = {fold(u) for u in ("میلیون", "میلیارد", "تومان", "هزار", "تومن")}

MAX_NGRAM = 4
FUZZY_CUTOFF = 0.86


def match(query: str, lex: Lexicon) -> EntityMatch:
    """Find brand/model mentions in a query.

    Longest n-gram wins, so «206 sd» beats «206» and «کیا سراتو» resolves both
    parts. Unmatched tokens are returned as `leftover` for the text and semantic
    stages to use.
    """
    result = EntityMatch()
    tokens = fold(query).split()
    if not tokens:
        return result

    used = [False] * len(tokens)
    # Numbers that are really amounts ('۵۰۰ میلیون') must never be read as model
    # names. Mark them consumed up front.
    amounts = [False] * len(tokens)
    for i, token in enumerate(tokens):
        if token.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in _AMOUNT_UNITS:
            amounts[i] = True

    for size in range(min(MAX_NGRAM, len(tokens)), 0, -1):
        for start in range(len(tokens) - size + 1):
            if any(used[start:start + size]) or any(amounts[start:start + size]):
                continue
            phrase = " ".join(tokens[start:start + size])

            # A bare spec word is not an entity, even when some marque happens to
            # use it as a model name: «اتوماتیک» in a query means the gearbox,
            # not Saina's AT trim. Multi-word phrases are safe.
            if size == 1 and phrase in _STOPWORDS:
                continue

            if phrase in lex.models:
                for brand, model in lex.models[phrase]:
                    result.models.add((brand, model))
                result.matched_text.append(phrase)
                for i in range(start, start + size):
                    used[i] = True
                continue

            if phrase in lex.brands:
                result.brands.add(lex.brands[phrase])
                result.matched_text.append(phrase)
                for i in range(start, start + size):
                    used[i] = True

    leftover_tokens = [t for t, u in zip(tokens, used) if not u]

    # A named brand plus a bare designator: «مزدا ۳» -> mazda/3sedan, 3hatchback…;
    # «ب ام و سری ۵» -> the alias resolves 'سری 5' to '5series', which prefixes
    # bmw/5seriessedan. Only ever scoped to the brands the query actually named,
    # so a loose token like '3' can't drag in every marque's 3-something.
    if result.brands and not result.models and leftover_tokens:
        phrases = list(leftover_tokens)
        for size in (3, 2):
            phrases += [
                " ".join(leftover_tokens[i:i + size])
                for i in range(len(leftover_tokens) - size + 1)
            ]
        for phrase in phrases:
            target = fold(MODEL_ALIASES.get(phrase, phrase))
            if not target or target in _STOPWORDS:
                continue
            hits = {
                (b, m)
                for key, pairs in lex.models.items()
                for b, m in pairs
                if b in result.brands and (m.startswith(target) or key == target)
            }
            if hits:
                result.models |= hits
                result.matched_text.append(phrase)
                for token in phrase.split():
                    if token in leftover_tokens:
                        leftover_tokens.remove(token)
                break

    # Typo tolerance, single tokens only, never on stopwords.
    if not result.has_entity:
        for i, token in enumerate(leftover_tokens):
            # Numbers match exactly or not at all. Fuzzy-matching them turns
            # «زیر ۵۰۰ میلیون» into a Fiat 500.
            if token in _STOPWORDS or len(token) < 3 or token.isdigit():
                continue
            near = get_close_matches(token, lex.model_keys, n=1, cutoff=FUZZY_CUTOFF)
            if near:
                for brand, model in lex.models[near[0]]:
                    result.models.add((brand, model))
                result.fuzzy = True
                result.matched_text.append(near[0])
                leftover_tokens[i] = ""
                break
            near = get_close_matches(token, lex.brand_keys, n=1, cutoff=FUZZY_CUTOFF)
            if near:
                result.brands.add(lex.brands[near[0]])
                result.fuzzy = True
                result.matched_text.append(near[0])
                leftover_tokens[i] = ""
                break

    # A named brand disambiguates an ambiguous model name: «سمند ال ایکس» must
    # resolve to samand/lx, not lexus/lx, even though both are called "LX".
    #
    # The narrowing is unconditional, and that matters when it leaves nothing:
    # «کوییک دنده ای» named Saipa's Quik, and «دنده ای» is *also* the literal
    # model name of a few Saina trims. Keeping those on an empty narrowing
    # answered a Quik query with Sainas. An empty narrowing means the query
    # named a brand and a designator that brand has no model for, so the brand
    # alone is the honest filter — and if we stock none, retrieval says so.
    if result.brands and result.models:
        result.models = {(b, m) for b, m in result.models if b in result.brands}

    # A brand named alongside its own model adds nothing as a separate filter,
    # and keeping it would wrongly widen the result set to the whole brand.
    if result.models:
        model_brands = {b for b, _ in result.models}
        result.brands -= model_brands

    result.leftover = " ".join(t for t in leftover_tokens if t)
    return result

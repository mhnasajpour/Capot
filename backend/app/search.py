"""Hybrid retrieval: decide *which* cars a query is about.

Phase 1 had no retrieval stage at all. `rank()` scored the entire corpus on
value/health/fit, so a query naming a car the ranker didn't understand returned
whatever was cheapest relative to market — the same handful of cars every time.

Retrieval now runs first and three signals decide it, because each fails in a
different way:

  1. **Entity match** (`lexicon.py`) — precise and definitive. «سراتو» means Kia
     Cerato; nothing else may appear. This is a hard filter, not a score.
  2. **TF-IDF over listing text** — catches wording the lexicon has no entry
     for. Character n-grams absorb Persian morphology, word tokens keep the
     query's words apart; both are needed.
  3. **Semantic embeddings** — for vague intent («ماشین برای دختر دانشجو»)
     where no word in the query appears in any listing.

Ranking then orders *within* the retrieved set, so value/health/fit never again
decide relevance.

Two gates stand between a query and a result set, because similarity alone will
always rank *something* first:

  * **Is this a question about a car?** Only words the corpus actually uses —
    attribute names, or vocabulary common across listings — plus known buyer
    intent count. Without this, «یخچال فریزر» and «فراری» were car queries,
    because a search index will always find its best match for anything.
  * **Is this car close enough to the best one?** Candidates must clear a
    fraction of the top score. Retrieval used to pass on its top 400 rows
    regardless, and normalisation then rescaled the best of a bad batch to a
    confident 1.0.

Whatever survives both is what the user asked for; when nothing does, retrieval
says which kind of nothing it is (`nonsense`, `unknown_car`, `constraints`) so
the UI can give a true reason instead of a shrug.

Embeddings are optional by construction: if the model can't be downloaded or
loaded, semantic similarity falls back to LSA (TruncatedSVD over the same
TF-IDF matrix), which needs no download. Phase 1's offline guarantee holds.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from difflib import get_close_matches
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize as l2_normalize

from . import lexicon
from .config import DATA_DIR
from .lexicon import Lexicon

log = logging.getLogger(__name__)

EMBEDDINGS_PATH = DATA_DIR / "embeddings.npy"
EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# The LSA fallback, cached to disk. Fitting it over the whole corpus takes the
# better part of ten seconds, and it used to be fitted lazily inside the first
# query that needed it — so the first vague search of every server run waited
# through the fit before it saw a single car. It is now built once, up front and
# off the request path, and cached so the next start pays nothing.
LSA_PATH = DATA_DIR / "lsa.npz"
LSA_COMPONENTS = 160

# Fusion weights when no entity was matched.
W_TEXT = 0.6
W_SEMANTIC = 0.4

# Lexical relevance blends two views of the same text. Character n-grams absorb
# Persian morphology and typos («اقساطی» finding «اقساط») but they smear a query
# across its words, so «ماشین با سقف شیشه ای» scored on «ماشین» as much as on
# «سقف» and returned cars with no sunroof at 24% precision. Word tokens keep the
# words apart. Weighted toward words, that case reaches 71% precision, while the
# char component still carries the morphology cases.
W_WORD = 0.65

# Retrieval keeps a generous candidate pool; ranking does the fine ordering.
CANDIDATE_POOL = 400

# A description word counts as corpus vocabulary once this share of listings
# uses it. Measured over the live corpus: «سقف» 4.9%, «اقساط» 3.2%, «شیشه» 6.7%
# all clear it; «یخچال» 0.6%, «گوشی» 0.05%, «دوچرخه» 0.01% do not.
MIN_DF_RATIO = 0.01

# How many listings must share an identity word before it counts as a car
# attribute rather than one seller's turn of phrase.
MIN_IDENTITY_DF = 3

# How far below the best candidate a listing may score and still be shown.
# Without a floor, retrieval handed ranking the top 400 rows whatever their
# score, and `_unit` rescaled the best of a bad batch to 1.0 — which is how a
# search for «فراری» answered with a Maserati, a 207 and a Zotye Ario.
#
# Two floors, because the two signals mean different things. Lexical overlap is
# specific: if some listing shares the query's words, one sharing far fewer is
# not the same car, so the floor is high. Semantic similarity is diffuse —
# every car is a car — so its floor only trims the tail.
TEXT_FLOOR = 0.40
SEMANTIC_FLOOR = 0.55


def identity_text(row: dict) -> str:
    """The fields that say what this car *is* — every word here is an attribute
    some listing genuinely has, so this is the vocabulary a query is checked
    against. `body_color` is in the list because «ماشین قرمز» is a real search
    and colour lives in no other indexed field."""
    parts = [
        row.get("title"), row.get("brand_fa"), row.get("trim"),
        row.get("body_type_fa"), row.get("transmission"), row.get("fuel"),
        row.get("body_status"), row.get("body_color"), row.get("city"),
    ]
    return lexicon.fold(" ".join(p for p in parts if p))


def doc_text(row: dict) -> str:
    """The searchable text of one listing: what it is, plus what the seller
    wrote. Free text is worth indexing but is *not* evidence about the corpus's
    vocabulary — see `SearchIndex.word_df`."""
    body = lexicon.fold((row.get("description") or "")[:300])
    return f"{identity_text(row)} {body}".strip()


@dataclass
class Retrieval:
    """What retrieval decided, and why — surfaced so the API can explain it."""

    codes: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    mode: str = "none"          # entity | text | semantic | none | nonsense
    entity: lexicon.EntityMatch | None = None
    matched_models: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "matched": self.entity.matched_text if self.entity else [],
            "models": self.matched_models,
            "fuzzy": bool(self.entity.fuzzy) if self.entity else False,
            "n_candidates": len(self.codes),
        }


class SearchIndex:
    """TF-IDF (+ optional embedding) index over the corpus."""

    def __init__(self, corpus: list[dict], lex: Lexicon | None = None) -> None:
        self.corpus = corpus
        self.codes = [r["code"] for r in corpus]
        self.by_code = {r["code"]: r for r in corpus}
        self.lexicon = lex or lexicon.load(corpus)

        self._docs = [doc_text(r) for r in corpus]
        # char_wb n-grams handle Persian morphology and typos far better than
        # word tokens, and need no stemmer.
        self.vectorizer = TfidfVectorizer(
            analyzer="char_wb", ngram_range=(3, 5), min_df=2, max_features=200_000,
            sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform(self._docs)

        # Whitespace tokens, not sklearn's default pattern: the text is already
        # folded, and the default drops single-character tokens that matter here
        # («بی رنگ»). Bigrams let a two-word attribute («سقف شیشه») beat two
        # unrelated listings that each mention one of the words.
        self.word_vectorizer = TfidfVectorizer(
            analyzer="word", token_pattern=r"\S+", ngram_range=(1, 2), min_df=2,
            sublinear_tf=True,
        )
        self.word_matrix = self.word_vectorizer.fit_transform(self._docs)
        log.info("tf-idf index: %s docs, %s char features, %s word features",
                 self.matrix.shape[0], self.matrix.shape[1], self.word_matrix.shape[1])

        # Two vocabularies, because "this word occurs somewhere" turned out to
        # be almost no evidence at all. Free-text descriptions mention fridges,
        # motorbikes, houses and Ferraris (in part-exchange offers), so a single
        # combined vocabulary accepted «یخچال فریزر» and «فراری» as car queries
        # and answered them with whatever the ranker liked.
        #
        #   word_vocab — words from identity fields only. Every entry is an
        #     attribute a car in the corpus actually has.
        #   word_df    — document frequency over the full text. A description
        #     word is evidence only when it is *common* («سقف»: 531 listings,
        #     «دوچرخه»: 1).
        identity_df: Counter[str] = Counter()
        for row in corpus:
            identity_df.update({t for t in identity_text(row).split() if len(t) > 1})
        # Divar titles are seller-written free text, so a handful of them put
        # «دختر» or «شهری» into what is otherwise a field of car attributes.
        # Three listings is enough to tell an attribute from one person's prose,
        # and low enough to keep rare-but-real colours («نارنجی», 8 listings).
        self.word_vocab = {t for t, n in identity_df.items() if n >= MIN_IDENTITY_DF}

        self.word_df: Counter[str] = Counter()
        for doc in self._docs:
            self.word_df.update({t for t in doc.split() if len(t) > 1})
        # 1% of the corpus: high enough to exclude one-off mentions, low enough
        # to keep genuine but uncommon features («پانوراما», «هیبرید»).
        self.min_df = max(3, round(MIN_DF_RATIO * len(corpus)))

        self.embeddings: np.ndarray | None = None
        self._embedder: Any = None
        # The LSA fallback is held as plain arrays rather than a fitted
        # estimator, because for LSA `TruncatedSVD.transform` is exactly
        # `X @ components_.T` — no centring, nothing else to reconstruct. Two
        # arrays cache to disk cleanly; a pickled estimator would not survive a
        # scikit-learn upgrade.
        self._lsa_components: np.ndarray | None = None
        self._lsa_docs: np.ndarray | None = None
        self._lsa_lock = threading.Lock()

    # ---------------------------------------------------------------- semantic

    def load_embeddings(self, build: bool = False, allow_build: bool = True) -> bool:
        """Load (or build) sentence embeddings. Returns True if available.

        `allow_build=False` means "use the cache or do without" — the right
        setting at server start-up, where encoding the whole corpus would add
        minutes to boot time. Building is an explicit offline step.
        """
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            log.info("sentence-transformers not installed; semantic search uses LSA fallback")
            return False

        if EMBEDDINGS_PATH.exists() and not build:
            try:
                cached = np.load(EMBEDDINGS_PATH)
                if cached.shape[0] == len(self.corpus):
                    self.embeddings = cached
                    self._embedder = SentenceTransformer(EMBEDDING_MODEL)
                    log.info("loaded %d cached embeddings", cached.shape[0])
                    return True
                log.warning("embedding cache is stale (%d vs %d rows); rebuilding",
                            cached.shape[0], len(self.corpus))
            except (OSError, ValueError) as exc:
                log.warning("embedding cache unreadable (%s); rebuilding", exc)

        if not allow_build:
            log.info("no embedding cache; semantic search uses the LSA fallback")
            return False

        try:
            self._embedder = SentenceTransformer(EMBEDDING_MODEL)
            log.info("encoding %d listings (one-off)…", len(self._docs))
            vectors = self._embedder.encode(
                self._docs, batch_size=64, show_progress_bar=False,
                convert_to_numpy=True, normalize_embeddings=True,
            )
            EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            np.save(EMBEDDINGS_PATH, vectors)
            self.embeddings = vectors
            return True
        except Exception as exc:  # noqa: BLE001 - download/OOM/etc all fall back
            log.warning("embedding model unavailable (%s); using LSA fallback", exc)
            self._embedder = None
            return False

    def prepare_semantic(self, allow_build: bool = True) -> str:
        """Make the semantic signal usable *before* the first query arrives.

        Retrieval never fits anything itself (see `_semantic_scores`), so
        whichever signal this leaves behind is the one every search gets. Call
        it at start-up — off the request path, since a fit takes seconds.

        Returns the signal that ended up available: "embeddings", "lsa" or
        "none".
        """
        if self.load_embeddings(allow_build=False):
            return "embeddings"
        try:
            self._ensure_lsa(build=allow_build, cache=True)
        except Exception as exc:  # noqa: BLE001 - a missing signal is not fatal
            log.warning("LSA unavailable (%s); relevance is lexical only", exc)
        return "lsa" if self._lsa_docs is not None else "none"

    @property
    def semantic_ready(self) -> bool:
        return self.embeddings is not None or self._lsa_docs is not None

    def _ensure_lsa(self, build: bool = True, cache: bool = False) -> None:
        """LSA fallback: dense semantic space from the TF-IDF matrix itself.

        Cheaper and weaker than a sentence model, but it needs no download, so
        the semantic path never simply disappears on a blocked network.

        Fitting it costs the better part of ten seconds over the live corpus, so
        the result is cached to disk under a fingerprint of the very matrix it
        was fitted on: re-ingest the corpus and the cache is refitted, leave it
        alone and start-up pays a file read.

        Only `prepare_semantic` writes that cache (`cache=True`). Reading it is
        always safe — the fingerprint sees to that — but writing is a start-up
        concern, and an index built over a handful of fabricated rows in a test
        has no business leaving a file in the data directory.
        """
        if self._lsa_docs is not None:
            return
        with self._lsa_lock:
            if self._lsa_docs is not None:
                return
            fingerprint = self._lsa_fingerprint()
            if self._load_lsa(fingerprint) or not build:
                return

            components = min(LSA_COMPONENTS, self.matrix.shape[1] - 1, self.matrix.shape[0] - 1)
            started = time.perf_counter()
            svd = TruncatedSVD(n_components=components, random_state=42)
            docs = l2_normalize(svd.fit_transform(self.matrix))
            # float32 halves both the file and the resident arrays; the scores
            # decide a ranking, not an accounting entry.
            self._lsa_components = svd.components_.astype(np.float32)
            # Published last, and read first everywhere else: a reader that sees
            # the docs matrix is guaranteed to see the components too.
            self._lsa_docs = docs.astype(np.float32)
            log.info("LSA fitted (%d components) in %.1fs", components,
                     time.perf_counter() - started)
            if cache:
                self._save_lsa(fingerprint)

    def _lsa_fingerprint(self) -> str:
        """Identifies the matrix the cached LSA was fitted on.

        The sparsity pattern covers both halves of what could go stale: which
        listings are in the corpus (`indptr`) and what the vectoriser's
        vocabulary turned them into (`indices`).
        """
        digest = hashlib.blake2b(digest_size=16)
        digest.update(f"{self.matrix.shape}|{LSA_COMPONENTS}".encode())
        digest.update(self.matrix.indptr.tobytes())
        digest.update(self.matrix.indices.tobytes())
        return digest.hexdigest()

    def _load_lsa(self, fingerprint: str) -> bool:
        if not LSA_PATH.exists():
            return False
        try:
            with np.load(LSA_PATH) as cache:
                if str(cache["fingerprint"]) != fingerprint:
                    log.info("LSA cache is stale; refitting")
                    return False
                components, docs = cache["components"], cache["docs"]
        except (OSError, ValueError, KeyError) as exc:
            log.warning("LSA cache unreadable (%s); refitting", exc)
            return False

        self._lsa_components = components
        self._lsa_docs = docs
        log.info("loaded cached LSA (%d components over %d docs)", docs.shape[1], docs.shape[0])
        return True

    def _save_lsa(self, fingerprint: str) -> None:
        try:
            LSA_PATH.parent.mkdir(parents=True, exist_ok=True)
            np.savez(
                LSA_PATH,
                fingerprint=np.array(fingerprint),
                components=self._lsa_components,
                docs=self._lsa_docs,
            )
        except OSError as exc:  # a read-only data dir costs a refit, nothing more
            log.warning("could not cache LSA (%s); it will be refitted next start", exc)

    def _semantic_scores(self, query: str, *, build: bool = True) -> np.ndarray | None:
        """Semantic similarity of every listing to the query, or None.

        `build=False` means "use the semantic space if it is ready, otherwise do
        without" — what `retrieve` asks for, because fitting LSA takes seconds
        and no single search should ever be the one that pays for it. Retrieval
        already degrades to lexical relevance when this returns None.
        """
        if self.embeddings is not None and self._embedder is not None:
            vector = self._embedder.encode(
                [lexicon.fold(query)], convert_to_numpy=True, normalize_embeddings=True
            )
            return self.embeddings @ vector[0]

        docs, components = self._lsa_docs, self._lsa_components
        if docs is None:
            if not build:
                return None
            try:
                self._ensure_lsa()
            except Exception as exc:  # noqa: BLE001
                log.warning("LSA fallback failed (%s); text-only relevance", exc)
                return None
            docs, components = self._lsa_docs, self._lsa_components
            if docs is None or components is None:
                return None

        # `TruncatedSVD.transform` for LSA, written out: project the query into
        # the same space and read off cosine similarity.
        projected = self.vectorizer.transform([lexicon.fold(query)]) @ components.T
        return docs @ l2_normalize(np.asarray(projected))[0]

    # --------------------------------------------------------------- retrieval

    def _text_scores(self, query: str) -> np.ndarray:
        """Lexical relevance: character n-grams and word tokens, blended.

        Each is unit-scaled first so the blend is a weighting of two rankings,
        not of two incomparable similarity scales.
        """
        folded = lexicon.fold(query)
        char_vector = self.vectorizer.transform([folded])
        char = (self.matrix @ char_vector.T).toarray().ravel()
        word_vector = self.word_vectorizer.transform([folded])
        word = (self.word_matrix @ word_vector.T).toarray().ravel()
        return (1 - W_WORD) * _unit(char) + W_WORD * _unit(word)

    def retrieve(self, query: str, *, has_constraints: bool = False,
                 pool: int = CANDIDATE_POOL) -> Retrieval:
        """Pick the candidate set for a query."""
        query = (query or "").strip()
        if not query:
            return Retrieval(codes=list(self.codes), mode="none")

        entity = lexicon.match(query, self.lexicon)

        # 1. Entity match wins outright — it is an identity claim, not a hint.
        if entity.has_entity:
            wanted_models = {(b, m) for b, m in entity.models}
            wanted_brands = set(entity.brands)
            codes = [
                r["code"] for r in self.corpus
                if ((r.get("brand") or "").lower(), (r.get("model") or "").lower()) in wanted_models
                or (wanted_brands and (r.get("brand") or "").lower() in wanted_brands)
            ]
            if codes:
                return Retrieval(
                    codes=codes,
                    scores=self._entity_scores(codes, entity.leftover),
                    mode="entity",
                    entity=entity,
                    matched_models=sorted(f"{b}/{m}" for b, m in wanted_models),
                )
            # Named a real car that isn't in the corpus: say so, don't substitute.
            return Retrieval(codes=[], mode="unknown_car", entity=entity)

        tokens = [t for t in lexicon.fold(query).split() if t]
        # Words that could carry relevance: anything that isn't budget/spec
        # vocabulary or filler.
        content = [
            t for t in tokens
            if t not in lexicon.CONSTRAINT_WORDS and t not in lexicon.GENERIC_WORDS
            and not t.isdigit()
        ]

        # 2. Pure constraint query ("زیر ۵۰۰ میلیون", "بین ۱ تا ۲ میلیارد") — no
        #    relevance signal to apply; the structured filters do all the work.
        if not content:
            return Retrieval(codes=list(self.codes), mode="none", entity=entity)

        # 3. Does anything in the query refer to a car at all? A word counts
        #    when it names an attribute some listing has, when it is known
        #    buyer-intent vocabulary, or when listings commonly use it in free
        #    text. Anything else — «دوچرخه», «یخچال فریزر», «زیبیبیبیب» — is a
        #    question about something we do not sell, and the honest answer is
        #    nothing, not the globally cheapest cars.
        grounded = [t for t in content if self._is_attribute(t)]
        supported = grounded or [t for t in content if t in lexicon.LIFESTYLE_WORDS]

        if not supported:
            if has_constraints:
                # The words meant nothing to us but the budget/spec filters did.
                # Answer those and let the UI say the wording was ignored,
                # rather than ordering the corpus by a meaningless similarity.
                return Retrieval(codes=list(self.codes), mode="constraints", entity=entity)
            return Retrieval(codes=[], mode="nonsense", entity=entity)

        text = self._text_scores(query)
        semantic = self._semantic_scores(query, build=False)

        # `grounded` decides which signal is the authority. When the query uses
        # words the corpus actually contains, lexical overlap says which cars
        # are meant and semantics may only reorder them. With nothing but
        # lifestyle wording («ماشین برای دختر دانشجو») there is no lexical
        # signal to trust, so semantics decides membership too.
        if grounded:
            keep = _above_floor(text, TEXT_FLOOR)
            mode = "text"
        elif semantic is not None:
            keep = _above_floor(semantic, SEMANTIC_FLOOR)
            mode = "semantic"
        else:
            keep = _above_floor(text, TEXT_FLOOR)
            mode = "text"

        if semantic is not None:
            fused = W_TEXT * _unit(text) + W_SEMANTIC * _unit(semantic)
        else:
            fused = _unit(text)

        # Recognised intent that neither text nor semantics can discriminate on
        # (a small corpus, or purely lifestyle wording). We have no relevance
        # signal, so hand the whole corpus to ranking rather than showing an
        # empty page — "no signal" is not the same as "no such car".
        if not keep.any() or float(fused.max()) <= 0:
            return Retrieval(codes=list(self.codes), mode="none", entity=entity)

        scores = np.where(keep, fused, 0.0)
        top = np.argsort(-scores)[:pool]
        codes = [self.codes[i] for i in top if scores[i] > 0]
        return Retrieval(
            codes=codes,
            scores={self.codes[i]: float(scores[i]) for i in top if scores[i] > 0},
            mode=mode,
            entity=entity,
        )

    def _entity_scores(self, codes: list[str], leftover: str) -> dict[str, float]:
        """Relevance inside an entity match.

        The entity is a hard filter, so every one of these cars is the car the
        query named and all of them stay. What the entity match cannot express
        is the rest of the query: «سراتوی سفید» matched on «سراتو» and dropped
        «سفید» on the floor, so a black Cerato ranked as well as a white one.
        Intent carries no colour field, so ranking cannot recover it either —
        this is the only stage that still has the words.

        How much room the leftover gets depends on what it is. «مشکی» is a
        corpus attribute and a buyer who types it means it, so it reorders
        freely (0.5 → 1.0). Anything we cannot place only nudges (0.8 → 1.0):
        ranking must stay in charge of an entity result, since price and
        condition matter more than a word the buyer used in passing.
        """
        leftover = (leftover or "").strip()
        if not leftover:
            return {c: 1.0 for c in codes}

        words = [w for w in leftover.split() if w]
        grounded = words and all(self._is_attribute(w) for w in words)
        base = 0.5 if grounded else 0.8

        scores = self._text_scores(leftover)
        by_code = {self.codes[i]: float(scores[i]) for i in range(len(self.codes))}
        wanted = {c: by_code.get(c, 0.0) for c in codes}
        top = max(wanted.values(), default=0.0)
        if top <= 0:
            return {c: 1.0 for c in codes}
        return {c: base + (1 - base) * (v / top) for c, v in wanted.items()}

    def _is_attribute(self, token: str) -> bool:
        """Is this word something a car in the corpus actually is or has?"""
        if token in self.word_vocab:
            return True
        if self.word_df.get(token, 0) >= self.min_df:
            return True
        # Typo tolerance, against attribute names only. Brand and model typos
        # are lexicon.match's job; a loose cutoff here used to turn any word at
        # all into "recognised" via the description vocabulary. Short words are
        # excluded outright — at four characters «گران» is an 0.88 match for the
        # city «گرگان», and treating that as a colour-or-city query is worse
        # than treating «گران» as the plain intent word it is.
        if len(token) < 5:
            return False
        return bool(get_close_matches(token, self.word_vocab, n=1, cutoff=0.88))


def _unit(scores: np.ndarray) -> np.ndarray:
    """Scale to 0..1 so text and semantic scores are comparable."""
    if scores.size == 0:
        return scores
    top = float(scores.max())
    return scores / top if top > 0 else scores


def _above_floor(scores: np.ndarray, floor: float) -> np.ndarray:
    """Which listings score close enough to the best one to belong in the set.

    The floor is relative because absolute similarity is not comparable across
    queries — a one-word query and a nine-word one score on different scales.
    What is comparable is the gap to the best match.
    """
    if scores.size == 0:
        return np.zeros(0, dtype=bool)
    top = float(scores.max())
    if top <= 0:
        return np.zeros(scores.shape, dtype=bool)
    return scores >= floor * top

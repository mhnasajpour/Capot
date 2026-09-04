"""Runtime configuration.

The LLM is reached through an OpenAI-compatible endpoint so the same code works
against an Iranian proxy (AvalAI / Metis / Liara / GapGPT), a local Ollama, or
OpenAI itself — only LLM_BASE_URL changes.

Copy .env.example to .env and fill in your key. With no key the app still runs:
every AI path has a deterministic fallback (see llm.py).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"

# Every on-disk artefact, named once. These used to be recomputed from
# `__file__` in db.py, pricing.py, ingest.py and crawl/run.py — four copies of
# the same `parents[1] / "data"`, and two independent spellings of where a raw
# crawl file lives, so the crawler wrote one path and the ingester read another
# it had derived for itself.
DB_PATH = DATA_DIR / "cars.db"
LEXICON_PATH = DATA_DIR / "lexicon.json"
MODEL_PATH = DATA_DIR / "price_model.pkl"
#: The model's held-out error, written beside it on every retrain. Until it
#: existed the metrics were logged and then lost, so nothing downstream could
#: quote what the model actually measures — which is exactly what an estimate
#: needs in order to publish an honest range around itself. See
#: `appraise.price_band`.
METRICS_PATH = DATA_DIR / "price_model_metrics.json"
EMBEDDINGS_PATH = DATA_DIR / "embeddings.npy"
LSA_PATH = DATA_DIR / "lsa.npz"
BAMA_DETAIL_PATH = DATA_DIR / "bama_details.jsonl"


def raw_path(source: str) -> Path:
    """Where one source's untouched crawl output lives.

    The crawler writes it and the ingester reads it, so it is defined here
    rather than in either of them.
    """
    return DATA_DIR / f"{source}_raw.jsonl"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    llm_base_url: str = "https://api.avalai.ir/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 30.0

    # When false, the app uses only the on-disk cache and never calls out. This
    # is the mode the demo is recorded in.
    llm_live: bool = True

    data_dir: Path = DATA_DIR
    cache_dir: Path = DATA_DIR / "llm_cache"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key) and self.llm_live


settings = Settings()

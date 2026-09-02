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

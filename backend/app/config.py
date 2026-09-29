"""Deployment settings, read from environment variables.

Keys belong to the deployment, not to individual reviewers: everyone using one
deployment shares one Hindsight memory bank, which is the point of team memory.
Nothing secret is committed; each deployment supplies its own values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    groq_model: str
    hindsight_base_url: str
    hindsight_api_key: str
    hindsight_bank_id: str
    cors_origins: list[str]
    public_demo: bool = False

    @property
    def missing(self) -> list[str]:
        out = []
        if not self.groq_api_key:
            out.append("GROQ_API_KEY")
        if not self.hindsight_api_key and "vectorize.io" in self.hindsight_base_url:
            out.append("HINDSIGHT_API_KEY")
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
        hindsight_base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io").strip(),
        hindsight_api_key=os.getenv("HINDSIGHT_API_KEY", "").strip(),
        hindsight_bank_id=os.getenv("HINDSIGHT_BANK_ID", "precedent-ap").strip(),
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        public_demo=os.getenv("PUBLIC_DEMO", "").strip().lower() in ("1", "true", "yes"),
    )

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_base: str
    asr_model: str
    llm_model: str


def get_settings() -> Settings:
    return Settings(
        api_key=os.environ.get("MODEL_API_KEY", ""),
        api_base=os.environ.get("MODEL_API_BASE", "https://api.meta.ai/v1").rstrip("/"),
        asr_model=os.environ.get("ASR_MODEL", "muse-voice-transcribe-1.0"),
        llm_model=os.environ.get("LLM_MODEL", "muse-spark-1.3"),
    )

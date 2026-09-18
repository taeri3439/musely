"""환경 변수 로딩.

`.env`는 커밋하지 않고 `.env.example`만 커밋한다. cwd와 무관하게 같은 파일을
읽도록 ai-core 디렉터리 기준 절대 경로를 쓴다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"

    # job 상한 — 없으면 LLM이 먹통일 때 job이 영원히 RUNNING으로 남는다.
    job_timeout_seconds: float = 30.0
    job_ttl_minutes: int = 30

    # 아래는 2주차부터 쓴다. mock 서버는 읽지 않는다.
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

    # 임베딩. Anthropic은 임베딩 API가 없어서 선택지에 없다.
    embedding_provider: Literal["openai", "gemini"] = "gemini"
    embedding_model: str = "gemini-embedding-001"

    vector_store: Literal["chroma", "qdrant"] = "chroma"
    chroma_path: str = "./chroma"
    qdrant_url: str = "http://localhost:6333"

    llm_provider: Literal["anthropic"] = "anthropic"
    llm_model: str = "claude-haiku-4-5-20251001"

    

    def require_openai_key(self) -> str:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY가 비어 있다. ai-core/.env를 확인할 것.")
        return self.openai_api_key

    def require_gemini_key(self) -> str:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY가 비어 있다. ai-core/.env를 확인할 것.")
        return self.gemini_api_key

    def require_anthropic_key(self) -> str:
        if not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY가 비어 있다. ai-core/.env를 확인할 것.")
        return self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()

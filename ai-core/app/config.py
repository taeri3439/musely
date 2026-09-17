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
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    vector_store: Literal["chroma", "qdrant"] = "chroma"
    chroma_path: str = "./chroma"
    qdrant_url: str = "http://localhost:6333"

    def require_openai_key(self) -> str:
        """LLM을 호출하는 지점에서만 부른다. 키가 없어도 mock은 떠야 하기 때문."""
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY가 비어 있다. ai-core/.env를 확인할 것.")
        return self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()

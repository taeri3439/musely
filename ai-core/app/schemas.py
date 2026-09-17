"""musely ai-core 계약 스키마 — 백엔드(백엔드)와의 약속.

이 파일의 필드를 바꾸면 Spring Boot DTO도 같이 바뀐다. 임의로 고치지 말고
변경 전에 반드시 공유할 것.

와이어 포맷은 camelCase(Jackson 기본값)로 통일하고, 파이썬 내부는 snake_case를
쓴다. `CamelModel`이 그 변환을 담당한다. FastAPI는 응답을 직렬화할 때
by_alias=True를 기본으로 쓰므로 응답도 자동으로 camelCase가 된다.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


Track = Literal["cosmetic", "fragrance", "both"]


# --------------------------------------------------------------------------
# 요청
# --------------------------------------------------------------------------


class OrchestrateRequest(CamelModel):
    """POST /jobs 본문. 기획서 화면 1의 입력 항목과 1:1로 대응한다."""

    profile_id: str
    track: Track

    skin_type: str | None = None
    category: str | None = None  # "토너" 같은 카테고리 힌트. 완화 체인 1단계에서 풀린다
    concerns: list[str] = []
    avoid_ingredients: list[str] = []
    current_actives: list[str] = []

    preferred_scent_families: list[str] = []
    occasion: str | None = None


# --------------------------------------------------------------------------
# 결과
# --------------------------------------------------------------------------


class FragranceNotes(CamelModel):
    """향수 카드의 노트 피라미드(기획서 화면 3). 화장품 후보는 채우지 않는다."""

    family: str | None = None
    top: list[str] = []
    heart: list[str] = []
    base: list[str] = []


class Candidate(CamelModel):
    item_id: str
    name: str
    brand: str
    score: float  # 0~100. 화면 3의 막대 게이지에 그대로 쓴다
    note: str  # 왜 뽑혔는지 한 줄 = 화면 3의 "추천 이유". 절대 비우지 말 것

    category: str | None = None  # 화장품 카드 부제("브랜드 · 토너"). 향수는 null
    notes: FragranceNotes | None = None  # 향수만 채움


class Caution(CamelModel):
    pair: list[str]  # 규칙 키. 예: ["retinol", "aha"]
    pair_labels: list[str]  # 화면 표기용. 예: ["레티놀", "AHA/BHA"]
    severity: Literal["caution", "avoid"]
    message: str
    source: str
    confidence: Literal["low", "medium", "high"]


class OrchestrateResult(CamelModel):
    summary: str
    cosmetic: list[Candidate] = []
    fragrance: list[Candidate] = []
    cautions: list[Caution] = []

    relaxation_level: int = 0  # 0=원조건 1=일부완화 2=대폭완화. both면 두 트랙 중 최대값
    blocked_by: list[str] = []  # 0건일 때 어떤 조건이 걸렸는지(기획서 화면 3)


# --------------------------------------------------------------------------
# job
# --------------------------------------------------------------------------


class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class StepKey(str, Enum):
    PROFILE = "profile"
    SEARCH = "search"
    CONFLICT = "conflict"
    COMMENTARY = "commentary"


STEP_LABELS: dict[StepKey, str] = {
    StepKey.PROFILE: "프로필 분석",
    StepKey.SEARCH: "조건에 맞는 제품 찾기",
    StepKey.CONFLICT: "성분 조합 검수",
    StepKey.COMMENTARY: "추천 이유 작성",
}


class Step(CamelModel):
    """기획서 화면 2의 단계 표시용. RUNNING 중에도 채워진다."""

    key: StepKey
    label: str  # 사용자 언어. 내부 노드 이름을 그대로 노출하지 않는다
    status: Literal["pending", "running", "done", "skipped"]
    elapsed_ms: int | None = None


class ErrorCode(str, Enum):
    TIMEOUT = "TIMEOUT"
    LLM_ERROR = "LLM_ERROR"
    INTERNAL = "INTERNAL"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ErrorDetail(CamelModel):
    code: ErrorCode
    message: str


class JobAcceptedResponse(CamelModel):
    """POST /jobs 202 응답."""

    job_id: str
    status: JobStatus


class JobStatusResponse(CamelModel):
    """GET /jobs/{jobId} 응답 — 프론트가 1초마다 폴링하는 대상.

    steps가 result 밖에 있는 이유: 단계 표시는 RUNNING 중에 필요한데
    result는 DONE에서야 채워진다.
    """

    job_id: str
    status: JobStatus
    steps: list[Step] = []
    result: OrchestrateResult | None = None
    error: ErrorDetail | None = None
    elapsed_ms: int


class HealthResponse(CamelModel):
    status: Literal["ok", "degraded"]
    indexed_counts: dict[str, int] = Field(default_factory=dict)

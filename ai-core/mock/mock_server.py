"""musely ai-core mock 서버 — 성미가 폴링/로딩/에러 UI를 먼저 만들 수 있게 하는 용도.

실제 추천 로직(벡터 검색·LLM)은 없고 지연과 단계 진행만 시뮬레이션한다. 응답은
app.schemas의 실제 계약 모델로 검증해서 내보내므로 mock과 계약이 어긋날 수 없다.

실행:
    uvicorn mock.mock_server:app --port 8000 --workers 1 --reload
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import AliasChoices, ConfigDict, Field

from app.schemas import (
    STEP_LABELS,
    ErrorCode,
    ErrorDetail,
    HealthResponse,
    JobAcceptedResponse,
    JobStatus,
    JobStatusResponse,
    OrchestrateRequest,
    OrchestrateResult,
    Step,
    StepKey,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"
DEFAULT_DELAY = 5.0
PENDING_WINDOW = 0.4  # 접수 직후 PENDING을 잠깐 노출해서 프론트가 이 상태도 다루게 한다

# 트랙별 단계 구성과 가중치. 가중치는 ai-core 플랜 12절 레이턴시 표를 따라
# 설명 생성(LLM)이 가장 오래 걸리게 잡았다.
STEP_WEIGHTS: dict[StepKey, float] = {
    StepKey.PROFILE: 0.10,
    StepKey.SEARCH: 0.35,
    StepKey.CONFLICT: 0.15,
    StepKey.COMMENTARY: 0.40,
}

# 향수 트랙에는 성분 충돌 검수 노드가 없다(플랜 06 그래프: scent_matcher -> commentary).
TRACK_STEPS: dict[str, list[StepKey]] = {
    "cosmetic": [StepKey.PROFILE, StepKey.SEARCH, StepKey.CONFLICT, StepKey.COMMENTARY],
    "fragrance": [StepKey.PROFILE, StepKey.SEARCH, StepKey.COMMENTARY],
    "both": [StepKey.PROFILE, StepKey.SEARCH, StepKey.CONFLICT, StepKey.COMMENTARY],
}

DEFAULT_FIXTURE: dict[str, str] = {
    "cosmetic": "cosmetic_only",
    "fragrance": "fragrance_only",
    "both": "both",
}

MOCK_FAIL_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.TIMEOUT: "30초 내 완료되지 않았습니다",
    ErrorCode.LLM_ERROR: "설명 생성에 실패했습니다",
    ErrorCode.INTERNAL: "내부 오류가 발생했습니다",
    ErrorCode.JOB_NOT_FOUND: "job을 찾을 수 없습니다",
    ErrorCode.VALIDATION_ERROR: "요청 형식이 올바르지 않습니다",
}


class MockOrchestrateRequest(OrchestrateRequest):
    """실제 계약 + mock 제어 필드. 밑줄로 시작하는 필드는 실제 서버에는 없다."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    mock_delay: float = Field(
        default=DEFAULT_DELAY,
        validation_alias=AliasChoices("_mockDelay", "_mock_delay", "mockDelay"),
    )
    mock_fail: ErrorCode | None = Field(
        default=None,
        validation_alias=AliasChoices("_mockFail", "_mock_fail", "mockFail"),
    )
    mock_fixture: str | None = Field(
        default=None,
        validation_alias=AliasChoices("_mockFixture", "_mock_fixture", "mockFixture"),
    )


@dataclass
class MockJob:
    id: str
    track: str
    fixture: str
    delay: float
    fail: ErrorCode | None
    started_at: float


JOBS: dict[str, MockJob] = {}

app = FastAPI(
    title="musely ai-core (mock)",
    description="1주차 계약 확인용 mock. 실제 추천 로직은 없다.",
    version="0.1.0",
)


def load_fixture(name: str) -> OrchestrateResult:
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in FIXTURE_DIR.glob("*.json"))
        raise HTTPException(
            400,
            detail={
                "code": ErrorCode.VALIDATION_ERROR.value,
                "message": f"fixture '{name}' 없음. 사용 가능: {available}",
            },
        )
    # 실제 계약 모델로 검증한다. fixture가 스키마에서 벗어나면 여기서 터진다.
    return OrchestrateResult.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_steps(job: MockJob, elapsed: float, *, finished: bool) -> list[Step]:
    """경과 시간 비율로 단계 진행 상태를 만든다."""
    keys = TRACK_STEPS[job.track]
    total_weight = sum(STEP_WEIGHTS[k] for k in keys)
    ratio = 1.0 if finished else min(elapsed / job.delay, 0.999)

    # 후보 0건이면 설명 생성을 건너뛴다(플랜 07: 없는 제품을 지어내지 않기 위해).
    skipped = {StepKey.COMMENTARY} if job.fixture == "no_candidates" else set()

    steps: list[Step] = []
    consumed = 0.0
    for key in keys:
        share = STEP_WEIGHTS[key] / total_weight
        start, end = consumed, consumed + share
        consumed = end

        if key in skipped:
            status = "skipped" if ratio >= start else "pending"
        elif ratio >= end:
            status = "done"
        elif ratio >= start:
            status = "running"
        else:
            status = "pending"

        steps.append(
            Step(
                key=key,
                label=STEP_LABELS[key],
                status=status,
                elapsed_ms=int(share * job.delay * 1000) if status in ("done", "skipped") else None,
            )
        )
    return steps


@app.post("/jobs", status_code=202, response_model=JobAcceptedResponse)
async def create_job(req: MockOrchestrateRequest) -> JobAcceptedResponse:
    job = MockJob(
        id=f"mock_{uuid.uuid4().hex[:12]}",
        track=req.track,
        fixture=req.mock_fixture or DEFAULT_FIXTURE[req.track],
        delay=max(req.mock_delay, 0.1),  # 0이면 진행률 계산에서 0으로 나눈다
        fail=req.mock_fail,
        started_at=time.monotonic(),
    )
    load_fixture(job.fixture)  # 존재하지 않는 fixture면 접수 시점에 400으로 알려준다
    JOBS[job.id] = job
    return JobAcceptedResponse(job_id=job.id, status=JobStatus.PENDING)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            404,
            detail={"code": ErrorCode.JOB_NOT_FOUND.value, "message": "job을 찾을 수 없습니다"},
        )

    elapsed = time.monotonic() - job.started_at
    elapsed_ms = int(elapsed * 1000)

    if elapsed < PENDING_WINDOW:
        return JobStatusResponse(
            job_id=job.id,
            status=JobStatus.PENDING,
            steps=build_steps(job, 0.0, finished=False),
            elapsed_ms=elapsed_ms,
        )

    if elapsed < job.delay:
        return JobStatusResponse(
            job_id=job.id,
            status=JobStatus.RUNNING,
            steps=build_steps(job, elapsed, finished=False),
            elapsed_ms=elapsed_ms,
        )

    if job.fail is not None:
        return JobStatusResponse(
            job_id=job.id,
            status=JobStatus.FAILED,
            steps=build_steps(job, elapsed, finished=False),  # 실패 지점에서 멈춘 상태로 보여준다
            error=ErrorDetail(code=job.fail, message=MOCK_FAIL_MESSAGES[job.fail]),
            elapsed_ms=elapsed_ms,
        )

    return JobStatusResponse(
        job_id=job.id,
        status=JobStatus.DONE,
        steps=build_steps(job, elapsed, finished=True),
        result=load_fixture(job.fixture),
        elapsed_ms=elapsed_ms,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        indexed_counts={"cosmetic": 0, "fragrance": 0},  # mock이므로 0
    )

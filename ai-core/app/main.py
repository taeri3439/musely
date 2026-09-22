from __future__ import annotations

import asyncio
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.graph.build import graph
from app.graph.state import empty_state
from app.jobs import _now, steps_from_trace, store
from app.schemas import (
    Candidate,
    Caution,
    FragranceNotes,
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
    STEP_LABELS,
)

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="musely ai-core", version="0.2.0")


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.post("/jobs", status_code=202, response_model=JobAcceptedResponse)
async def create_job(req: OrchestrateRequest, bg: BackgroundTasks) -> JobAcceptedResponse:
    job = store.create()
    bg.add_task(run_job, job.id, req)
    return JobAcceptedResponse(job_id=job.id, status=job.status)


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str) -> JobStatusResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(
            404,
            detail={"code": ErrorCode.JOB_NOT_FOUND.value, "message": "job을 찾을 수 없습니다"},
        )
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        steps=job.steps,
        result=job.result,
        error=ErrorDetail(**job.error) if job.error else None,
        elapsed_ms=job.elapsed_ms,
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    try:
        from app.graph.agents.ingredient_matcher import get_store
        from app.retrieval.store import FragranceStore

        n_cos = get_store().count()
        n_frag = FragranceStore().count()
        return HealthResponse(
            status="ok",
            indexed_counts={"cosmetic": n_cos, "fragrance": n_frag},
        )
    except Exception:
        return HealthResponse(status="degraded", indexed_counts={"cosmetic": 0, "fragrance": 0})


def _mark_running(job) -> None:
    job.status = JobStatus.RUNNING
    job.steps = [
        Step(key=StepKey.PROFILE, label=STEP_LABELS[StepKey.PROFILE], status="done"),
        Step(key=StepKey.SEARCH, label=STEP_LABELS[StepKey.SEARCH], status="running"),
        Step(key=StepKey.CONFLICT, label=STEP_LABELS[StepKey.CONFLICT], status="pending"),
        Step(key=StepKey.COMMENTARY, label=STEP_LABELS[StepKey.COMMENTARY], status="pending"),
    ]


async def run_job(job_id: str, req: OrchestrateRequest) -> None:
    job = store.get(job_id)
    if job is None:
        return
    _mark_running(job)
    try:
        state = await asyncio.wait_for(execute(req), timeout=settings.job_timeout_seconds)
        empty = not state["candidates"]
        job.steps = steps_from_trace(
            state.get("trace") or [],
            empty=empty,
            track=req.track,
        )
        # profile은 항상 done
        if job.steps:
            job.steps[0] = Step(
                key=StepKey.PROFILE,
                label=STEP_LABELS[StepKey.PROFILE],
                status="done",
            )
        job.result = to_result(state, track=req.track)
        job.status = JobStatus.DONE
    except asyncio.TimeoutError:
        job.status = JobStatus.FAILED
        job.error = {"code": ErrorCode.TIMEOUT.value, "message": "30초 내 완료되지 않았습니다"}
    except Exception:
        logger.exception("job %s failed", job_id)
        job.status = JobStatus.FAILED
        job.error = {"code": ErrorCode.INTERNAL.value, "message": "내부 오류가 발생했습니다"}
    finally:
        job.finished_at = _now()


async def execute(req: OrchestrateRequest) -> dict:
    if req.track == "fragrance":
        profile = {
            "preferred_scent_families": req.preferred_scent_families,
            "occasion": req.occasion,
        }
        return await graph.ainvoke(empty_state(profile, "fragrance"))
    if req.track == "both":
        profile = {
            "skin_type": req.skin_type,
            "concerns": req.concerns,
            "avoid_ingredients": req.avoid_ingredients,
            "current_actives": req.current_actives,
            "category": req.category,
        }
        return await graph.ainvoke(empty_state(profile, "cosmetic"))
    profile = {
        "skin_type": req.skin_type,
        "concerns": req.concerns,
        "avoid_ingredients": req.avoid_ingredients,
        "current_actives": req.current_actives,
        "category": req.category,
    }
    return await graph.ainvoke(empty_state(profile, "cosmetic"))


def _candidate_from_dict(c: dict, *, fragrance: bool) -> Candidate:
    notes_raw = c.get("notes")
    notes = None
    if fragrance and isinstance(notes_raw, dict):
        notes = FragranceNotes.model_validate(notes_raw)
    return Candidate(
        item_id=c["item_id"],
        name=c["name"],
        brand=c["brand"],
        score=c["score"],
        note=c["note"],
        category=c.get("category") if not fragrance else None,
        notes=notes,
    )


def to_result(state: dict, *, track: str = "cosmetic") -> OrchestrateResult:
    candidates = state.get("candidates") or []
    is_fragrance = track == "fragrance"
    cosmetic = [
        _candidate_from_dict(c, fragrance=False)
        for c in candidates
        if not is_fragrance
    ]
    fragrance = [
        _candidate_from_dict(c, fragrance=True)
        for c in candidates
        if is_fragrance
    ]
    return OrchestrateResult(
        summary=state.get("summary") or "조건에 맞는 제품을 찾지 못했어요.",
        cosmetic=cosmetic,
        fragrance=fragrance,
        cautions=[Caution.model_validate(c) for c in state.get("cautions") or []],
        relaxation_level=state.get("relaxation_level") or 0,
        blocked_by=state.get("blocked_by") or [],
    )
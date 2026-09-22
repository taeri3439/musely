from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.schemas import STEP_LABELS, JobStatus, OrchestrateResult, Step, StepKey, Track

def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    result: OrchestrateResult | None = None
    error: dict[str, str] | None = None
    steps: list[Step] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None

    @property
    def elapsed_ms(self) -> int:
        end = self.finished_at or _now()
        return int((end - self.created_at).total_seconds() * 1000)


class JobStore:
    def __init__(self, ttl_minutes: int = 30) -> None:
        self._jobs: dict[str, Job] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def create(self) -> Job:
        self._sweep()
        job = Job(id=f"job_{uuid.uuid4().hex[:12]}")
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _sweep(self) -> None:
        cutoff = _now() - self._ttl
        for key in [k for k, v in self._jobs.items() if v.created_at < cutoff]:
            del self._jobs[key]


def steps_from_trace(
    trace: list[dict[str, Any]],
    *,
    empty: bool,
    track: Track = "cosmetic",
) -> list[Step]:
    """내부 노드명 → 화면 steps. commentary는 0건이면 skipped."""
    nodes = {row["node"] for row in trace}
    elapsed = {row["node"]: row.get("elapsed_ms") for row in trace}
    if track == "both":
        return _steps_both(trace, empty=empty)

    search_node = "scent_matcher" if track == "fragrance" else "ingredient_matcher"
    skip_conflict = track == "fragrance"

    def one(key: StepKey, node: str | None, *, skipped: bool = False) -> Step:
        if skipped:
            status = "skipped"
        elif node and node in nodes:
            status = "done"
        else:
            status = "pending"
        return Step(
            key=key,
            label=STEP_LABELS[key],
            status=status,
            elapsed_ms=elapsed.get(node) if node and status == "done" else None,
        )

    return [
        one(StepKey.PROFILE, None),
        one(StepKey.SEARCH, search_node),
        one(StepKey.CONFLICT, "conflict_checker", skipped=skip_conflict),
        one(StepKey.COMMENTARY, "commentary", skipped=empty),
    ]


def _steps_both(trace: list[dict[str, Any]], *, empty: bool) -> list[Step]:
    nodes = {row["node"] for row in trace}
    elapsed = {row["node"]: row.get("elapsed_ms") for row in trace}
    search_done = "ingredient_matcher" in nodes and "scent_matcher" in nodes
    search_ms = None
    if search_done:
        search_ms = (elapsed.get("ingredient_matcher") or 0) + (elapsed.get("scent_matcher") or 0)
    conflict_skipped = "ingredient_matcher" in nodes and "conflict_checker" not in nodes
    if conflict_skipped:
        conflict_status = "skipped"
        conflict_ms = None
    elif "conflict_checker" in nodes:
        conflict_status = "done"
        conflict_ms = elapsed.get("conflict_checker")
    else:
        conflict_status = "pending"
        conflict_ms = None
    if empty:
        commentary_status = "skipped"
        commentary_ms = None
    elif "commentary" in nodes:
        commentary_status = "done"
        commentary_ms = elapsed.get("commentary")
    else:
        commentary_status = "pending"
        commentary_ms = None

    return [
        Step(key=StepKey.PROFILE, label=STEP_LABELS[StepKey.PROFILE], status="done"),
        Step(
            key=StepKey.SEARCH,
            label=STEP_LABELS[StepKey.SEARCH],
            status="done" if search_done else "pending",
            elapsed_ms=search_ms,
        ),
        Step(
            key=StepKey.CONFLICT,
            label=STEP_LABELS[StepKey.CONFLICT],
            status=conflict_status,
            elapsed_ms=conflict_ms,
        ),
        Step(
            key=StepKey.COMMENTARY,
            label=STEP_LABELS[StepKey.COMMENTARY],
            status=commentary_status,
            elapsed_ms=commentary_ms,
        ),
    ]


store = JobStore(ttl_minutes=get_settings().job_ttl_minutes)
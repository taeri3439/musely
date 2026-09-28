"""Job API E2E — POST /jobs → GET 폴링 → 계약·steps·결과 검증.

TestClient가 BackgroundTasks를 POST 직후 실행한다. 인덱스 필요.

실행 (ai-core):
    python -m scripts.e2e_jobs

주간 묶음:
    python -m scripts.run_weekly_checks
"""

from __future__ import annotations

import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.qna.store import FaqStore
from app.retrieval.store import CosmeticStore, FragranceStore
from app.schemas import JobStatus, JobStatusResponse, OrchestrateRequest, QnaResponse

POLL_INTERVAL_SEC = 0.4
JOB_TIMEOUT_SEC = 120.0

CASES: list[dict[str, Any]] = [
    {
        "id": "job_cosmetic",
        "request": {
            "profileId": "e2e_cos",
            "track": "cosmetic",
            "skinType": "combination",
            "concerns": ["모공", "수분"],
            "avoidIngredients": ["알코올"],
            "currentActives": ["레티놀"],
        },
        "expect_cosmetic_min": 1,
        "expect_fragrance_min": 0,
        "must_exclude_cosmetic": ["p_002", "p_005", "p_010"],
        "conflict_step": "done",
    },
    {
        "id": "job_fragrance",
        "request": {
            "profileId": "e2e_frag",
            "track": "fragrance",
            "preferredScentFamilies": ["우디", "머스크"],
            "occasion": "오피스",
        },
        "expect_cosmetic_min": 0,
        "expect_fragrance_min": 1,
        "conflict_step": "skipped",
    },
    {
        "id": "job_both",
        "request": {
            "profileId": "e2e_both",
            "track": "both",
            "skinType": "combination",
            "concerns": ["모공"],
            "avoidIngredients": ["알코올"],
            "preferredScentFamilies": ["우디"],
            "occasion": "오피스",
        },
        "expect_cosmetic_min": 1,
        "expect_fragrance_min": 1,
        "must_exclude_cosmetic": ["p_002"],
        "conflict_step": "done",
    },
]


QNA_CASES: list[dict[str, Any]] = [
    {"question": "레티놀 처음 쓰는데 매일 발라도 돼?", "intent": "faq"},
    {"question": "레티놀이랑 BHA 같이 써도 돼요?", "intent": "pair"},
    {"question": "건성인데 토너 추천해줘", "intent": "recommend"},
    {"question": "오늘 서울 날씨 어때?", "intent": "unknown"},
]


def _ensure_index() -> None:
    cos = CosmeticStore()
    frag = FragranceStore()
    faq = FaqStore()
    if cos.count() == 0:
        print("cosmetic 인덱스 rebuild...")
        cos.rebuild()
    if frag.count() == 0:
        print("fragrance 인덱스 rebuild...")
        frag.rebuild()
    if faq.count() == 0:
        print("faq 인덱스 rebuild...")
        faq.rebuild()


def _validate_qna(case: dict[str, Any], body: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    resp = QnaResponse.model_validate(body)
    if resp.intent != case["intent"]:
        errors.append(f"intent {resp.intent} != {case['intent']}")
    if not resp.answer.strip():
        errors.append("answer 비어 있음")
    if resp.intent in ("faq", "pair") and not resp.sources:
        errors.append("근거(sources) 없음")
    if resp.intent == "pair" and not resp.cautions:
        errors.append("pair인데 cautions 없음")
    if resp.intent == "recommend" and resp.redirect != "recommend":
        errors.append("recommend인데 redirect 없음")
    return errors


def _step_status(steps: list[dict], key: str) -> str | None:
    for row in steps:
        if row.get("key") == key:
            return row.get("status")
    return None


def _poll_job(client: TestClient, job_id: str) -> JobStatusResponse:
    deadline = time.monotonic() + JOB_TIMEOUT_SEC
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/jobs/{job_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"GET /jobs/{job_id} → {resp.status_code} {resp.text}")
        last = resp.json()
        status = last.get("status")
        if status in (JobStatus.DONE.value, JobStatus.FAILED.value):
            return JobStatusResponse.model_validate(last)
        time.sleep(POLL_INTERVAL_SEC)
    raise TimeoutError(f"job {job_id} did not finish in {JOB_TIMEOUT_SEC}s (last={last})")


def _validate_case(case: dict[str, Any], body: JobStatusResponse) -> list[str]:
    errors: list[str] = []
    if body.status != JobStatus.DONE:
        err = body.error.message if body.error else "unknown"
        errors.append(f"status={body.status} error={err}")
        return errors

    result = body.result
    if result is None:
        errors.append("result가 null")
        return errors

    cos_ids = [c.item_id for c in result.cosmetic]
    frag_ids = [c.item_id for c in result.fragrance]

    if len(result.cosmetic) < case["expect_cosmetic_min"]:
        errors.append(f"cosmetic {len(result.cosmetic)} < {case['expect_cosmetic_min']}")
    if len(result.fragrance) < case["expect_fragrance_min"]:
        errors.append(f"fragrance {len(result.fragrance)} < {case['expect_fragrance_min']}")

    for iid in case.get("must_exclude_cosmetic") or []:
        if iid in cos_ids:
            errors.append(f"cosmetic에 {iid}가 포함됨")

    for c in result.cosmetic:
        if not (c.note or "").strip():
            errors.append(f"cosmetic {c.item_id} note 비어 있음")
    for c in result.fragrance:
        if not (c.note or "").strip():
            errors.append(f"fragrance {c.item_id} note 비어 있음")
        if c.notes is None:
            errors.append(f"fragrance {c.item_id} notes null")

    if not (result.summary or "").strip():
        errors.append("summary 비어 있음")

    steps_raw = [s.model_dump(mode="json", by_alias=True) for s in body.steps]
    for key in ("profile", "search", "conflict", "commentary"):
        st = _step_status(steps_raw, key)
        if st is None:
            errors.append(f"step {key} 없음")
    exp_conflict = case.get("conflict_step")
    if exp_conflict and _step_status(steps_raw, "conflict") != exp_conflict:
        errors.append(
            f"conflict step expected {exp_conflict}, got {_step_status(steps_raw, 'conflict')}"
        )
    if _step_status(steps_raw, "search") != "done":
        errors.append(f"search step={_step_status(steps_raw, 'search')}")
    if _step_status(steps_raw, "commentary") != "done":
        errors.append(f"commentary step={_step_status(steps_raw, 'commentary')}")

    return errors


def main() -> int:
    _ensure_index()
    problems: list[str] = []

    print(f"cases: {len(CASES)}  timeout={JOB_TIMEOUT_SEC}s\n")

    with TestClient(app) as client:
        health = client.get("/health")
        if health.status_code != 200:
            problems.append(f"/health → {health.status_code}")
        else:
            print(f"health: {health.json()}")

        for case in CASES:
            case_id = case["id"]
            req_body = case["request"]
            OrchestrateRequest.model_validate(req_body)

            post = client.post("/jobs", json=req_body)
            if post.status_code != 202:
                problems.append(f"{case_id}: POST → {post.status_code} {post.text}")
                continue
            job_id = post.json()["jobId"]
            print(f"[run] {case_id}  jobId={job_id}")

            try:
                final = _poll_job(client, job_id)
            except (TimeoutError, RuntimeError) as exc:
                problems.append(f"{case_id}: {exc}")
                continue

            errs = _validate_case(case, final)
            n_cos = len(final.result.cosmetic) if final.result else 0
            n_frag = len(final.result.fragrance) if final.result else 0
            line = f"[{'OK' if not errs else 'FAIL'}] {case_id}  cos={n_cos} frag={n_frag}  elapsed={final.elapsed_ms}ms"
            print(line)
            for e in errs:
                print(f"    - {e}")
                problems.append(f"{case_id}: {e}")

        print()
        for case in QNA_CASES:
            resp = client.post("/qna", json={"question": case["question"]})
            if resp.status_code != 200:
                problems.append(f"qna {case['question']}: {resp.status_code} {resp.text}")
                continue
            body = resp.json()
            errs = _validate_qna(case, body)
            mark = "OK" if not errs else "FAIL"
            print(f"[{mark}] qna {body['intent']:9} llm={body['usedLlm']}  {case['question']}")
            print(f"      → {body['answer'][:80]}")
            for e in errs:
                print(f"    - {e}")
                problems.append(f"qna {case['question']}: {e}")

    print()
    if problems:
        print(f"실패 {len(problems)}건")
        return 1
    print("모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

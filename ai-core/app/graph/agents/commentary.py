"""설명 생성 — 지금은 LLM 없이 템플릿만. 0건이면 그래프가 여기로 오지 않는다."""

from __future__ import annotations

import time
from typing import Any

from app.graph.state import CurationState, append_trace


async def commentary(state: CurationState) -> dict[str, Any]:
    started = time.perf_counter()
    candidates = list(state.get("candidates") or [])
    cautions = state.get("cautions") or []
    n = len(candidates)
    level = state.get("relaxation_level") or 0

    if level > 0:
        summary = f"조건에 딱 맞는 제품이 적어서 일부 조건을 완화했고, {n}개를 골랐어요."
    else:
        summary = f"기피 성분을 제외하고 {n}개를 골랐어요."
    if cautions:
        summary += " 지금 쓰는 성분과 겹치는 조합은 주의사항에 적어 두었어요."

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "summary": summary,
        "candidates": candidates,
        "trace": append_trace(state, "commentary", elapsed_ms, llm=False),
    }

"""설명 생성. 후보가 있을 때만 그래프가 여기로 온다. LLM 실패 시 템플릿으로 폴백."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.graph.state import CurationState, append_trace
from app.llm import CommentaryOut, generate_commentary

logger = logging.getLogger(__name__)


def _fallback_summary(state: CurationState) -> str:
    n = len(state.get("candidates") or [])
    level = state.get("relaxation_level") or 0
    if level > 0:
        summary = f"조건에 딱 맞는 제품이 적어서 일부 조건을 완화했고, {n}개를 골랐어요."
    else:
        summary = f"기피 성분을 제외하고 {n}개를 골랐어요."
    if state.get("cautions"):
        summary += " 지금 쓰는 성분과 겹치는 조합은 주의사항에 적어 두었어요."
    return summary


def _apply_notes(candidates: list[dict[str, Any]], out: CommentaryOut) -> list[dict[str, Any]]:
    """후보에 있는 item_id만 note를 덮는다. 없는 id는 환각이므로 버린다."""
    allowed = {c["item_id"] for c in candidates}
    notes = {item.item_id: item.note for item in out.per_item if item.item_id in allowed}
    updated = []
    for c in candidates:
        row = dict(c)
        if row["item_id"] in notes:
            row["note"] = notes[row["item_id"]]
        updated.append(row)
    return updated


async def commentary(state: CurationState) -> dict[str, Any]:
    started = time.perf_counter()
    candidates = [dict(c) for c in (state.get("candidates") or [])]
    summary = _fallback_summary(state)
    used_llm = False

    try:
        out = await generate_commentary(
            candidates=candidates,
            cautions=state.get("cautions") or [],
            profile=state.get("profile") or {},
        )
        summary = out.summary
        candidates = _apply_notes(candidates, out)
        used_llm = True
    except Exception:
        logger.exception("commentary LLM 실패, 템플릿으로 폴백")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "summary": summary,
        "candidates": candidates,
        "trace": append_trace(state, "commentary", elapsed_ms, llm=used_llm),
    }
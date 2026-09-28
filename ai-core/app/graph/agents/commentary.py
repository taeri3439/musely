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
    track = state.get("track") or "cosmetic"
    if track == "fragrance":
        if level > 0:
            summary = f"선호 계열에 딱 맞는 향이 적어서 조건을 일부 완화했고, {n}개를 골랐어요."
        else:
            summary = f"입력하신 계열·상황을 반영해 {n}개를 골랐어요."
        return summary
    if level > 0:
        summary = f"조건에 딱 맞는 제품이 적어서 일부 조건을 완화했고, {n}개를 골랐어요."
    else:
        summary = f"기피 성분을 제외하고 {n}개를 골랐어요."
    if state.get("cautions"):
        summary += " 지금 쓰는 성분과 겹치는 조합은 주의사항에 적어 두었어요."
    return summary


def _apply_notes(
    candidates: list[dict[str, Any]],
    out: CommentaryOut,
) -> tuple[list[dict[str, Any]], list[str]]:
    """LLM note를 덮는다. 빠진 id·빈 note·목록 밖 id는 템플릿 note를 유지한다."""
    allowed = {c["item_id"] for c in candidates}
    notes = {
        item.item_id: item.note.strip()
        for item in out.per_item
        if item.item_id in allowed and (item.note or "").strip()
    }
    warnings: list[str] = []
    if len(out.per_item) != len(candidates):
        warnings.append(
            f"per_item {len(out.per_item)}개 != 후보 {len(candidates)}개 — 빠진 카드는 템플릿 note 유지"
        )
    for item in out.per_item:
        if item.item_id not in allowed:
            warnings.append(f"per_item에 없는 id {item.item_id!r} — 무시")
        elif item.item_id in allowed and not (item.note or "").strip():
            warnings.append(f"{item.item_id} note가 비어 있음 — 템플릿 note 유지")

    updated = []
    for c in candidates:
        row = dict(c)
        iid = row["item_id"]
        if iid in notes:
            row["note"] = notes[iid]
        elif iid not in notes and iid in allowed:
            warnings.append(f"{iid} per_item 누락 — 템플릿 note 유지")
        updated.append(row)
    return updated, warnings


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
            track=state.get("track") or "cosmetic",
        )
        summary = (out.summary or "").strip() or _fallback_summary(state)
        candidates, note_warnings = _apply_notes(candidates, out)
        for w in note_warnings:
            logger.warning("commentary note: %s", w)
        used_llm = True
    except Exception:
        logger.exception("commentary LLM 실패, 템플릿으로 폴백")

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "summary": summary,
        "candidates": candidates,
        "trace": append_trace(state, "commentary", elapsed_ms, llm=used_llm),
    }
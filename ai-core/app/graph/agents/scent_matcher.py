"""향수 매칭 — FragranceStore.search를 호출한다."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.graph.state import CurationState, append_trace
from app.retrieval.store import FragranceStore, SearchResult

_store: FragranceStore | None = None


def get_fragrance_store() -> FragranceStore:
    global _store
    if _store is None:
        _store = FragranceStore()
    return _store


def _hit_to_candidate(hit) -> dict[str, Any]:
    row = hit.product
    family = row.get("note_family") or ""
    return {
        "item_id": row["item_id"],
        "name": row["name"],
        "brand": row["brand"],
        "score": hit.score,
        "category": None,
        "actives": [],
        "key_ingredients": [],
        "notes": {
            "family": family,
            "top": list(row.get("top") or []),
            "heart": list(row.get("heart") or []),
            "base": list(row.get("base") or []),
        },
        "note": f"{family} 계열 중에서 선호 조건을 통과한 향이에요." if family else "선호 조건을 통과한 향이에요.",
    }


async def scent_matcher(state: CurationState) -> dict[str, Any]:
    profile = state["profile"]
    started = time.perf_counter()
    result: SearchResult = await asyncio.to_thread(
        get_fragrance_store().search,
        preferred_scent_families=profile.get("preferred_scent_families") or [],
        occasion=profile.get("occasion"),
        k=5,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    candidates = [_hit_to_candidate(h) for h in result.hits]
    return {
        "candidates": candidates,
        "relaxation_level": result.relaxation_level,
        "blocked_by": result.blocked_by,
        "trace": append_trace(
            state,
            "scent_matcher",
            elapsed_ms,
            hit_count=len(candidates),
            relaxation_level=result.relaxation_level,
        ),
    }

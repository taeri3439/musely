"""성분 매칭 — 검색을 다시 짜지 않고 CosmeticStore.search를 호출한다."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from app.graph.state import CurationState, append_trace
from app.retrieval.store import CosmeticStore, SearchResult

_store: CosmeticStore | None = None


def get_store() -> CosmeticStore:
    global _store
    if _store is None:
        _store = CosmeticStore()
    return _store


def _hit_to_candidate(hit) -> dict[str, Any]:
    product = hit.product
    category = product.get("category") or ""
    return {
        "item_id": product["item_id"],
        "name": product["name"],
        "brand": product["brand"],
        "score": hit.score,
        "category": product.get("category"),
        "actives": list(product.get("actives") or []),
        "key_ingredients": list(product.get("key_ingredients") or []),
        "note": f"{category} 중에서 기피 조건을 통과한 제품이에요." if category else "기피 조건을 통과한 제품이에요.",
    }


async def ingredient_matcher(state: CurationState) -> dict[str, Any]:
    profile = state["profile"]
    started = time.perf_counter()
    result: SearchResult = await asyncio.to_thread(
        get_store().search,
        skin_type=profile.get("skin_type"),
        concerns=profile.get("concerns") or [],
        avoid_ingredients=profile.get("avoid_ingredients") or [],
        category=profile.get("category"),
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
            "ingredient_matcher",
            elapsed_ms,
            hit_count=len(candidates),
            relaxation_level=result.relaxation_level,
        ),
    }

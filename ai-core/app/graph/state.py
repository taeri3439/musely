"""그래프 노드가 주고받는 상태. 화면 계약(Candidate)과 달리 actives를 내부에 남긴다."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class CurationState(TypedDict):
    profile: dict[str, Any]
    track: Literal["cosmetic", "fragrance"]
    candidates: list[dict[str, Any]]
    cautions: list[dict[str, Any]]
    relaxation_level: int
    blocked_by: list[str]
    summary: str
    trace: list[dict[str, Any]]


def empty_state(profile: dict[str, Any], track: Literal["cosmetic", "fragrance"] = "cosmetic") -> CurationState:
    return {
        "profile": profile,
        "track": track,
        "candidates": [],
        "cautions": [],
        "relaxation_level": 0,
        "blocked_by": [],
        "summary": "",
        "trace": [],
    }


def append_trace(state: CurationState, node: str, elapsed_ms: int, **extra: Any) -> list[dict[str, Any]]:
    entry: dict[str, Any] = {"node": node, "elapsed_ms": elapsed_ms, **extra}
    return [*state.get("trace", []), entry]

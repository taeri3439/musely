"""그래프 E2E(검색·충돌·설명) — cosmetic / fragrance / both.

인덱스가 없으면 만든다. 후보가 있으면 LLM 호출이 나갈 수 있다.

실행 (ai-core 디렉터리):
    python -m scripts.check_graph
"""

from __future__ import annotations

import asyncio
import sys

from app.graph.agents.commentary import _apply_notes
from app.graph.agents.conflict_checker import conflict_checker
from app.graph.build import graph
from app.graph.state import CurationState, empty_state
from app.llm import CommentaryOut, ItemNote
from app.main import execute
from app.retrieval.store import CosmeticStore, FragranceStore
from app.schemas import OrchestrateRequest


def _ids(state: CurationState) -> list[str]:
    return [c["item_id"] for c in state.get("candidates") or []]


def _nodes(state: CurationState) -> list[str]:
    return [t["node"] for t in state.get("trace") or []]


async def _run_cosmetic(profile: dict) -> CurationState:
    return await graph.ainvoke(empty_state(profile, "cosmetic"))


async def _run_fragrance(profile: dict) -> CurationState:
    return await graph.ainvoke(empty_state(profile, "fragrance"))


def _check_apply_notes() -> list[str]:
    problems: list[str] = []
    base = [{"item_id": "p_001", "note": "템플릿 A"}, {"item_id": "p_003", "note": "템플릿 B"}]
    partial = CommentaryOut(
        summary="s",
        per_item=[ItemNote(item_id="p_001", note="LLM 문장")],
    )
    updated, warnings = _apply_notes(base, partial)
    if updated[0]["note"] != "LLM 문장":
        problems.append("_apply_notes: LLM note가 반영되지 않았다")
    if updated[1]["note"] != "템플릿 B":
        problems.append("_apply_notes: 누락 id는 템플릿을 유지해야 한다")
    if not any("누락" in w for w in warnings):
        problems.append("_apply_notes: 누락 경고가 없다")

    empty_note = CommentaryOut(
        summary="s",
        per_item=[ItemNote(item_id="p_001", note="   ")],
    )
    kept, _ = _apply_notes([{"item_id": "p_001", "note": "템플릿"}], empty_note)
    if kept[0]["note"] != "템플릿":
        problems.append("_apply_notes: 빈 LLM note는 템플릿을 유지해야 한다")
    return problems


async def main() -> int:
    cos_store = CosmeticStore()
    frag_store = FragranceStore()
    if cos_store.count() == 0:
        print("cosmetic 인덱스 rebuild...")
        cos_store.rebuild()
    if frag_store.count() == 0:
        print("fragrance 인덱스 rebuild...")
        frag_store.rebuild()

    problems: list[str] = []
    problems.extend(_check_apply_notes())

    alcohol = await _run_cosmetic({
        "skin_type": "combination",
        "concerns": ["트러블"],
        "avoid_ingredients": ["알코올"],
        "current_actives": [],
    })
    print(f"[cos] 기피=알코올 → {_ids(alcohol)}  relax={alcohol['relaxation_level']}  nodes={_nodes(alcohol)}")
    for bad in ("p_002", "p_005", "p_010"):
        if bad in _ids(alcohol):
            problems.append(f"그래프 결과에 에탄올 제품 {bad}가 있다")
    if not _ids(alcohol):
        problems.append("알코올 기피 검색이 0건이다")
    if "commentary" not in _nodes(alcohol):
        problems.append("후보가 있는데 commentary가 안 돌았다")

    retinol = await _run_cosmetic({
        "skin_type": "combination",
        "concerns": ["모공"],
        "avoid_ingredients": [],
        "current_actives": ["레티놀"],
    })
    caution_pairs = [tuple(c["pair"]) for c in retinol.get("cautions") or []]
    print(f"[cos] 사용중=레티놀 → {_ids(retinol)}  cautions={caution_pairs}")
    actives_present = {a for c in retinol["candidates"] for a in c.get("actives") or []}
    if "bha" in actives_present and ("retinol", "bha") not in caution_pairs:
        problems.append("bha 후보가 있는데 retinol+bha caution이 없다")
    if "vitamin_c" in actives_present and ("retinol", "vitamin_c") not in caution_pairs:
        problems.append("vitamin_c 후보가 있는데 retinol+vitamin_c caution이 없다")

    dropped = await conflict_checker({
        **empty_state({"current_actives": ["레티놀"]}, "cosmetic"),
        "candidates": [
            {"item_id": "x_avoid", "actives": ["benzoyl_peroxide"], "name": "dummy"},
            {"item_id": "x_ok", "actives": ["niacinamide"], "name": "ok"},
        ],
    })
    dropped_ids = _ids(dropped)
    print(f"[cos] avoid 규칙 → kept={dropped_ids}")
    if "x_avoid" in dropped_ids:
        problems.append("avoid 후보가 안 빠졌다")
    if "x_ok" not in dropped_ids:
        problems.append("무관한 후보까지 빠졌다")

    empty = await _run_cosmetic({
        "avoid_ingredients": ["알코올", "향료", "파라벤", "에센셜오일"]
        + [p["ingredients"][0] for p in cos_store.catalog.values() if p.get("ingredients")],
    })
    print(f"[cos] 0건 → hits={len(empty['candidates'])}  nodes={_nodes(empty)}")
    if empty["candidates"]:
        problems.append("0건이어야 하는데 후보가 있다")
    if "commentary" in _nodes(empty):
        problems.append("0건인데 commentary가 돌았다")
    if not empty.get("blocked_by"):
        problems.append("0건인데 blocked_by가 비어 있다")

    woody = await _run_fragrance({
        "preferred_scent_families": ["우디"],
        "occasion": "오피스",
    })
    print(f"[frag] 우디+오피스 → {_ids(woody)}  nodes={_nodes(woody)}")
    if not _ids(woody):
        problems.append("향수 우디 검색이 0건이다")
    if "scent_matcher" not in _nodes(woody):
        problems.append("향수 그래프에 scent_matcher가 없다")
    if "conflict_checker" in _nodes(woody):
        problems.append("향수 그래프에 conflict_checker가 돌았다")
    if "commentary" not in _nodes(woody):
        problems.append("향수 후보가 있는데 commentary가 없다")
    for c in woody["candidates"]:
        notes = c.get("notes")
        if not isinstance(notes, dict) or not notes.get("family"):
            problems.append(f"{c['item_id']}에 notes.family가 없다")

    both_req = OrchestrateRequest(
        profile_id="check_graph",
        track="both",
        skin_type="combination",
        concerns=["모공", "수분"],
        avoid_ingredients=["알코올"],
        current_actives=[],
        preferred_scent_families=["우디", "머스크"],
        occasion="오피스",
    )
    both_state = await execute(both_req)
    cos_ids = [c["item_id"] for c in both_state.get("cosmetic_candidates") or []]
    frag_ids = [c["item_id"] for c in both_state.get("fragrance_candidates") or []]
    trace_nodes = [t["node"] for t in both_state.get("trace") or []]
    print(f"[both] cos={cos_ids}  frag={frag_ids}  nodes={trace_nodes}")
    if not cos_ids or not frag_ids:
        problems.append("both에서 cosmetic 또는 fragrance 후보가 비었다")
    if "ingredient_matcher" not in trace_nodes or "scent_matcher" not in trace_nodes:
        problems.append("both trace에 두 매처가 모두 없다")
    for bad in ("p_002", "p_005", "p_010"):
        if bad in cos_ids:
            problems.append(f"both cosmetic에 에탄올 {bad}가 있다")

    if problems:
        print(f"\n문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

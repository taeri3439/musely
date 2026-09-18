"""화장품 그래프가 검색·충돌 검수를 한 줄로 도는지 확인한다.

인덱스가 없으면 여기서 만든다. Gemini 호출이 한두 번 나간다.

실행 (ai-core 디렉터리에서):
    python -m scripts.check_graph
"""

from __future__ import annotations

import asyncio
import sys

from app.graph.agents.conflict_checker import conflict_checker
from app.graph.build import graph
from app.graph.state import CurationState, empty_state
from app.retrieval.store import CosmeticStore


def _ids(state: CurationState) -> list[str]:
    return [c["item_id"] for c in state.get("candidates") or []]


def _nodes(state: CurationState) -> list[str]:
    return [t["node"] for t in state.get("trace") or []]


async def _run(profile: dict) -> CurationState:
    return await graph.ainvoke(empty_state(profile, "cosmetic"))


async def main() -> int:
    store = CosmeticStore()
    if store.count() == 0:
        print("인덱스가 비어 있어서 다시 넣습니다...")
        store.rebuild()

    problems: list[str] = []

    alcohol = await _run({
        "skin_type": "combination",
        "concerns": ["트러블"],
        "avoid_ingredients": ["알코올"],
        "current_actives": [],
    })
    print(f"기피=알코올 → {_ids(alcohol)}  relax={alcohol['relaxation_level']}  nodes={_nodes(alcohol)}")
    if "p_007" not in _ids(alcohol):
        problems.append("그래프 결과에 p_007이 없다")
    for bad in ("p_002", "p_005", "p_010"):
        if bad in _ids(alcohol):
            problems.append(f"그래프 결과에 에탄올 제품 {bad}가 있다")
    if "commentary" not in _nodes(alcohol):
        problems.append("후보가 있는데 commentary가 안 돌았다")

    retinol = await _run({
        "skin_type": "combination",
        "concerns": ["모공"],
        "avoid_ingredients": [],
        "current_actives": ["레티놀"],
    })
    caution_pairs = [tuple(c["pair"]) for c in retinol.get("cautions") or []]
    print(f"사용중=레티놀 → {_ids(retinol)}  cautions={caution_pairs}  nodes={_nodes(retinol)}")
    actives_present = {a for c in retinol["candidates"] for a in c.get("actives") or []}
    if "bha" in actives_present and ("retinol", "bha") not in caution_pairs:
        problems.append("bha 후보가 있는데 retinol+bha caution이 없다")
    if "vitamin_c" in actives_present and ("retinol", "vitamin_c") not in caution_pairs:
        problems.append("vitamin_c 후보가 있는데 retinol+vitamin_c caution이 없다")

    dropped = await conflict_checker({
        **empty_state({"current_actives": ["레티놀"]}),
        "candidates": [
            {"item_id": "x_avoid", "actives": ["benzoyl_peroxide"], "name": "dummy"},
            {"item_id": "x_ok", "actives": ["niacinamide"], "name": "ok"},
        ],
    })
    dropped_ids = _ids(dropped)
    print(f"avoid 규칙 → kept={dropped_ids}  cautions={[c['severity'] for c in dropped['cautions']]}")
    if "x_avoid" in dropped_ids:
        problems.append("avoid 후보가 안 빠졌다")
    if "x_ok" not in dropped_ids:
        problems.append("무관한 후보까지 빠졌다")

    empty = await _run({
        "avoid_ingredients": ["알코올", "향료", "파라벤", "에센셜오일"]
        + [p["ingredients"][0] for p in store.catalog.values() if p.get("ingredients")],
    })
    print(f"0건 → hits={len(empty['candidates'])}  nodes={_nodes(empty)}  blockedBy={empty['blocked_by']}")
    if empty["candidates"]:
        problems.append("0건이어야 하는데 후보가 있다")
    if "commentary" in _nodes(empty):
        problems.append("0건인데 commentary가 돌았다")
    if not empty.get("blocked_by"):
        problems.append("0건인데 blocked_by가 비어 있다")

    if problems:
        print(f"\n문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

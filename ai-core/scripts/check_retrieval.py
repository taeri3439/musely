"""하드 제약 필터가 세틸알코올을 에탄올과 섞지 않는지 확인한다.

서버를 띄울 필요 없다. 인덱스가 없으면 여기서 만든다.

실행 (ai-core 디렉터리에서):
    python -m scripts.check_retrieval
"""

from __future__ import annotations

import sys

from app.retrieval.store import CosmeticStore


def _ids(result) -> list[str]:
    return [h.product["item_id"] for h in result.hits]


def main() -> int:
    store = CosmeticStore()
    if store.count() == 0:
        print("인덱스가 비어 있어서 다시 넣습니다...")
        store.rebuild()

    problems: list[str] = []

    alcohol = store.search(
        skin_type="combination",
        concerns=["트러블"],
        avoid_ingredients=["알코올"],
        k=12,
    )
    ids = _ids(alcohol)
    print(f"기피=알코올  → {ids}  relaxation={alcohol.relaxation_level}")

    if "p_007" not in ids:
        problems.append("p_007(세틸알코올 젤크림)이 알코올 기피에서 탈락했다 — 불리언 필터 버그")
    if "p_012" not in ids:
        problems.append("p_012(세틸알코올 선크림)이 알코올 기피에서 탈락했다")
    for bad in ("p_002", "p_005", "p_010"):
        if bad in ids:
            problems.append(f"{bad}가 알코올 기피에 섞였다 — ethanol 제품이 빠져야 한다")

    toner = store.search(
        skin_type="combination",
        concerns=["트러블"],
        avoid_ingredients=["알코올"],
        category="토너",
        k=5,
    )
    toner_ids = _ids(toner)
    print(f"기피=알코올, 카테고리=토너 → {toner_ids}  relaxation={toner.relaxation_level}")
    if "p_002" in toner_ids:
        problems.append("에탄올 토너 p_002가 토너+알코올 기피에 나왔다")
    if not toner.hits:
        problems.append("토너+알코올 기피가 0건이다 (p_001, p_003이 있어야 한다)")
    if toner.relaxation_level != 0:
        problems.append("토너가 있는데 카테고리를 완화했다")

    # 없는 카테고리는 1단계에서 풀린다. 기피 성분은 그대로라 결과가 남아야 한다.
    relaxed = store.search(
        avoid_ingredients=["알코올"],
        category="존재하지않는카테고리",
        k=5,
    )
    print(
        f"없는 카테고리 완화 → {_ids(relaxed)}  "
        f"relaxation={relaxed.relaxation_level}"
    )
    if not relaxed.hits:
        problems.append("카테고리 완화 후에도 0건이다 — 기피만 남으면 후보가 있어야 한다")
    if relaxed.relaxation_level != 1:
        problems.append(f"없는 카테고리의 relaxation_level이 1이 아니라 {relaxed.relaxation_level}")
    for bad in ("p_002", "p_005", "p_010"):
        if bad in _ids(relaxed):
            problems.append(f"카테고리를 풀었는데도 {bad}(에탄올)가 섞였다")

    # 진짜 0건: 살아남은 제품의 전성분을 전부 직접 기피로 넣으면 후처리에서 다 탈락한다.
    flags = ("alcohol_free", "fragrance_free", "paraben_free", "essential_oil_free")
    remaining = [
        p for p in store.catalog.values()
        if all(p.get(f) for f in flags)
    ]
    custom = [p["ingredients"][0] for p in remaining if p.get("ingredients")]
    empty = store.search(
        avoid_ingredients=["알코올", "향료", "파라벤", "에센셜오일", *custom],
        k=5,
    )
    print(
        f"0건 케이스 → hits={len(empty.hits)} "
        f"relaxation={empty.relaxation_level} blockedBy={empty.blocked_by}"
    )
    if empty.hits:
        problems.append(f"전성분 전부 기피인데 결과가 나왔다: {_ids(empty)}")
    if empty.relaxation_level != 2:
        problems.append("0건일 때 relaxation_level이 2가 아니다")
    if not empty.blocked_by:
        problems.append("0건인데 blockedBy가 비어 있다")

    if problems:
        print(f"\n문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

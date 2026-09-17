"""하드 제약 필터.

임베딩은 부정을 못 잡는다. "알코올 안 들어간 토너"를 그대로 임베딩하면 알코올이
들어간 토너가 상위에 온다. 기피 성분은 전부 여기서 처리하고, 벡터에는 피부 타입·고민
같은 소프트 선호만 넣는다.

화면 1의 칩(알코올/향료/파라벤/에센셜오일)은 성분명이 아니라 분류다. 전성분에
"알코올"이 있는지로 걸러내면 세틸알코올(점도용 지방 알코올)이 들어간 제품이 탈락한다.
칩은 불리언 플래그로, 사용자가 직접 입력한 개별 성분만 전성분 문자열로 후처리한다.

Chroma 메타데이터는 문자열·숫자·불리언만 받아서 리스트 `$nin` 필터가 안 된다.
그래서 칩 → 불리언 where, 직접 입력 → 검색 후 파이썬 후처리로 나눈다.
"""

from __future__ import annotations

from typing import Any

# 화면 칩 / 자주 쓰는 표기 → 제품 불리언 필드. 이 키는 전성분 부분문자열로 절대 매칭하지 않는다.
CHIP_TO_FLAG: dict[str, str] = {
    "알코올": "alcohol_free",
    "alcohol": "alcohol_free",
    "에탄올": "alcohol_free",
    "ethanol": "alcohol_free",
    "향료": "fragrance_free",
    "fragrance": "fragrance_free",
    "파라벤": "paraben_free",
    "paraben": "paraben_free",
    "에센셜오일": "essential_oil_free",
    "에센셜 오일": "essential_oil_free",
    "essential oil": "essential_oil_free",
    "essentialoil": "essential_oil_free",
}

FLAG_LABELS: dict[str, str] = {
    "alcohol_free": "기피 성분: 알코올",
    "fragrance_free": "기피 성분: 향료",
    "paraben_free": "기피 성분: 파라벤",
    "essential_oil_free": "기피 성분: 에센셜오일",
}


def normalize_token(raw: str) -> str:
    return " ".join(raw.strip().lower().split())


def split_avoids(avoid_ingredients: list[str]) -> tuple[set[str], list[str]]:
    """칩으로 정규화되는 플래그와, 전성분에서 직접 찾을 토큰을 나눈다."""
    flags: set[str] = set()
    custom: list[str] = []
    for raw in avoid_ingredients:
        token = normalize_token(raw)
        if not token:
            continue
        flag = CHIP_TO_FLAG.get(token) or CHIP_TO_FLAG.get(raw.strip())
        if flag:
            flags.add(flag)
        else:
            custom.append(token)
    return flags, custom


def _chroma_where(conditions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def build_where(
    *,
    flags: set[str],
    category: str | None = None,
) -> dict[str, Any] | None:
    """Chroma `where`. 기피 플래그는 어떤 완화 단계에서도 빠지지 않는다."""
    conditions: list[dict[str, Any]] = [{flag: True} for flag in sorted(flags)]
    if category:
        conditions.append({"category": category})
    return _chroma_where(conditions)


def relaxation_chain(
    avoid_ingredients: list[str],
    category: str | None,
) -> list[tuple[int, dict[str, Any] | None, set[str], list[str]]]:
    """(level, where, flags, custom) 순서. 카테고리만 풀고 기피는 풀지 않는다."""
    flags, custom = split_avoids(avoid_ingredients)
    chain: list[tuple[int, dict[str, Any] | None, set[str], list[str]]] = [
        (0, build_where(flags=flags, category=category), flags, custom),
    ]
    if category:
        chain.append((1, build_where(flags=flags, category=None), flags, custom))
    return chain


def post_filter(
    products: list[dict[str, Any]],
    custom: list[str],
) -> list[dict[str, Any]]:
    """직접 입력 성분이 전성분에 있으면 제외. 칩(알코올 등)은 여기로 오지 않는다."""
    if not custom:
        return products
    kept: list[dict[str, Any]] = []
    for product in products:
        names = [normalize_token(x) for x in product.get("ingredients", [])]
        if any(token in name or name in token for token in custom for name in names):
            continue
        kept.append(product)
    return kept


def build_query_text(
    *,
    skin_type: str | None,
    concerns: list[str],
    category: str | None,
) -> str:
    """벡터에 넣을 소프트 선호. 기피 성분은 넣지 않는다(부정을 못 잡아서)."""
    parts: list[str] = []
    if skin_type:
        parts.append(f"{skin_type} 피부")
    if concerns:
        parts.append("고민: " + ", ".join(concerns))
    if category:
        parts.append(f"카테고리: {category}")
    return " / ".join(parts) if parts else "스킨케어 추천"


def blocked_by(avoid_ingredients: list[str], category: str | None) -> list[str]:
    flags, custom = split_avoids(avoid_ingredients)
    reasons = [FLAG_LABELS[f] for f in sorted(flags) if f in FLAG_LABELS]
    if custom:
        reasons.append("기피 성분: " + ", ".join(custom))
    if category:
        reasons.append(f"카테고리: {category}")
    return reasons

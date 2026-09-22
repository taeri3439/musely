import json
from typing import Any, Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import get_settings

CommentaryTrack = Literal["cosmetic", "fragrance"]


class ItemNote(BaseModel):
    item_id: str
    note: str


class CommentaryOut(BaseModel):
    summary: str
    per_item: list[ItemNote]


_client: AsyncAnthropic | None = None


def _client_once() -> AsyncAnthropic:
    global _client
    if _client is None:
        s = get_settings()
        if not s.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY가 비어 있다.")
        _client = AsyncAnthropic(api_key=s.anthropic_api_key)
    return _client


SYSTEM_COSMETIC = """당신은 화장품 추천 이유를 짧게 씁니다. JSON만 출력하세요.
키는 summary, per_item (item_id, note)입니다.

- per_item 개수는 후보 개수와 같아야 합니다. 목록의 item_id를 전부 쓰고, 없는 id는 쓰지 마세요.
- note는 한 문장입니다. 제품명·브랜드명을 다시 쓰지 마세요.
- 근거는 후보의 key_ingredients, actives, category와 프로필의 피부 타입·고민·기피·현재 사용 성분만 쓰세요.
- 효능 표현은 "~에 맞을 수 있어요", "도움될 수 있어요"만 쓰세요.
- 쓰지 말 것: 효과적입니다, 적합합니다, 추천합니다, 좋습니다, 루틴, 완벽, 최고.
- summary는 2~3문장입니다. 고른 기준(피부 타입, 고민, 기피)만 말하고 제품을 나열하지 마세요.
- cautions에 없는 주의사항은 만들지 마세요.
- 후보 목록에 없는 제품명을 절대 언급하지 마세요.
"""

SYSTEM_FRAGRANCE = """당신은 향수 추천 이유를 짧게 씁니다. JSON만 출력하세요.
키는 summary, per_item (item_id, note)입니다.

- per_item 개수는 후보 개수와 같아야 합니다. 목록의 item_id를 전부 쓰고, 없는 id는 쓰지 마세요.
- note는 한 문장입니다. 제품명·브랜드명을 다시 쓰지 마세요.
- 근거는 후보의 note_family, top, heart, base 노트와 프로필의 선호 계열·사용 상황(occasion)만 쓰세요.
- 향·분위기 표현은 "~느껴질 수 있어요", "~분위기에 맞을 수 있어요", "~에 어울릴 수 있어요"만 쓰세요.
- 피부·성분·자외선·트러블 등 화장품/스킨케어 주제는 쓰지 마세요.
- 쓰지 말 것: 효과적입니다, 적합합니다, 추천합니다, 좋습니다, 최고, 완벽, 중독, 반드시.
- summary는 2~3문장입니다. 선호 계열·사용 상황 기준만 말하고 제품을 나열하지 마세요.
- 후보 목록에 없는 제품명을 절대 언급하지 마세요.
"""


def _system_for(track: CommentaryTrack) -> str:
    return SYSTEM_FRAGRANCE if track == "fragrance" else SYSTEM_COSMETIC


def _cosmetic_payload(candidates: list[dict[str, Any]], profile: dict[str, Any], cautions: list) -> dict:
    return {
        "track": "cosmetic",
        "profile": {
            "skin_type": profile.get("skin_type"),
            "concerns": profile.get("concerns") or [],
            "avoid_ingredients": profile.get("avoid_ingredients") or [],
            "current_actives": profile.get("current_actives") or [],
        },
        "candidates": [
            {
                "item_id": c["item_id"],
                "name": c["name"],
                "brand": c["brand"],
                "category": c.get("category"),
                "key_ingredients": c.get("key_ingredients") or [],
                "actives": c.get("actives") or [],
            }
            for c in candidates
        ],
        "cautions": cautions,
    }


def _fragrance_payload(candidates: list[dict[str, Any]], profile: dict[str, Any]) -> dict:
    rows = []
    for c in candidates:
        notes = c.get("notes") or {}
        rows.append(
            {
                "item_id": c["item_id"],
                "name": c["name"],
                "brand": c["brand"],
                "note_family": notes.get("family") or "",
                "top": list(notes.get("top") or []),
                "heart": list(notes.get("heart") or []),
                "base": list(notes.get("base") or []),
            }
        )
    return {
        "track": "fragrance",
        "profile": {
            "preferred_scent_families": profile.get("preferred_scent_families") or [],
            "occasion": profile.get("occasion"),
        },
        "candidates": rows,
    }


async def generate_commentary(
    *,
    candidates: list[dict[str, Any]],
    cautions: list,
    profile: dict[str, Any],
    track: CommentaryTrack = "cosmetic",
) -> CommentaryOut:
    if track == "fragrance":
        payload = _fragrance_payload(candidates, profile)
    else:
        payload = _cosmetic_payload(candidates, profile, cautions)

    n = len(candidates)
    user = (
        f"후보는 {n}개입니다. per_item도 {n}개여야 하고 item_id는 아래 목록과 같아야 합니다.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    msg = await _client_once().messages.create(
        model=get_settings().llm_model,
        max_tokens=1024,
        system=_system_for(track),
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("LLM 응답에 JSON이 없다")
    return CommentaryOut.model_validate_json(text[start : end + 1])

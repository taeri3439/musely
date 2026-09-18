import json
from anthropic import AsyncAnthropic
from pydantic import BaseModel
from app.config import get_settings
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

SYSTEM = """당신은 화장품 추천 이유를 짧게 씁니다. JSON만 출력하세요.
키는 summary, per_item (item_id, note)입니다.

- per_item 개수는 후보 개수와 같아야 합니다. 목록의 item_id를 전부 쓰고, 없는 id는 쓰지 마세요.
- note는 한 문장입니다. 제품명을 다시 쓰지 마세요.
- 근거는 후보의 key_ingredients, actives, category와 프로필의 피부 타입·고민·기피만 쓰세요.
- 효능은 "~에 맞을 수 있어요", "도움될 수 있어요"만 쓰세요.
- 쓰지 말 것: 효과적입니다, 적합합니다, 추천합니다, 좋습니다, 루틴.
- summary는 2~3문장입니다. 고른 기준(피부 타입, 고민, 기피)만 말하고 제품을 나열하지 마세요.
- cautions에 없는 주의사항은 만들지 마세요.
- 후보 목록에 없는 제품명을 절대 언급하지 마세요.
"""

async def generate_commentary(*, candidates, cautions, profile) -> CommentaryOut:
    payload = {
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
    n = len(candidates)
    user = (
        f"후보는 {n}개입니다. per_item도 {n}개여야 하고 item_id는 아래 목록과 같아야 합니다.\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    msg = await _client_once().messages.create(
        model=get_settings().llm_model,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
    )
    text = msg.content[0].text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("LLM 응답에 JSON이 없다")
    return CommentaryOut.model_validate_json(text[start : end + 1])
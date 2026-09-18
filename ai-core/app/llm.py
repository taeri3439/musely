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

SYSTEM = """당신은 화장품 추천 이유를 짧게 씁니다.
- 아래 후보 목록에 없는 제품명을 절대 언급하지 마세요.
- 효능은 단정하지 말고 "~에 도움될 수 있어요" 수준으로 표현하세요.
- 주의사항은 제공된 caution 목록에 있는 것만 말하세요.
- JSON만 출력하세요. 키는 summary, per_item (item_id, note).
"""

async def generate_commentary(*, candidates, cautions, profile) -> CommentaryOut:
    payload = {
        "profile": {
            "skin_type": profile.get("skin_type"),
            "concerns": profile.get("concerns") or [],
            "avoid_ingredients": profile.get("avoid_ingredients") or [],
        },
        "candidates": [
            {"item_id": c["item_id"], "name": c["name"], "brand": c["brand"], "category": c.get("category")}
            for c in candidates
        ],
        "cautions": cautions,
    }
    msg = await _client_once().messages.create(
        model=get_settings().llm_model,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
    )
    text = msg.content[0].text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("LLM 응답에 JSON이 없다")
    return CommentaryOut.model_validate_json(text[start : end + 1])
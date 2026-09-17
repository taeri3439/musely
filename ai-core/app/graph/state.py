class CurationState(TypedDict):
    profile: dict
    track: str                    # 지금은 "cosmetic"만
    candidates: list[dict]        # item_id, name, brand, score, category, actives, note
    cautions: list[dict]
    relaxation_level: int
    blocked_by: list[str]
    summary: str
    trace: list[dict]
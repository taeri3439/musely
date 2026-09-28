"""화장품·향수·FAQ jsonl을 Chroma에 색인한다.

실행 (ai-core 디렉터리에서):
    python -m app.retrieval.index
"""

from __future__ import annotations

from app.qna.store import FaqStore
from app.retrieval.store import CosmeticStore, FragranceStore


def main() -> None:
    cosmetic = CosmeticStore()
    n_cos = cosmetic.rebuild()
    fragrance = FragranceStore()
    n_frag = fragrance.rebuild()
    faq = FaqStore()
    n_faq = faq.rebuild()
    print(
        f"indexed {n_cos} cosmetics → {cosmetic.collection().count()} in chroma, "
        f"{n_frag} fragrances → {fragrance.collection().count()} in chroma, "
        f"{n_faq} faq → {faq.collection().count()} in chroma"
    )


if __name__ == "__main__":
    main()

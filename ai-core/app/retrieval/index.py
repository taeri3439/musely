"""화장품 jsonl을 Chroma에 색인한다.

실행 (ai-core 디렉터리에서):
    python -m app.retrieval.index
"""

from __future__ import annotations

from app.retrieval.store import CosmeticStore


def main() -> None:
    store = CosmeticStore()
    n = store.rebuild()
    print(f"indexed {n} cosmetics → {store.collection().count()} in chroma")


if __name__ == "__main__":
    main()

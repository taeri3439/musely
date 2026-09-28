"""FAQ Chroma 색인. 답이 2~3문장이라 청킹하지 않고 1문항 = 1벡터로 넣는다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from app.config import BASE_DIR, Settings, get_settings
from app.retrieval.store import _distance_to_score, _EmbeddingClient, chroma_dir

COLLECTION_FAQ = "faq"
FAQ_PATH = BASE_DIR / "data" / "faq.jsonl"


@dataclass
class FaqHit:
    row: dict[str, Any]
    score: float


def load_faq(path: Path = FAQ_PATH) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["id"]] = row
    return rows


def embed_faq_text(row: dict[str, Any]) -> str:
    # 답까지 넣어야 질문 문장이 달라도(패러프레이즈) 내용으로 걸린다.
    return (
        f"질문: {row['question']}\n"
        f"태그: {', '.join(row.get('tags') or [])}\n"
        f"답: {row['answer']}"
    )


class FaqStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.catalog = load_faq()
        self._client = chromadb.PersistentClient(path=str(chroma_dir(self.settings)))
        self._embed = _EmbeddingClient(self.settings)

    def collection(self):
        return self._client.get_or_create_collection(
            name=COLLECTION_FAQ,
            metadata={"hnsw:space": "cosine"},
        )

    def rebuild(self) -> int:
        try:
            self._client.delete_collection(COLLECTION_FAQ)
        except Exception:  # noqa: BLE001
            pass
        col = self.collection()
        rows = list(self.catalog.values())
        texts = [embed_faq_text(r) for r in rows]
        col.add(
            ids=[r["id"] for r in rows],
            documents=texts,
            embeddings=self._embed.embed(texts),
            metadatas=[{"topic": r.get("topic") or ""} for r in rows],
        )
        return len(rows)

    def count(self) -> int:
        return self.collection().count()

    def search(self, question: str, *, k: int = 3) -> list[FaqHit]:
        query_emb = self._embed.embed([question], task="RETRIEVAL_QUERY")[0]
        n = min(k, max(self.count(), 1))
        raw = self.collection().query(query_embeddings=[query_emb], n_results=n)
        ids = (raw.get("ids") or [[]])[0]
        distances = (raw.get("distances") or [[]])[0]
        return [
            FaqHit(row=self.catalog[i], score=_distance_to_score(d))
            for i, d in zip(ids, distances)
            if i in self.catalog
        ]

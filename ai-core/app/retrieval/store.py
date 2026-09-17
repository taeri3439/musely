"""Chroma persist 스토어.

메타데이터에는 불리언·문자열만 넣는다. 전성분 리스트는 jsonl 카탈로그에 두고
검색 후 item_id로 붙여서 후처리한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from openai import OpenAI

from app.config import BASE_DIR, Settings, get_settings
from app.ssl_setup import configure_ssl
from app.retrieval.filters import (
    blocked_by,
    build_query_text,
    post_filter,
    relaxation_chain,
)

configure_ssl()

COLLECTION = "cosmetics"
PRODUCTS_PATH = BASE_DIR / "data" / "products.jsonl"


@dataclass
class SearchHit:
    product: dict[str, Any]
    score: float  # 0~100. 화면 게이지용. cosine 거리를 변환한다.


@dataclass
class SearchResult:
    hits: list[SearchHit]
    relaxation_level: int
    blocked_by: list[str]


def chroma_dir(settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = Path(settings.chroma_path)
    return path if path.is_absolute() else BASE_DIR / path


def load_catalog(path: Path = PRODUCTS_PATH) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        catalog[row["item_id"]] = row
    return catalog


def embed_text(product: dict[str, Any]) -> str:
    keys = ", ".join(product.get("key_ingredients") or [])
    return (
        f"{product['name']} / {product['brand']} / {product['category']}\n"
        f"주요 성분: {keys}\n"
        f"{product.get('description', '')}"
    )


def metadata_of(product: dict[str, Any]) -> dict[str, Any]:
    # Chroma는 list를 거절한다. 필터에 쓸 값만 스칼라로 넣는다.
    return {
        "name": product["name"],
        "brand": product["brand"],
        "category": product["category"],
        "alcohol_free": bool(product["alcohol_free"]),
        "fragrance_free": bool(product["fragrance_free"]),
        "paraben_free": bool(product["paraben_free"]),
        "essential_oil_free": bool(product["essential_oil_free"]),
    }


class CosmeticStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if self.settings.embedding_provider not in ("openai", "gemini"):
            raise RuntimeError(
                "Anthropic은 임베딩 API가 없다. EMBEDDING_PROVIDER는 openai 또는 gemini."
            )
        self.catalog = load_catalog()
        self._client = chromadb.PersistentClient(path=str(chroma_dir(self.settings)))
        self._openai: OpenAI | None = None
        self._gemini = None
        if self.settings.embedding_provider == "openai":
            self._openai = OpenAI(api_key=self.settings.require_openai_key())
        else:
            from google import genai
            from google.genai import types

            import certifi

            self._gemini = genai.Client(
                api_key=self.settings.require_gemini_key(),
                http_options=types.HttpOptions(
                    client_args={"verify": certifi.where()},
                ),
            )

    def collection(self):
        return self._client.get_or_create_collection(
            name=COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )

    def embed(self, texts: list[str], *, task: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        if self.settings.embedding_provider == "openai":
            assert self._openai is not None
            resp = self._openai.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
            )
            return [item.embedding for item in resp.data]

        from google.genai import types

        assert self._gemini is not None
        resp = self._gemini.models.embed_content(
            model=self.settings.embedding_model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task,
                output_dimensionality=768,
            ),
        )
        if not resp.embeddings:
            raise RuntimeError("Gemini 임베딩 응답이 비어 있다.")
        return [list(item.values or []) for item in resp.embeddings]

    def rebuild(self) -> int:
        """카탈로그 전체를 다시 넣는다. 12~150건 규모라 증분 업데이트보다 이게 안전하다."""
        try:
            self._client.delete_collection(COLLECTION)
        except Exception:  # noqa: BLE001 — 없으면 그냥 만들면 된다
            pass
        col = self.collection()
        products = list(self.catalog.values())
        texts = [embed_text(p) for p in products]
        col.add(
            ids=[p["item_id"] for p in products],
            documents=texts,
            embeddings=self.embed(texts),
            metadatas=[metadata_of(p) for p in products],
        )
        return len(products)

    def count(self) -> int:
        return self.collection().count()

    def search(
        self,
        *,
        skin_type: str | None = None,
        concerns: list[str] | None = None,
        avoid_ingredients: list[str] | None = None,
        category: str | None = None,
        k: int = 5,
    ) -> SearchResult:
        avoid = avoid_ingredients or []
        query = build_query_text(skin_type=skin_type, concerns=concerns or [], category=category)
        query_emb = self.embed([query], task="RETRIEVAL_QUERY")[0]
        col = self.collection()
        fetch = min(max(k * 4, 12), max(self.count(), 1))

        last_level = 0
        for level, where, _flags, custom in relaxation_chain(avoid, category):
            last_level = level
            kwargs: dict[str, Any] = {
                "query_embeddings": [query_emb],
                "n_results": fetch,
            }
            if where:
                kwargs["where"] = where
            raw = col.query(**kwargs)
            ids = (raw.get("ids") or [[]])[0]
            distances = (raw.get("distances") or [[]])[0]
            products = [self.catalog[i] for i in ids if i in self.catalog]
            kept = post_filter(products, custom)
            if kept:
                id_to_dist = {i: d for i, d in zip(ids, distances)}
                hits = [
                    SearchHit(product=p, score=_distance_to_score(id_to_dist[p["item_id"]]))
                    for p in kept[:k]
                ]
                return SearchResult(hits=hits, relaxation_level=level, blocked_by=[])

        return SearchResult(
            hits=[],
            relaxation_level=2,
            blocked_by=blocked_by(avoid, category),
        )


def _distance_to_score(distance: float) -> float:
    """cosine distance 0(같음)~2(반대)를 100~0에 가깝게 접는다."""
    similarity = max(0.0, min(1.0, 1.0 - float(distance)))
    return round(similarity * 100, 1)

"""Retrieval 평가 — Recall@K, Hit@K, must_include / must_exclude.

`data/eval_retrieval.jsonl` 한 줄 = 케이스. 서버 불필요.

실행 (ai-core 디렉터리):
    python -m scripts.eval_recall
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import BASE_DIR
from app.retrieval.store import CosmeticStore, FragranceStore, SearchResult

EVAL_PATH = BASE_DIR / "data" / "eval_retrieval.jsonl"


@dataclass
class CaseResult:
    case_id: str
    ok: bool
    top_k: list[str]
    relaxation: int
    recall_at_k: float | None = None
    hit_at_k: bool | None = None
    errors: list[str] = field(default_factory=list)


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(json.loads(line))
    return cases


def _resolve_impossible_avoid(case: dict[str, Any], store: CosmeticStore) -> dict[str, Any]:
    """cos_impossible_avoid: 카탈로그에서 살아남은 제품의 첫 전성분을 전부 기피."""
    query = dict(case.get("query") or {})
    avoid = list(query.get("avoid_ingredients") or [])
    if "__dynamic_all_ingredients__" not in avoid:
        return query
    flags = ("alcohol_free", "fragrance_free", "paraben_free", "essential_oil_free")
    remaining = [p for p in store.catalog.values() if all(p.get(f) for f in flags)]
    extra = [p["ingredients"][0] for p in remaining if p.get("ingredients")]
    avoid = [a for a in avoid if a != "__dynamic_all_ingredients__"] + extra
    query["avoid_ingredients"] = avoid
    return query


def _search_cosmetic(store: CosmeticStore, case: dict[str, Any]) -> SearchResult:
    query = _resolve_impossible_avoid(case, store)
    k = store.count() if case.get("use_catalog_k") else int(case.get("k") or 5)
    return store.search(
        skin_type=query.get("skin_type"),
        concerns=query.get("concerns") or [],
        avoid_ingredients=query.get("avoid_ingredients") or [],
        category=query.get("category"),
        k=max(k, 1),
    )


def _search_fragrance(store: FragranceStore, case: dict[str, Any]) -> SearchResult:
    query = case.get("query") or {}
    k = int(case.get("k") or 5)
    return store.search(
        preferred_scent_families=query.get("preferred_scent_families") or [],
        occasion=query.get("occasion"),
        k=k,
    )


def _recall_at_k(relevant: list[str], top_k: list[str]) -> tuple[float, bool]:
    rel = set(relevant)
    if not rel:
        return 0.0, False
    hit = rel & set(top_k)
    recall = len(hit) / len(rel)
    hit_at_k = len(hit) > 0
    return recall, hit_at_k


def _eval_case(
    case: dict[str, Any],
    cos_store: CosmeticStore,
    frag_store: FragranceStore,
) -> CaseResult:
    case_id = case["id"]
    track = case["track"]
    errors: list[str] = []

    if track == "cosmetic":
        result = _search_cosmetic(cos_store, case)
    elif track == "fragrance":
        result = _search_fragrance(frag_store, case)
    else:
        return CaseResult(case_id, False, [], 0, errors=[f"unknown track: {track}"])

    top_k = [h.product["item_id"] for h in result.hits]
    relaxation = result.relaxation_level

    recall: float | None = None
    hit: bool | None = None
    relevant = case.get("relevant") or []
    if relevant:
        recall, hit = _recall_at_k(relevant, top_k)

    for item_id in case.get("must_include") or []:
        if item_id not in top_k:
            errors.append(f"must_include {item_id} not in top-{len(top_k) or '0'}")

    for item_id in case.get("must_exclude") or []:
        if item_id in top_k:
            errors.append(f"must_exclude {item_id} appeared in top-{len(top_k)}")

    if case.get("expect_empty"):
        if top_k:
            errors.append(f"expected empty, got {top_k}")
    else:
        min_hits = case.get("expect_min_hits")
        if min_hits is not None and len(top_k) < min_hits:
            errors.append(f"expected >= {min_hits} hits, got {len(top_k)}")

    exp_relax = case.get("expect_relaxation")
    if exp_relax is not None and relaxation != exp_relax:
        errors.append(f"expected relaxation {exp_relax}, got {relaxation}")

    if case.get("expect_blocked_by") and not result.blocked_by:
        errors.append("expected blocked_by non-empty")

    return CaseResult(
        case_id=case_id,
        ok=not errors,
        top_k=top_k,
        relaxation=relaxation,
        recall_at_k=recall,
        hit_at_k=hit,
        errors=errors,
    )


def main() -> int:
    if not EVAL_PATH.is_file():
        print(f"eval file missing: {EVAL_PATH}", file=sys.stderr)
        return 1

    cos_store = CosmeticStore()
    frag_store = FragranceStore()
    if cos_store.count() == 0:
        print("cosmetic 인덱스 rebuild...")
        cos_store.rebuild()
    if frag_store.count() == 0:
        print("fragrance 인덱스 rebuild...")
        frag_store.rebuild()

    cases = _load_cases(EVAL_PATH)
    results: list[CaseResult] = []
    recalls: list[float] = []

    print(f"cases: {len(cases)}  eval={EVAL_PATH.name}\n")

    for case in cases:
        r = _eval_case(case, cos_store, frag_store)
        results.append(r)
        line = f"[{'OK' if r.ok else 'FAIL'}] {r.case_id}  k={len(r.top_k)}  relax={r.relaxation}"
        if r.recall_at_k is not None:
            line += f"  Recall@{len(r.top_k) or case.get('k', 5)}={r.recall_at_k:.3f}  Hit@K={r.hit_at_k}"
            recalls.append(r.recall_at_k)
        line += f"  ids={r.top_k[:8]}{'…' if len(r.top_k) > 8 else ''}"
        print(line)
        for err in r.errors:
            print(f"    - {err}")

    failed = [r for r in results if not r.ok]
    macro_recall = sum(recalls) / len(recalls) if recalls else None

    print()
    if macro_recall is not None:
        print(f"macro Recall@K (케이스 {len(recalls)}개, relevant 정의된 것만): {macro_recall:.3f}")
    print(f"pass {len(results) - len(failed)}/{len(results)}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

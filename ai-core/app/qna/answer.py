"""QnA 파이프라인 — 의도 분기 → (규칙 | FAQ 검색) → 근거 안에서만 답한다.

추천 요청은 여기서 답하지 않는다. 추천 목록은 job 파이프라인 하나만 만든다.
성분 조합 질문은 LLM 없이 conflict_rules.yaml로 답한다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from app.graph.agents.conflict_checker import ACTIVE_ALIASES, _to_caution, load_rules
from app.llm import generate_qna_answer
from app.qna.store import FaqHit, FaqStore

logger = logging.getLogger(__name__)

# eval_qna로 맞춘 값(관련 FAQ 최저 74.5, 범위 밖 최고 57.9의 중간).
# FAQ가 늘거나 임베딩 모델을 바꾸면 다시 맞춘다.
UNKNOWN_BELOW = 66.0
DIRECT_ABOVE = 88.0

QNA_ALIASES: dict[str, list[str]] = {
    **ACTIVE_ALIASES,
    "비타민씨": ["vitamin_c"],
    "vitamin c": ["vitamin_c"],
    "아스코빅": ["vitamin_c"],
    "글리콜산": ["aha"],
    "젖산": ["aha"],
    "살리실산": ["bha"],
    "bpo": ["benzoyl_peroxide"],
    "벤조일 퍼옥사이드": ["benzoyl_peroxide"],
}

_RECOMMEND = re.compile(
    r"추천\s*(해|좀|부탁|받)|골라\s*(줘|주)|뭐\s*(써|사|바르)|뭘\s*(써|사|바르)"
    r"|어떤\s*제품|제품\s*(알려|추천)|살까|사야\s*(돼|해|할)"
)
_CO_USE = re.compile(r"같이|함께|섞|동시|충돌|궁합|겹쳐|레이어링")

RECOMMEND_ANSWER = (
    "제품 추천은 [추천 받기]에서 피부 타입과 고민을 입력하면 조건에 맞춰 골라 드려요. "
    "여기서는 성분이나 사용법에 대한 궁금증을 도와드릴게요."
)
UNKNOWN_ANSWER = (
    "그 질문은 제가 가진 정보로는 정확히 답하기 어려워요. "
    "성분, 사용 순서, 향수 노트처럼 조금 더 구체적으로 물어봐 주시면 찾아볼게요."
)


@dataclass
class QnaAnswer:
    intent: str
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    cautions: list[dict[str, Any]] = field(default_factory=list)
    redirect: str | None = None
    used_llm: bool = False


_store: FaqStore | None = None


def get_faq_store() -> FaqStore:
    global _store
    if _store is None:
        _store = FaqStore()
    return _store


def detect_actives(question: str) -> set[str]:
    compact = question.lower().replace(" ", "")
    keys: set[str] = set()
    for alias, mapped in QNA_ALIASES.items():
        if alias.replace(" ", "") in compact:
            keys.update(mapped)
    return keys


def classify(question: str) -> str:
    if _RECOMMEND.search(question):
        return "recommend"
    if len(detect_actives(question)) >= 2 and _CO_USE.search(question):
        return "pair"
    return "faq"


def _answer_pair(question: str) -> QnaAnswer:
    labels, rules = load_rules()
    actives = detect_actives(question)
    wanted = {frozenset(p) for p in combinations(sorted(actives), 2)}
    matched = [r for r in rules if frozenset(r["pair"]) in wanted]

    if not matched:
        names = "·".join(labels.get(k, k) for k in sorted(actives))
        return QnaAnswer(
            intent="pair",
            answer=(
                f"{names} 조합은 등록된 주의 규칙이 없어요. "
                "사용 중 따가움이나 붉어짐이 느껴지면 사용을 멈추고 시간을 나눠 써 보세요."
            ),
        )

    cautions = [_to_caution(r, labels) for r in matched]
    lines = [f"{'·'.join(c['pair_labels'])}: {c['message']}" for c in cautions]
    sources = [
        {
            "kind": "rule",
            "id": r["id"],
            "title": "·".join(labels.get(k, k) for k in r["pair"]),
            "source": r["source"],
            "confidence": r["confidence"],
        }
        for r in matched
    ]
    return QnaAnswer(intent="pair", answer="\n".join(lines), sources=sources, cautions=cautions)


def _faq_source(hit: FaqHit) -> dict[str, Any]:
    return {
        "kind": "faq",
        "id": hit.row["id"],
        "title": hit.row["question"],
        "source": hit.row.get("source") or "",
        "score": hit.score,
    }


async def _answer_faq(question: str, *, use_llm: bool) -> QnaAnswer:
    hits = await asyncio.to_thread(get_faq_store().search, question, k=3)
    relevant = [h for h in hits if h.score >= UNKNOWN_BELOW]
    if not relevant:
        return QnaAnswer(intent="unknown", answer=UNKNOWN_ANSWER)

    top = relevant[0]
    fallback = QnaAnswer(intent="faq", answer=top.row["answer"], sources=[_faq_source(top)])
    if not use_llm or top.score >= DIRECT_ABOVE:
        return fallback

    try:
        out = await generate_qna_answer(
            question=question,
            snippets=[
                {"id": h.row["id"], "question": h.row["question"], "answer": h.row["answer"]}
                for h in relevant
            ],
        )
    except Exception:
        logger.exception("qna LLM 실패, FAQ 원문으로 폴백")
        return fallback

    by_id = {h.row["id"]: h for h in relevant}
    used = [by_id[i] for i in out.used_ids if i in by_id]
    if not out.answer.strip() or not used:
        return fallback
    return QnaAnswer(
        intent="faq",
        answer=out.answer.strip(),
        sources=[_faq_source(h) for h in used],
        used_llm=True,
    )


async def answer_question(question: str, *, use_llm: bool = True) -> QnaAnswer:
    intent = classify(question)
    if intent == "recommend":
        return QnaAnswer(intent="recommend", answer=RECOMMEND_ANSWER, redirect="recommend")
    if intent == "pair":
        return _answer_pair(question)
    return await _answer_faq(question, use_llm=use_llm)

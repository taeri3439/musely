"""QnA 평가 — 의도 정확도, 근거(top-1) 정확도, FAQ Hit@3.

LLM은 끄고 돌린다(의도 분기·검색·임계값만 본다). FAQ 인덱스가 없으면 만든다.

실행 (ai-core):
    python -m scripts.eval_qna
"""

from __future__ import annotations

import asyncio
import json
import sys

from app.config import BASE_DIR
from app.qna.answer import DIRECT_ABOVE, UNKNOWN_BELOW, answer_question, get_faq_store

EVAL_PATH = BASE_DIR / "data" / "eval_qna.jsonl"


def _load() -> list[dict]:
    return [
        json.loads(line)
        for line in EVAL_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def main() -> int:
    store = get_faq_store()
    if store.count() == 0:
        print("faq 인덱스 rebuild...")
        store.rebuild()

    cases = _load()
    intent_ok = 0
    source_total = source_ok = 0
    hit3_total = hit3_ok = 0
    failed: list[str] = []

    print(f"cases: {len(cases)}  unknown<{UNKNOWN_BELOW}  direct>={DIRECT_ABOVE}\n")

    for case in cases:
        q = case["question"]
        out = await answer_question(q, use_llm=False)
        top_source = out.sources[0]["id"] if out.sources else None
        errors: list[str] = []

        if out.intent == case["expect_intent"]:
            intent_ok += 1
        else:
            errors.append(f"intent {out.intent} != {case['expect_intent']}")

        expected = case.get("expect_source")
        if expected:
            source_total += 1
            if top_source == expected:
                source_ok += 1
            else:
                errors.append(f"source {top_source} != {expected}")

        # 검색 점수는 의도와 상관없이 찍어 둔다. 임계값을 맞출 때 이 숫자를 본다.
        hits = await asyncio.to_thread(store.search, q, k=3)
        hit_ids = [h.row["id"] for h in hits]
        top_score = hits[0].score if hits else 0.0
        if case["expect_intent"] == "faq" and expected:
            hit3_total += 1
            if expected in hit_ids:
                hit3_ok += 1

        mark = "OK" if not errors else "FAIL"
        print(f"[{mark}] {out.intent:9} top={top_score:5.1f} src={top_source}  {q}")
        for e in errors:
            print(f"    - {e}")
        if errors:
            failed.append(q)

    print()
    print(f"intent accuracy : {intent_ok}/{len(cases)}")
    print(f"source top-1    : {source_ok}/{source_total}")
    print(f"faq Hit@3       : {hit3_ok}/{hit3_total}")
    print(f"pass {len(cases) - len(failed)}/{len(cases)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""주간 회귀 — retrieval → graph → job API 순서.

실행 (ai-core):
    python -m scripts.run_weekly_checks
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]

STEPS = [
    ("scripts.eval_recall", "Retrieval Recall@K"),
    ("scripts.eval_qna", "QnA 의도·근거 정확도"),
    ("scripts.check_graph", "LangGraph cosmetic/fragrance/both"),
    ("scripts.e2e_jobs", "POST/GET /jobs E2E"),
]


def _run(module: str) -> int:
    return subprocess.call([sys.executable, "-m", module], cwd=BASE)


def main() -> int:
    failed: list[str] = []
    for module, label in STEPS:
        print(f"\n{'=' * 60}\n▶ {label}  ({module})\n{'=' * 60}")
        code = _run(module)
        if code != 0:
            failed.append(module)
    print(f"\n{'=' * 60}")
    if failed:
        print(f"실패: {', '.join(failed)}")
        return 1
    print("주간 검사 모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""계약 스키마와 mock fixture가 서로 맞는지 확인한다.

서버를 띄우지 않고 돌아가므로 fixture나 규칙 파일을 손볼 때마다 먼저 이걸 돌리면 된다.
출력된 JSON이 백엔드가 실제로 받는 모양(camelCase)이다.

실행:
    python -m scripts.check_contract
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from app.config import get_settings
from app.schemas import JobStatusResponse, JobStatus, OrchestrateRequest, OrchestrateResult

BASE_DIR = Path(__file__).resolve().parents[1]
FIXTURE_DIR = BASE_DIR / "mock" / "fixtures"
RULES_PATH = BASE_DIR / "data" / "conflict_rules.yaml"


def load_rules() -> tuple[dict[str, str], dict[str, dict]]:
    raw = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    labels: dict[str, str] = raw.get("labels", {})
    rules = {r["id"]: r for r in raw.get("rules", [])}
    return labels, rules


def check_rules(labels: dict[str, str], rules: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    for rule_id, rule in rules.items():
        for key in rule["pair"]:
            if key not in labels:
                problems.append(f"conflict_rules.yaml: 규칙 {rule_id}의 '{key}'에 labels 항목이 없다")
    print(f"  OK  conflict_rules.yaml    규칙 {len(rules)}건 / 라벨 {len(labels)}개")
    return problems


def check_fixtures(labels: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        try:
            result = OrchestrateResult.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 — 어떤 검증 실패든 그대로 보여주면 된다
            problems.append(f"{path.name}: {exc}")
            continue

        # 계약이 아니라 제품 규칙: 추천 이유가 빠지면 화면 3의 차별점이 사라진다.
        for candidate in [*result.cosmetic, *result.fragrance]:
            if not candidate.note.strip():
                problems.append(f"{path.name}: {candidate.item_id}에 note(추천 이유)가 없다")

        # 향수 후보는 노트 피라미드를 채워야 화면 3의 향수 카드가 그려진다.
        for candidate in result.fragrance:
            if candidate.notes is None:
                problems.append(f"{path.name}: {candidate.item_id}에 notes가 없다")

        # pairLabels가 규칙 파일의 labels와 어긋나면 화면과 데이터가 따로 논다.
        for caution in result.cautions:
            if len(caution.pair) != len(caution.pair_labels):
                problems.append(f"{path.name}: pair와 pairLabels 길이가 다르다 ({caution.pair})")
                continue
            for key, label in zip(caution.pair, caution.pair_labels):
                expected = labels.get(key)
                if expected is None:
                    problems.append(f"{path.name}: '{key}'가 conflict_rules.yaml labels에 없다")
                elif expected != label:
                    problems.append(
                        f"{path.name}: '{key}' 라벨 불일치 — fixture '{label}' vs 규칙 '{expected}'"
                    )

        print(f"  OK  {path.name:22} "
              f"화장품 {len(result.cosmetic)}건 / 향수 {len(result.fragrance)}건 / "
              f"주의 {len(result.cautions)}건 / relaxation {result.relaxation_level}")
    return problems


def print_sample_wire_format() -> None:
    """백엔드에게 보여줄 실제 응답 모양."""
    request = OrchestrateRequest(
        profile_id="pf_1",
        track="cosmetic",
        skin_type="combination",
        concerns=["모공", "트러블"],
        avoid_ingredients=["알코올"],
        current_actives=["레티놀"],
    )
    print("\n[요청 본문]")
    print(json.dumps(request.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))

    response = JobStatusResponse(
        job_id="mock_0123456789ab",
        status=JobStatus.DONE,
        result=OrchestrateResult.model_validate(
            json.loads((FIXTURE_DIR / "cosmetic_only.json").read_text(encoding="utf-8"))
        ),
        elapsed_ms=5120,
    )
    print("\n[응답 본문 — steps는 생략]")
    print(json.dumps(response.model_dump(mode="json", by_alias=True), ensure_ascii=False, indent=2))


def print_settings() -> None:
    """.env가 실제로 읽히는지 확인. 키 값은 있는지 여부만 찍는다."""
    s = get_settings()
    print(
        f"  .env  APP_ENV={s.app_env} / VECTOR_STORE={s.vector_store} / "
        f"JOB_TIMEOUT={s.job_timeout_seconds}s / "
        f"OPENAI_API_KEY={'설정됨' if s.openai_api_key else '비어 있음 (2주차에 채움)'}"
    )


def main() -> int:
    print(f"검사 대상: {BASE_DIR}")
    print_settings()

    labels, rules = load_rules()
    problems = check_rules(labels, rules)
    problems += check_fixtures(labels)
    print_sample_wire_format()

    if problems:
        print(f"\n문제 {len(problems)}건:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n모두 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

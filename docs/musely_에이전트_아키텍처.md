# musely — 에이전트 아키텍처 흐름

나연 담당 · LangGraph 노드 4개 · 트랙별 조건부 라우팅

> 관련 문서: **ai-core 플랜**(설계 원본), **빌드 플랜**(시스템 경계), **화면별 기능 정의**(진행 단계)

에이전트 4개는 자율 루프가 아니다. **검색 · 규칙 검수 · 설명 생성**으로 책임을 나눈 LangGraph 노드이고, 오케스트레이터가 `track`으로 분기한다.

현재 `app/graph/` 에 화장품 트랙이 있다. 향수 노드와 LLM commentary는 아직 없다.

---

## 00. 시스템에서 에이전트가 도는 위치

호출은 한쪽으로만 흐른다. 프론트는 ai-core를 직접 부르지 않는다.

```
[프론트]  REST 폴링
    │
    ▼
[Spring Boot]  프로필·추천 이력 영속화
    │  POST /jobs → 즉시 202
    │  GET  /jobs/{id} 폴링
    ▼
[ai-core FastAPI]
    │  JobStore (휘발, TTL 30분)
    │  graph.ainvoke()
    ▼
[LangGraph 오케스트레이터]
    ├─ 성분 매칭 ──► Chroma (화장품)
    ├─ 성분 충돌 검수 ──► conflict_rules.yaml
    ├─ 향수 매칭 ──► Chroma (향수)
    └─ 설명 생성 ──► LLM (텍스트만)
```

ai-core는 **프로필 JSON을 받아 추천 JSON을 뱉는 함수**다. 백엔드 DB를 조회하지 않는다.

---

## 01. job이 그래프에 들어가기까지

```
POST /jobs
  → PENDING (접수만, 50ms 미만)
  → BackgroundTasks에서 RUNNING
  → asyncio.wait_for(graph.ainvoke(...), 30s)
       ├─ DONE   후보 0건 포함. 빈 배열 + blockedBy
       └─ FAILED TIMEOUT | LLM_ERROR | INTERNAL
```

후보 0건은 시스템 오류가 아니다. `FAILED`로 주면 화면이 "문제가 생겼어요"로 잘못 분기한다.

`track: "both"`면 그래프를 두 번 병렬 호출한 뒤 결과를 합친다. 계약은 1주차부터 열려 있고, 구현은 단일 트랙이 안정된 뒤(4주차) 한다.

```
if track == "both":
    cosmetic, fragrance = await asyncio.gather(
        graph.ainvoke({..., "track": "cosmetic"}),
        graph.ainvoke({..., "track": "fragrance"}),
    )
    return merge(cosmetic, fragrance)
```

---

## 02. 공유 상태 `CurationState`

노드끼리 주고받는 가방. 각 에이전트는 이 일부를 읽고 일부를 쓴다.

| 필드 | 누가 씀 | 용도 |
|---|---|---|
| `profile` | 시작 시 | 피부 타입, 고민, 기피, 현재 활성 성분, 향 계열 |
| `track` | 시작 시 | `cosmetic` 또는 `fragrance` (`both`는 그래프 밖에서 쪼갬) |
| `candidates` | matcher → checker | 추천 후보 |
| `cautions` | conflict_checker | 성분 조합 주의 |
| `relaxation_level` | matcher | 0=원조건, 1=카테고리 완화, 2=그래도 0건 |
| `blocked_by` | matcher (0건일 때) | 화면에 "뭐가 걸렸는지" |
| `summary` | commentary | 결과 상단 2~3문장 |
| `trace` | 모든 노드 | 소요시간·검색쿼리. 화면 `steps`와는 별개 |

코드: `ai-core/app/graph/state.py`

---

## 03. 트랙별 그래프

```
                    START
                      │
                      ▼
              track으로 분기
             /              \
            ▼                ▼
   ingredient_matcher   scent_matcher
            │                │
            ▼                │
    conflict_checker         │
         /      \            │
   후보 있음   0건이면 END    │
        │                    │
        ▼                    ▼
              commentary
                  │
                 END
```

| track | 경로 |
|---|---|
| `cosmetic` | 성분 매칭 → 충돌 검수 → (후보 있으면) 설명 생성 |
| `fragrance` | 향수 매칭 → 설명 생성 |
| `both` | 위 둘을 병렬 실행 후 merge. 충돌 검수는 화장품 쪽만 |

에이전트는 4개에서 늘리지 않는다. 리랭킹이 필요하면 matcher 안에서 처리한다.

---

## 04. 에이전트별 내부 흐름

### 1) 성분 매칭 `ingredient_matcher`

화장품 트랙의 입구. **하드 제약은 필터, 소프트 선호는 벡터.**

임베딩은 부정을 못 잡는다. "알코올 안 들어간 토너"를 그대로 임베딩하면 알코올이 들어간 토너가 상위에 온다. 기피가 결과에 섞이면 성능 문제가 아니라 버그다.

```
profile
  │
  ├─ 기피 칩(알코올/향료/파라벤/에센셜오일)
  │     → 불리언 플래그 where  (alcohol_free=true 등)
  ├─ 직접 입력 기피 성분
  │     → 검색 후 전성분 문자열 후처리
  │        (Chroma 메타데이터는 리스트 $nin 불가)
  └─ 피부 타입·고민·카테고리
        → 쿼리 텍스트 임베딩 (기피 문구는 넣지 않음)
              │
              ▼
        Chroma cosmetics 검색
              │
         히트 있음? ──yes──► candidates, relaxation_level
              │ no
              ▼
        완화 체인 (카테고리만 품. 기피는 유지)
              │
         그래도 0건 ──► candidates=[], blocked_by
                         commentary는 건너뜀
```

이미 있는 검색 구현은 `app/retrieval/store.py`의 `CosmeticStore.search()` + `filters.py`다. 에이전트 노드는 이 함수를 호출하면 된다.

| | 내용 |
|---|---|
| 입력 | `profile`, `track=cosmetic` |
| 의존 | Chroma 화장품 컬렉션, `filters.build_where` / `relaxation_chain` |
| 출력 | `candidates`, `relaxation_level`, `blocked_by`, `trace` |
| LLM | 쓰지 않음 |

---

### 2) 성분 충돌 검수 `conflict_checker`

화장품 트랙 전용. 후보와 사용자가 지금 쓰는 활성 성분(`current_actives`)을 규칙 테이블로 대조한다. LLM이 아니라 결정론이다.

```
candidates + profile.current_actives
              │
              ▼
     conflict_rules.yaml
     (pair / severity / source / confidence)
              │
              ├─ avoid  → 해당 후보 제외
              └─ caution → 후보는 남기고 cautions에 적재
              │
              ▼
     필터된 candidates + cautions
              │
         후보 남음? ──yes──► commentary
              │ no
              ▼
             END (LLM 호출 없음)
```

규칙 예시: 레티놀+AHA는 `caution`(자극 누적), 레티놀+벤조일퍼옥사이드는 `avoid`. 확신도가 낮은 통설(나이아신아마이드+비타민C)은 `confidence: low`로 두고 화면에서 단정하지 않게 보여 준다.

`Caution.pair`는 규칙 키(`retinol`)라 화면에 그대로 못 쓴다. `pairLabels`는 yaml의 `labels`에서 온다.

| | 내용 |
|---|---|
| 입력 | `candidates`, `profile.current_actives` |
| 의존 | `data/conflict_rules.yaml` |
| 출력 | 필터된 `candidates`, `cautions`, `trace` |
| LLM | 쓰지 않음 |

향수 트랙에는 이 노드가 없다.

---

### 3) 향수 매칭 `scent_matcher`

향수 트랙의 입구. 성분 매칭과 같은 패턴이지만 데이터·필터가 다르다.

```
profile
  │
  ├─ preferred_scent_families → 계열 필터 ($in)
  ├─ occasion                 → 분위기 태그 (소프트)
  └─ 선호 계열·상황 텍스트    → 쿼리 임베딩
              │
              ▼
        Chroma fragrance 검색
              │
         히트 있음? ──yes──► candidates (notes: top/heart/base)
              │ no
              ▼
        완화 체인 (선호 계열을 품. 하드 제약은 유지)
              │
         그래도 0건 ──► candidates=[], blocked_by
                         commentary는 건너뜀
```

충돌 검수는 거치지 않고, 후보가 있으면 바로 설명 생성으로 간다.

| | 내용 |
|---|---|
| 입력 | `profile`, `track=fragrance` |
| 의존 | Chroma 향수 컬렉션 |
| 출력 | `candidates` (`notes` 포함), `relaxation_level`, `blocked_by`, `trace` |
| LLM | 쓰지 않음 |

---

### 4) 설명 생성 `commentary` — 두 트랙 공용

마지막 공통 노드. 이미 고른 후보와 주의사항만 보고 자연어를 붙인다. **제품을 새로 고르지 않는다.**

```
candidates + cautions
              │
              ▼
        LLM structured output
        (gpt-4o-mini / claude-haiku)
              │
              ├─ summary   전체 2~3문장
              └─ per_item  후보별 note 한 줄
              │
              ▼
             END
```

프롬프트 제약 세 줄:

- 아래 후보 목록에 없는 제품명을 절대 언급하지 마세요.
- 효능은 단정하지 말고 "~에 도움될 수 있어요" 수준으로 표현하세요.
- 주의사항은 제공된 caution 목록에 있는 것만 말하세요.

후보가 0건이면 이 노드를 건너뛴다. 없는 제품을 지어내는 최악의 실패를 구조적으로 차단한다.

| | 내용 |
|---|---|
| 입력 | `candidates`, `cautions` |
| 의존 | LLM API (`app/llm.py` 예정) |
| 출력 | `summary`, 항목별 `note`, `trace` |
| LLM | 여기만 씀. 예상 2~4초, 단일 트랙 레이턴시의 대부분 |

---

## 05. 화면 단계와 내부 노드 매핑

프론트 SC-03의 `steps[]`는 에이전트와 1:1이 아니다. 내부 노드명(`ingredient_matcher` 등)을 그대로 노출하지 않는다.

| `StepKey` | 화면 문구 | 실제 노드 | 비고 |
|---|---|---|---|
| `profile` | 프로필 분석 | (별도 에이전트 없음) | job이 돌기 시작했다는 표시 |
| `search` | 조건에 맞는 제품 찾기 | `ingredient_matcher` 또는 `scent_matcher` | 트랙에 따라 갈림 |
| `conflict` | 성분 조합 검수 | `conflict_checker` | 향수 트랙에는 단계 자체가 없음 |
| `commentary` | 추천 이유 작성 | `commentary` | 후보 0건이면 `skipped` |

`CurationState.trace`와 혼동하지 말 것. `trace`는 디버깅용 소요시간·검색쿼리고, `steps`는 화면용이다.

트랙별 단계 (mock `TRACK_STEPS`와 동일):

- cosmetic / both: profile → search → conflict → commentary
- fragrance: profile → search → commentary

---

## 06. 데이터가 에이전트를 어떻게 받치나

```
data/products.jsonl          →  CosmeticsStore 인덱싱  →  성분 매칭
data/fragrances.jsonl        →  FragranceStore 인덱싱  →  향수 매칭
data/conflict_rules.yaml     →  규칙 로드              →  충돌 검수
후보 JSON                    →  LLM 프롬프트           →  설명 생성
```

제품 1건 = 청크 1개. 메타데이터에는 필터용 스칼라만 넣는다 (`alcohol_free`, `category`, `note_family`). 전성분 리스트는 jsonl 카탈로그에 두고 검색 후 `item_id`로 붙여 후처리한다.

---

## 07. 레이턴시에서 어디가 비싼가

| 구간 | 예상 | 담당 |
|---|---|---|
| 쿼리 임베딩 | 100~300ms | matcher |
| 벡터 검색 | 10ms 미만 | matcher |
| 충돌 검수 | 1ms 미만 | conflict_checker |
| 설명 생성 | 2~4초 | commentary |
| 단일 트랙 합계 | 3~5초 | |
| 두 트랙 병렬 | 4~6초 | both |

비용·시간의 거의 전부가 commentary다. 그래서 0건일 때 LLM을 건너뛰는 분기가 레이턴시 방어이기도 하다.

---

## 08. 절대 깨면 안 되는 규칙

1. 기피 성분·알러지 같은 하드 제약은 벡터 유사도가 아니라 **메타데이터 필터**(및 후처리)로 건다.
2. 검색 결과가 0건이면 LLM을 호출하지 않는다.
3. 에이전트는 4개에서 늘리지 않는다.
4. 완화 체인에서 **기피 성분은 어떤 단계에서도 풀지 않는다.**
5. 화면 단계 문구에 내부 노드명을 노출하지 않는다.

면접에서 "에이전트가 어떻게 동작하나요"를 물으면, 자율 에이전트처럼 말하지 말고 **이 책임 분리와 조건부 라우팅**, 그리고 **결정론적으로 둘 곳과 LLM에 맡길 곳을 나눈 판단**을 그대로 설명하면 된다.

---
*musely 에이전트 아키텍처 · 2026-09*

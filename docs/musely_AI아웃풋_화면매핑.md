# musely — AI 아웃풋 ↔ 화면 매핑

화면 기획에서 거꾸로 본, ai-core가 내려줘야 하는 JSON.

> 관련 문서: **기획서**(화면 레이아웃), **화면별 기능 정의**(SC-03·SC-04), **ai-core 플랜**(계약 스키마)

---

## 00. 프론트는 이 JSON을 어디에 넣나

**결과 화면(SC-04)은 `status === "DONE"`일 때 `result` 객체를 필드 그대로 매핑하면 된다.**

폴링이 `DONE`을 주면 백엔드가 그 `result`를 추천 레코드로 저장하고, 프론트는 `GET /api/recommendations/{id}`로 같은 모양을 받는다. 카드·요약·주의사항은 아래 "정상 결과" JSON의 키 이름과 1:1이다.

다만 **진행 화면(SC-03)은 `result`가 아니라 바깥의 `status` + `steps`**를 쓴다. `result`는 끝나기 전에는 `null`이다.

| 화면 | 읽는 JSON | 비고 |
|---|---|---|
| SC-03 진행 | `{ status, steps, error, elapsedMs }` | `result`는 아직 null |
| SC-04 결과 | `{ result }` (`DONE`일 때만) | 아래 정상 결과 JSON |
| SC-03 에러 | `{ status: "FAILED", error }` | `result`는 null |
| SC-04 0건 | `{ result }` 이지만 배열이 비어 있음 | 에러 화면이 아님 |

와이어 포맷은 **camelCase**.

---

## 01. 화면이 AI에게 받는 것

| 화면 | AI가 채울 것 | 안 채울 것 |
|---|---|---|
| SC-03 진행 | `status` + `steps[]` | 내부 노드명, `trace` |
| SC-04 결과 | `result` 전체 | 피드백, 날짜, 히스토리 요약 |
| SC-05 기록 | 없음 (SC-04 재사용) | 목록 카드 문구 |

프로필·피드백·히스토리 저장은 AI 책임이 아니다.

---

## 02. SC-03 — 진행 중 폴링 응답

`GET /jobs/{jobId}` (백엔드 릴레이: `GET /api/recommendations/jobs/{jobId}`)를 1초마다 친다. 단계 표시는 최상단 `steps`에 있어야 한다.

```json
{
  "jobId": "job_9f2c1a7b3e00",
  "status": "RUNNING",
  "steps": [
    { "key": "profile",    "label": "프로필 분석",           "status": "done" },
    { "key": "search",     "label": "조건에 맞는 제품 찾기", "status": "done" },
    { "key": "conflict",   "label": "성분 조합 검수",       "status": "running" },
    { "key": "commentary", "label": "추천 이유 작성",       "status": "pending" }
  ],
  "result": null,
  "error": null,
  "elapsedMs": 4200
}
```

### 화면 규칙

| 필드 | 화면에서 하는 일 |
|---|---|
| `status` | `RUNNING` 단계 UI / `DONE` → 결과로 이동 / `FAILED` → 에러 UI |
| `steps[].label` | **그대로 출력**. 프론트가 번역하지 않음 |
| `steps[].status` | `pending` ○ / `running` ◐ / `done` ✓ / `skipped` 흐리게(체크 없음) |
| `error.code` | `TIMEOUT` / `LLM_ERROR` / `INTERNAL` / `JOB_NOT_FOUND` |

- `conflict`는 향수 전용 트랙이면 `skipped`
- 후보 0건이면 `commentary`도 `skipped`
- `ingredient_matcher` 같은 내부 이름은 절대 노출하지 않음

---

## 03. SC-04 — 정상 결과 (`DONE`) ← 프론트가 카드에 넣는 데이터

기획서 레이아웃을 필드로 뒤집으면 이렇다.

```
복합성 피부에 트러블 고민을 고려해서, …     ← result.summary
⚠ 함께 쓸 때 주의                         ← result.cautions[]  (없으면 영역 숨김)
  레티놀 + AHA/BHA          [주의]        ← pairLabels + severity
  같은 날 밤에 함께 쓰면 …               ← message
  출처: 일반적 스킨케어 가이드라인         ← source (+ confidence)

─── 화장품 ───                            ← result.cosmetic[]
  시카 수딩 토너            ▓▓▓ 86       ← name + score
  브랜드명 · 토너                        ← brand · category
  알코올 무첨가, 진정 성분 위주라 …       ← note  ★필수

─── 향수 ───                              ← result.fragrance[]  (미요청이면 섹션 숨김)
  우디 머스크 오드퍼퓸       ▓▓ 79
  브랜드명 · 우디                        ← brand · notes.family
  탑 / 미들 / 베이스                     ← notes.top / heart / base
  오피스에서 쓰기 좋은 …                 ← note  ★필수
```

### 폴링이 끝났을 때 전체 응답

프론트 결과 화면은 이 안의 **`result`만** 보면 된다.

```json
{
  "jobId": "job_9f2c1a7b3e00",
  "status": "DONE",
  "steps": [
    { "key": "profile",    "label": "프로필 분석",           "status": "done" },
    { "key": "search",     "label": "조건에 맞는 제품 찾기", "status": "done" },
    { "key": "conflict",   "label": "성분 조합 검수",       "status": "done" },
    { "key": "commentary", "label": "추천 이유 작성",       "status": "done" }
  ],
  "result": {
    "summary": "복합성 피부에 트러블 고민을 고려해서, 알코올이 들어가지 않은 제품 위주로 골랐어요.",
    "cosmetic": [
      {
        "itemId": "p_001",
        "name": "시카 수딩 토너",
        "brand": "라보그린",
        "category": "토너",
        "score": 86,
        "note": "알코올 무첨가, 진정 성분 위주라 트러블 고민에 맞을 수 있어요."
      }
    ],
    "fragrance": [
      {
        "itemId": "f_002",
        "name": "우디 머스크 오드퍼퓸",
        "brand": "메종노트",
        "score": 79,
        "note": "오피스에서 쓰기 좋은 잔잔한 무게감이에요.",
        "notes": {
          "family": "우디",
          "top": ["베르가못"],
          "heart": ["아이리스"],
          "base": ["샌달우드", "화이트머스크"]
        }
      }
    ],
    "cautions": [
      {
        "pair": ["retinol", "aha"],
        "pairLabels": ["레티놀", "AHA/BHA"],
        "severity": "caution",
        "message": "같은 날 밤에 함께 쓰면 자극이 누적될 수 있어요. 번갈아 쓰는 걸 권해요.",
        "source": "일반적 스킨케어 가이드라인",
        "confidence": "medium"
      }
    ],
    "relaxationLevel": 0,
    "blockedBy": []
  },
  "error": null,
  "elapsedMs": 4800
}
```

mock fixture 전체 예시는 `ai-core/mock/fixtures/both.json`, `cosmetic_only.json`, `fragrance_only.json`.

### 필드 ↔ 화면 매핑

| 필드 | 화면 | 규칙 |
|---|---|---|
| `summary` | 상단 2~3문장 | 고른 **기준**을 말함. 효능 단정 금지 |
| `cautions[]` | 주의 카드 | 빈 배열이면 **영역 자체를 안 그림** |
| `cautions[].pairLabels` | 카드 제목 `A + B` | `pair`는 `retinol` 같은 키라 화면에 쓰지 않음 |
| `cautions[].severity` | 배지 | `caution` → 노랑 + **주의** / `avoid` → 빨강 + **피하세요** |
| `cautions[].message` | 본문 | 단정 금지, 다음 행동 포함 |
| `cautions[].source` · `confidence` | 작은 캡션 | **둘 다 필수**. 색만으로 구분하지 않음 |
| `cosmetic[]` / `fragrance[]` | 섹션별 카드 | 트랙이 `cosmetic`이면 향수 섹션 숨김 |
| `name` / `brand` / `score` | 제목·부제·게이지 | `score`는 0~100, 막대에 그대로 |
| `category` | 화장품 부제 `브랜드 · 토너` | 향수는 `null` |
| `notes` | 향수 피라미드 | 화장품은 `null`. `family`가 부제의 계열 |
| `note` | 추천 이유 한 줄 | **비면 버그.** 모든 카드 필수 |
| `relaxationLevel` | 상단 배너 | `> 0`일 때만: "일부 조건을 완화해서 찾았어요" |
| `blockedBy` | 0건 화면의 걸린 조건 | 결과가 있을 때는 `[]` |

---

## 04. 화면 분기를 만드는 결과 변형

결과 화면이 갈라지는 건 이 네 가지뿐이다. 정상 JSON만 넣으면 배너·빈 상태·에러가 빠진다.

### A. 정상 (`relaxationLevel = 0`)

03의 예시. 배너 없음, 카드 + 요약.

### B. 조건 완화 (`relaxationLevel > 0`)

같은 레이아웃 + 상단 배너. `summary`에도 완화했다는 한 줄이 들어가도 된다.

```json
{
  "relaxationLevel": 1,
  "summary": "조건에 딱 맞는 제품이 많지 않아서 카테고리 조건을 조금 완화해서 찾았어요. 기피 성분은 그대로 지켰어요."
}
```

`1` = 일부 완화, `2` = 대폭 완화. 기피 성분은 어떤 단계에서도 풀지 않는다.

### C. 결과 0건 — 에러가 아님

`status`는 `DONE`. 프론트는 오류 화면이 아니라 **빈 상태 + 걸린 조건 + [조건 수정하기]**.

```json
{
  "status": "DONE",
  "result": {
    "summary": "조건에 맞는 제품을 찾지 못했어요. 기피 성분을 조금 줄이거나 카테고리를 넓혀볼까요?",
    "cosmetic": [],
    "fragrance": [],
    "cautions": [],
    "relaxationLevel": 2,
    "blockedBy": [
      "기피 성분: 알코올, 향료, 파라벤, 에센셜오일",
      "카테고리: 토너"
    ]
  },
  "error": null
}
```

0건이면 LLM을 안 타므로 `commentary` 단계는 `skipped`. fixture: `ai-core/mock/fixtures/no_candidates.json`.

### D. 실패 (`FAILED`) — 결과 화면이 아님

SC-03에서 멈춘다. `result`는 `null`.

```json
{
  "status": "FAILED",
  "result": null,
  "error": { "code": "TIMEOUT", "message": "30초 내 완료되지 않았습니다" }
}
```

| `code` | 사용자 문구 (프론트가 번역) |
|---|---|
| `TIMEOUT` | 시간이 오래 걸리고 있어요 |
| `LLM_ERROR` | 추천 이유를 만들지 못했어요 |
| `INTERNAL` | 문제가 생겼어요 |
| `JOB_NOT_FOUND` | 요청을 찾을 수 없어요 |

`error.message`는 로그/개발용. 사용자에게 그대로 보여주지 않는다.

---

## 05. 카드별 최소 스키마

### 화장품 — `notes` 없음, `category` 있음

```json
{
  "itemId": "p_001",
  "name": "시카 수딩 토너",
  "brand": "라보그린",
  "category": "토너",
  "score": 86.0,
  "note": "알코올 무첨가에 진정 성분 위주라 트러블 고민에 맞을 수 있어요."
}
```

프론트 매핑 예:

- 제목 → `name`
- 부제 → `` `${brand} · ${category}` ``
- 점수 막대 → `score` (0~100)
- 추천 이유 → `note`

### 향수 — `category` 없음, `notes` 있음

```json
{
  "itemId": "f_002",
  "name": "우디 머스크 오드퍼퓸",
  "brand": "메종노트",
  "score": 79.0,
  "note": "샌달우드와 화이트머스크가 중심이라 오피스에서 쓰기 좋은 잔잔한 무게감이에요.",
  "notes": {
    "family": "우디",
    "top": ["베르가못"],
    "heart": ["아이리스"],
    "base": ["샌달우드", "화이트머스크"]
  }
}
```

프론트 매핑 예:

- 부제 → `` `${brand} · ${notes.family}` ``
- 피라미드 → `탑: notes.top.join` / `미들: notes.heart.join` / `베이스: notes.base.join`
- 추천 이유 → `note`

`track = "cosmetic"`이면 `fragrance`는 `[]`. **빈 배열이면 향수 섹션을 렌더링하지 않는다.** 빈 제목만 남기지 말 것.

### 주의 — 키(`pair`)와 한글(`pairLabels`)을 같이

```json
{
  "pair": ["retinol", "aha"],
  "pairLabels": ["레티놀", "AHA/BHA"],
  "severity": "caution",
  "message": "같은 날 밤에 함께 쓰면 자극이 누적될 수 있어요. 번갈아 쓰는 걸 권해요.",
  "source": "일반적 스킨케어 가이드라인",
  "confidence": "medium"
}
```

- 제목 → `pairLabels.join(" + ")`  (화면에 `pair` 쓰지 않음)
- 배지 텍스트 → `severity === "avoid"` 이면 **피하세요**, 아니면 **주의**
- 본문 → `message`
- 캡션 → `` `출처: ${source}` `` + `confidence`

---

## 06. 문장 톤 (화면이 깨지는 지점)

화면 카피가 AI 문장을 그대로 붙이므로, 생성 문장이 곧 UI다. 프론트는 번역하지 않고 출력만 한다.

| | 쓰면 안 됨 | 화면이 기대하는 톤 |
|---|---|---|
| `note` | 트러블에 효과적입니다 | 진정 성분 위주라 트러블 고민에 **맞을 수 있어요** |
| `cautions.message` | 함께 쓰면 안 됩니다 | 자극이 누적될 수 있어요. **번갈아 쓰는 걸 권해요** |
| `summary` (0건) | 검색 결과가 없습니다 | 조건에 맞는 제품을 찾지 못했어요. **기피 성분을 조금 줄여볼까요?** |
| 단계 `label` | ingredient_matcher 실행 중 | 조건에 맞는 제품 찾기 |

AI 쪽 추가 제약:

- 후보 목록에 없는 제품명을 `summary`/`note`에 넣지 않음
- 주의사항은 내려준 `cautions`에 있는 것만 말함
- 모든 `note`는 한 줄, 비우지 않음

---

## 07. AI가 안 내려줘도 되는 것

화면에는 있지만 **백엔드/프론트 몫**.

- 추천 날짜 (`2026.09.17 추천`)
- 좋아요/아쉬워요 → `POST /api/feedback`
- 히스토리 카드 (`화장품 · 향수`, `시카 수딩 토너 외 4개`)
- 프로필 칩 값 자체 (그건 **입력**)

입력 (`POST /jobs` 본문)은 화면 1과 1:1이다.

```json
{
  "profileId": "…",
  "track": "cosmetic",
  "skinType": "복합성",
  "concerns": ["모공", "트러블"],
  "avoidIngredients": ["알코올"],
  "currentActives": ["레티놀"],
  "preferredScentFamilies": ["우디", "머스크"],
  "occasion": "오피스"
}
```

`track`은 `"cosmetic"` | `"fragrance"` | `"both"`.  
`cosmetic`이면 응답 `fragrance`는 `[]`이고, 화면이 향수 섹션을 안 그린다.

---

## 08. 프론트 체크리스트

결과 화면을 정상 JSON만으로 그릴 때 빠지기 쉬운 것.

- [ ] `cautions.length === 0`이면 주의 영역 자체를 안 그림
- [ ] `fragrance.length === 0`이면 향수 섹션을 안 그림
- [ ] `relaxationLevel > 0`이면 상단 완화 배너
- [ ] `cosmetic`·`fragrance`가 둘 다 빈 배열이면 0건 화면 + `blockedBy` 표시
- [ ] 모든 카드에 `note`가 있다 (없으면 ai-core 버그로 취급)
- [ ] 주의 배지는 색 + 텍스트 (`주의` / `피하세요`)
- [ ] `pair` 대신 `pairLabels`를 제목에 쓴다
- [ ] `FAILED`는 결과 화면이 아니라 진행 화면의 에러 UI

---

*musely AI 아웃풋 ↔ 화면 매핑 · 2026-09*

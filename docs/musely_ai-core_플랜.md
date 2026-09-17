# musely — ai-core 플랜

나연 담당 · FastAPI + LangGraph · 비동기 job/폴링 · 최종판

> 관련 문서: **빌드 플랜**(전체), **기획서**(제품 정의 + 화면 구성)

---

## 00. 용어 정리 — "비동기"가 두 개다

이거 안 갈라두면 설계 대화가 계속 어긋난다.

| | 뜻 | 이번 프로젝트 |
|---|---|---|
| **API 계약으로서의 비동기** | 요청 접수 후 202+jobId 즉시 반환, 결과는 폴링 | ✅ 확정 |
| **런타임으로서의 비동기** | `async def` + 이벤트 루프로 I/O 대기 중 다른 요청 처리 | ✅ 필수 (별개 얘기) |

둘은 독립적이다. 그리고 **둘 다 해야 한다** — job API로 계약을 맺고, 내부는 이벤트 루프를 막지 않게 짠다. 04의 함정 두 개가 전부 후자에서 나온다.

---

## 01. ai-core의 소유 범위

**소유**
- FastAPI 서비스: `POST /jobs`, `GET /jobs/{id}`, `GET /health`
- job 상태 저장소 (휘발성, TTL 30분)
- LangGraph 오케스트레이터와 4개 에이전트
- 벡터 인덱싱·검색 파이프라인, 성분 충돌 규칙
- 계약 스키마와 mock 서버
- 평가 스크립트

**소유하지 않음**
- 사용자·프로필·추천 이력의 영속화 → Spring Boot
- 인증, 사용자에게 보이는 job 관리 → Spring Boot

**경계 원칙** — ai-core의 job은 *휘발성 작업 상태*, Spring Boot의 job은 *사용자에게 보여줄 영속 상태*다. 이름이 같아 헷갈리지만 역할이 다르다. 추천 결과의 진짜 주인은 Spring Boot의 `Recommendation` 레코드다.

ai-core는 **프로필 JSON 받아서 추천 JSON 뱉는 함수**로 유지한다. 백엔드 DB를 직접 조회하지 않는다.

---

## 02. 레포 구조

```
ai-core/
├─ app/
│  ├─ main.py                 # FastAPI, job 엔드포인트
│  ├─ jobs.py                 # JobStore, Job 상태 머신
│  ├─ schemas.py              # Pydantic 계약 = 백엔드와의 약속
│  ├─ graph/
│  │  ├─ state.py             # CurationState
│  │  ├─ build.py             # 그래프 조립, 조건부 엣지
│  │  └─ agents/
│  │     ├─ ingredient_matcher.py
│  │     ├─ conflict_checker.py
│  │     ├─ scent_matcher.py
│  │     └─ commentary.py     # 두 트랙 공용
│  ├─ retrieval/
│  │  ├─ store.py             # 벡터 스토어 추상화
│  │  ├─ filters.py           # 메타데이터 필터 빌더 ★
│  │  └─ index.py             # 인덱싱 CLI
│  └─ llm.py                  # AsyncOpenAI 래퍼, structured output
├─ data/
│  ├─ products.jsonl
│  ├─ fragrances.jsonl
│  └─ conflict_rules.yaml
├─ eval/
│  ├─ golden_set.jsonl
│  └─ run_eval.py
├─ mock/mock_server.py        # 1주차 최우선 산출물
└─ docker-compose.yml
```

---

## 03. job API

### 엔드포인트

| 메서드 | 경로 | 응답 |
|---|---|---|
| POST | `/jobs` | 202 `{jobId, status}` |
| GET | `/jobs/{jobId}` | 200 `{jobId, status, result, error, elapsedMs}` |
| GET | `/health` | 200 `{status, indexedCounts}` — 인덱싱 건수까지 노출하면 디버깅이 편하다 |

### 상태 머신

```
PENDING ──► RUNNING ──┬──► DONE     (후보 0건도 여기로 온다)
                      └──► FAILED  (TIMEOUT | LLM_ERROR | INTERNAL)
```

`FAILED`일 때 **기계가 읽을 코드**를 줄 것. 사람이 읽는 문장만 주면 백엔드가 분기 처리를 못 한다.

**후보 0건은 `FAILED`가 아니다.** 시스템은 정상 동작했고 조건이 빡빡했을 뿐이다. `DONE` +
빈 배열 + `blockedBy`(걸린 조건)로 주고, 프론트는 결과 화면의 빈 상태를 렌더링한다.
`FAILED`로 주면 화면이 "문제가 생겼어요"로 잘못 분기한다.

```json
{
  "jobId": "job_9f2c1a7b3e00",
  "status": "FAILED",
  "result": null,
  "error": { "code": "TIMEOUT", "message": "30초 내 완료되지 않았습니다" },
  "elapsedMs": 30021
}
```

### 계약 스키마 (1주차에 고정)

> **확정판은 `ai-core/app/schemas.py`다.** 아래는 설계 당시의 초안이고, 구현하면서
> 아래 다섯 가지가 바뀌었다. 문서와 코드가 어긋나면 코드가 맞다.
>
> 1. **와이어 포맷은 camelCase.** 내부는 snake_case를 쓰고 `CamelModel`이 변환한다.
>    Jackson 기본값과 맞아서 백엔드가 `@JsonProperty`를 붙일 필요가 없다.
> 2. **`steps[]`가 job 응답 최상위에 추가됐다.** 단계 표시는 RUNNING 중에 필요한데
>    `result`는 DONE에서야 채워진다. `label`에 한글 문구까지 담아 내린다.
> 3. **후보 0건은 `DONE` + 빈 배열 + `blockedBy`.** 위 상태 머신 설명 참고.
> 4. **`Candidate.notes`(향수 노트 피라미드)와 `Candidate.category`가 추가됐다.**
>    향수 카드가 탑/미들/베이스를 표시해야 하고, 화장품 카드는 부제에 카테고리를 쓴다.
> 5. **`Caution.pairLabels`가 추가됐다.** `pair`는 규칙 키(`retinol`)라 화면에 그대로
>    쓸 수 없다. 라벨은 `data/conflict_rules.yaml`의 `labels`에서 온다.
>
> `python -m scripts.check_contract`가 이 계약과 mock fixture의 정합성을 검사한다.

```python
class OrchestrateRequest(BaseModel):
    profile_id: str
    track: Literal["cosmetic", "fragrance", "both"]
    skin_type: str | None = None
    concerns: list[str] = []
    avoid_ingredients: list[str] = []
    current_actives: list[str] = []         # 현재 사용 중인 활성 성분
    preferred_scent_families: list[str] = []
    occasion: str | None = None

class Candidate(BaseModel):
    item_id: str
    name: str
    brand: str
    score: float
    note: str                                # 왜 뽑혔는지 한 줄

class Caution(BaseModel):
    pair: list[str]
    severity: Literal["caution", "avoid"]
    message: str
    source: str
    confidence: Literal["low", "medium", "high"]

class OrchestrateResult(BaseModel):
    cosmetic: list[Candidate] = []
    fragrance: list[Candidate] = []
    cautions: list[Caution] = []
    summary: str
    relaxation_level: int = 0                # 0=원조건 1=일부완화 2=대폭완화
```

---

## 04. FastAPI 구현

### job 저장소

```python
# app/jobs.py
class JobStatus(str, Enum):
    PENDING="PENDING"; RUNNING="RUNNING"; DONE="DONE"; FAILED="FAILED"

@dataclass
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    result: dict | None = None
    error: dict | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None

    @property
    def elapsed_ms(self) -> int:
        end = self.finished_at or datetime.utcnow()
        return int((end - self.created_at).total_seconds() * 1000)

class JobStore:
    def __init__(self, ttl_minutes: int = 30):
        self._jobs: dict[str, Job] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def create(self) -> Job:
        self._sweep()                        # 별도 스케줄러 없이 생성 시점에 청소
        job = Job(id=f"job_{uuid.uuid4().hex[:12]}")
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _sweep(self) -> None:
        cutoff = datetime.utcnow() - self._ttl
        for k in [k for k, v in self._jobs.items() if v.created_at < cutoff]:
            del self._jobs[k]
```

### 엔드포인트

```python
# app/main.py
@app.post("/jobs", status_code=202)
async def create_job(req: OrchestrateRequest, bg: BackgroundTasks):
    job = store.create()
    bg.add_task(run_job, job.id, req)
    return {"jobId": job.id, "status": job.status}

@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
    return {"jobId": job.id, "status": job.status, "result": job.result,
            "error": job.error, "elapsedMs": job.elapsed_ms}

async def run_job(job_id: str, req: OrchestrateRequest):
    job = store.get(job_id)
    job.status = JobStatus.RUNNING
    try:
        job.result = await asyncio.wait_for(execute(req), timeout=30.0)
        job.status = JobStatus.DONE
    except asyncio.TimeoutError:
        job.status = JobStatus.FAILED
        job.error = {"code": "TIMEOUT", "message": "30초 내 완료되지 않았습니다"}
    except Exception as e:
        job.status = JobStatus.FAILED
        job.error = {"code": "INTERNAL", "message": str(e)[:300]}
        logger.exception("job %s failed", job_id)
    finally:
        job.finished_at = datetime.utcnow()
```

`asyncio.wait_for` 상한이 중요하다. LLM이 먹통이 되면 job이 영원히 RUNNING으로 남고 프론트가 무한 폴링한다.

### 두 트랙 병렬

```python
async def execute(req: OrchestrateRequest) -> dict:
    base = req.model_dump()
    if req.track == "both":
        cos, frag = await asyncio.gather(
            graph.ainvoke({**base, "track": "cosmetic"}),
            graph.ainvoke({**base, "track": "fragrance"}),
        )
        return merge(cos, frag)
    return to_result(await graph.ainvoke({**base, "track": req.track}))
```

순차 12초가 병렬 6~7초가 된다. 단, **단일 트랙이 안정적으로 돌기 전엔 손대지 말 것**(디버깅이 두 배로 어려워진다). 계약에는 1주차부터 열어두고 구현은 4주차.

---

## 05. 반드시 밟는 함정 두 개

"알면 5분, 모르면 하루"짜리다. 둘 다 데모 당일에 터지는 종류.

### 함정 1 — uvicorn 워커 2개 이상이면 job이 사라진다

in-memory `dict`로 job을 들고 있으면 `POST /jobs`를 처리한 프로세스와 `GET /jobs/{id}`를 처리하는 프로세스가 달라져서, 방금 만든 job이 404로 나온다. 운에 따라 성공하기도 해서 재현이 들쭉날쭉하고 디버깅이 특히 짜증난다.

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1   # ✅ 고정
```

이벤트 루프가 I/O 대기 중엔 다른 요청을 처리하므로 데모 트래픽에선 병목이 아니다. docker-compose와 README에 이유를 주석으로 남길 것.

### 함정 2 — 동기 SDK가 이벤트 루프를 막는다

`async def` 안에서 동기 클라이언트를 호출하면 그 3~4초 동안 **이벤트 루프 전체가 멈춘다.** `GET /jobs/{id}` 폴링까지 같이 멈춰서 "폴링이 응답을 안 준다"로 나타난다. 비동기로 짰는데 동기처럼 동작하는, 제일 헷갈리는 증상이다.

```python
# ❌ 루프를 막는다
from openai import OpenAI
resp = OpenAI().chat.completions.create(...)

# ✅ async 클라이언트
from openai import AsyncOpenAI
resp = await AsyncOpenAI().chat.completions.create(...)

# ✅ async 버전이 없는 라이브러리(chromadb 등)는 스레드로
hits = await asyncio.to_thread(collection.query, query_texts=[q], n_results=5, where=where)
```

에이전트 전부 `async def`로 쓰고 `graph.ainvoke()`로 호출할 것. 하나라도 동기로 블로킹하면 그대로 재현된다.

---

## 06. 에이전트 구성

| 에이전트 | 입력 | 하는 일 | 출력 |
|---|---|---|---|
| **성분 매칭** | 프로필 | 하드 제약으로 필터 구성 → 화장품 벡터DB 검색 → 0건이면 완화 재시도 | `candidates` |
| **성분 충돌 검수** | candidates + current_actives | 규칙 테이블로 조합 검수, 위험 후보 제외 | `cautions`, 필터된 `candidates` |
| **향수 매칭** | 프로필 | 선호 계열·상황으로 향수 벡터DB 검색 | `candidates` |
| **설명 생성** (공용) | candidates + cautions | 근거와 함께 자연어 설명 생성 | `summary`, 항목별 `note` |

### State

```python
class CurationState(TypedDict):
    profile: dict
    track: Literal["cosmetic", "fragrance"]
    candidates: list[dict]
    cautions: list[dict]
    relaxation_level: int
    summary: str
    trace: list[dict]          # 에이전트별 소요시간·검색쿼리
```

### 그래프

```python
builder = StateGraph(CurationState)
builder.add_node("ingredient_matcher", ingredient_matcher)    # 전부 async def
builder.add_node("conflict_checker", conflict_checker)
builder.add_node("scent_matcher", scent_matcher)
builder.add_node("commentary", commentary)

builder.add_conditional_edges(
    START, lambda s: s["track"],
    {"cosmetic": "ingredient_matcher", "fragrance": "scent_matcher"},
)
builder.add_edge("ingredient_matcher", "conflict_checker")
builder.add_conditional_edges(
    "conflict_checker",
    lambda s: "skip" if not s["candidates"] else "go",
    {"go": "commentary", "skip": END},        # 0건이면 LLM 건너뜀
)
builder.add_edge("scent_matcher", "commentary")
builder.add_edge("commentary", END)
graph = builder.compile()
```

`trace`는 처음부터 넣을 것. "왜 이 제품이 추천됐지"를 디버깅할 때, 그리고 프론트의 진행 단계 표시(기획서 화면 2)에 쓸 때 이거 하나면 끝난다.

**에이전트는 4개에서 늘리지 말 것.** 리랭킹이 필요하면 노드 추가 말고 matcher 안에서 처리.

---

## 07. 검색 설계 — 기술적으로 제일 값어치 있는 부분

### 임베딩은 부정을 못 잡는다

"알코올 안 들어간 토너"를 그대로 임베딩해 유사도 검색하면 **알코올이 들어간 토너가 상위에 온다.** 기피 성분·알러지 같은 하드 제약은 100% 구조화 필터로 처리한다.

```python
# app/retrieval/filters.py
def build_where(profile: dict, track: str) -> dict:
    where: dict = {}
    if track == "cosmetic":
        if profile.get("category"):
            where["category"] = profile["category"]
        if profile.get("avoid_ingredients"):
            where["ingredients"] = {"$nin": profile["avoid_ingredients"]}
    else:
        if profile.get("preferred_scent_families"):
            where["note_family"] = {"$in": profile["preferred_scent_families"]}
    return where
```

**하드 제약은 필터, 소프트 선호는 벡터.** 기피 성분이 결과에 섞이면 성능 문제가 아니라 버그다.

### 0건일 때 완화 체인

필터가 세면 후보 0건이 자주 난다. 조용히 빈 배열을 주지 말 것.

```python
async def search_with_relaxation(profile, track, k=5):
    for level, where in enumerate(relaxation_chain(profile, track)):
        hits = await asyncio.to_thread(store.query, build_query(profile), where, k)
        if hits:
            return hits, level
    return [], 2
```

완화 순서는 **카테고리 → 선호 계열** 순으로 풀고, **기피 성분은 어떤 단계에서도 풀지 않는다.** `relaxation_level`을 결과에 실어 보내면 화면에서 "조건을 조금 완화해서 찾았어요"라고 안내할 수 있다.

0건일 땐 LLM을 아예 호출하지 않는다 — 없는 제품을 지어내는 최악의 실패를 구조적으로 차단.

---

## 08. 데이터 파이프라인 — 공수의 40%

**제일 오래 걸리고 제일 재미없다.** 규모를 통제하는 게 유일한 방어책.

| 데이터 | 건수 | 전략 |
|---|---|---|
| 화장품 | 100~150 | 브랜드 공식 제품 페이지 전성분을 수기 정리. 대량 크롤링은 ToS 문제로 피할 것 |
| 성분 사전 | 40~60 | 대표 활성 성분만(레티놀, 나이아신아마이드, AHA/BHA, 비타민C 등) 효능·주의 3~5줄 |
| 향수 | 80~120 | 노트 피라미드 + 계열 + 분위기 태그 |
| 충돌 규칙 | 15~25 | 아래 주의 |

**150건이면 충분하다.** 1000건을 반쯤 엉망으로 넣는 것보다 150건을 정확히 넣는 게 검색 품질도 발표 설득력도 낫다.

### 성분 충돌 규칙 — 주의

뷰티 커뮤니티에 도는 "충돌" 정보는 상당수가 근거가 약하거나 반박됐다(나이아신아마이드+비타민C 충돌설이 대표적으로 오래된 고온 실험 조건 얘기다). 레티놀+AHA/BHA도 "충돌"보다 자극 누적에 가깝다.

```yaml
- id: retinol_aha
  pair: [retinol, aha]
  severity: caution                # conflict 아님
  message: "같은 날 밤에 함께 쓰면 자극이 누적될 수 있어요. 번갈아 쓰는 걸 권해요."
  source: "일반적 스킨케어 가이드라인"
  confidence: medium
```

`severity`/`source`/`confidence`를 데이터로 들고 응답에 그대로 노출하는 설계 자체가 **"AI가 단정적 의학 주장을 하지 않게 만드는 장치"**로 발표에서 설명하기 좋다.

### 인덱싱

제품 1건 = 청크 1개. 청킹 전략은 고민할 게 없다.

```python
# 화장품
f"{name} / {brand} / {category}\n주요 성분: {', '.join(key_ingredients)}\n{description}"
# 향수
f"{name} / {brand}\n계열: {note_family}\n탑: {top} / 미들: {heart} / 베이스: {base}\n{description}"
```

메타데이터에 필터용 값을 반드시 구조화해서 넣을 것: `ingredients: list[str]`, `alcohol_free: bool`, `category`, `note_family`.

---

## 09. 프롬프트 & 환각 차단

```python
class Commentary(BaseModel):
    summary: str                    # 2~3문장
    per_item: list[ItemNote]        # 후보별 한 줄 근거
```

프롬프트 제약 세 줄:

```
- 아래 후보 목록에 없는 제품명을 절대 언급하지 마세요.
- 효능은 단정하지 말고 "~에 도움될 수 있어요" 수준으로 표현하세요.
- 주의사항은 제공된 caution 목록에 있는 것만 말하세요.
```

첫 줄이 제일 중요하고, 10의 평가에서 자동으로 잡는다.

---

## 10. 평가 — 작게 만들어서 살아남게

`eval/golden_set.jsonl` 20~30건:

```jsonl
{"profile":{"skin_type":"oily","concerns":["모공"],"avoid_ingredients":["알코올"]},"track":"cosmetic","must_not_contain":["알코올"],"expect_category":"토너"}
```

측정 세 가지 — **전부 LLM 없이 순수 코드로 가능:**

1. **제약 위반율** — 기피 성분이 결과에 섞였나. 0%여야 하고 아니면 버그.
2. **recall@5** — 기대 카테고리·성분군이 상위 5개에 들었나.
3. **환각율** — 설명에 나온 제품명이 전부 후보 안에 있나. 문자열 매칭으로 충분.

주관적 설명 품질(LLM-as-judge)은 스트레치. 위 셋만 있어도 "평가 루프를 갖춘 사이드 프로젝트"가 된다.

---

## 11. mock 서버 — 1주차 최우선 산출물

job API 구조에선 백엔드가 **로딩 UI와 폴링 로직을 개발하려면 "느린 mock"이 필요하다.**

```python
@app.post("/jobs", status_code=202)
async def create(req: dict):
    job_id = f"mock_{uuid.uuid4().hex[:8]}"
    MOCK[job_id] = {"at": time.time(),
                    "delay": float(req.get("_mock_delay", 5)),
                    "fail": req.get("_mock_fail")}
    return {"jobId": job_id, "status": "PENDING"}

@app.get("/jobs/{job_id}")
async def get(job_id: str):
    j = MOCK.get(job_id)
    if not j: raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
    if time.time() - j["at"] < j["delay"]:
        return {"jobId": job_id, "status": "RUNNING", "result": None}
    if j["fail"]:
        return {"jobId": job_id, "status": "FAILED",
                "error": {"code": j["fail"], "message": "mock failure"}}
    return {"jobId": job_id, "status": "DONE", "result": FIXTURE}
```

`_mock_delay`와 `_mock_fail`을 열어두면 백엔드가 로딩·타임아웃·에러 UI를 전부 테스트할 수 있다. **1주차에 이것만 나와도 백엔드는 3주차까지 안 막힌다.**

---

## 12. 레이턴시 · 비용

| 구간 | 예상 |
|---|---|
| `POST /jobs` 응답 | 50ms 미만 (접수만) |
| 쿼리 임베딩 | 100~300ms |
| 벡터 검색 (300건) | 10ms 미만 |
| 충돌 검수 (규칙) | 1ms 미만 |
| 설명 생성 (LLM) | 2~4초 |
| **단일 트랙 합계** | **3~5초** |
| 두 트랙 순차 | 6~10초 |
| **두 트랙 병렬** | **4~6초** |
| 권장 폴링 주기 | 1초 / 프론트 상한 60초 / ai-core 상한 30초 |

**비용**: 개발+데모 전체 몇 천 원. 인덱싱 1회 1원 미만, 추천 1건당 0.5원 미만(gpt-4o-mini 기준). 고민할 항목이 아니다.

---

## 13. 기술 선택

| 항목 | 선택 | 이유 |
|---|---|---|
| 그래프 | LangGraph | 익숙해서 학습 비용 0. 노드 4개 규모라 사실 함수 체인으로도 되지만 일관성 목적 |
| LLM | gpt-4o-mini / claude-haiku | 설명 문장 생성만 담당. 상위 모델 쓸 이유 없음 |
| 임베딩 | text-embedding-3-small | 300건 규모에선 모델 간 체감 차이 없음. 로컬 모델 세팅 비용이 이득보다 큼 |
| 벡터DB | Chroma(persist) 또는 Qdrant | 300건이면 Chroma 파일 모드로 충분. 실무에서 안 써본 걸 고르는 게 학습엔 나음 |
| 비동기 | FastAPI BackgroundTasks | Celery/RQ는 이 규모에 오버 |

**pgvector로 백엔드 Postgres에 얹는 안은 비추천.** 컨테이너를 안 늘리는 건 매력적이지만 ai-core가 백엔드 스키마에 묶여서 01의 경계가 깨지고, 둘이 마이그레이션 충돌을 겪게 된다.

---

## 14. 주차별 작업

| 주차 | 할 일 | 산출물 |
|---|---|---|
| 1주차 | 계약 스키마 확정 → **mock 서버 배포** → 데이터 수집(50건) → 인덱싱 스크립트 | `schemas.py`, mock, `index.py` |
| 2주차 | 데이터 완성(150건) → 필터 빌더 + 완화 체인 → 4개 에이전트 → job API 실동작 | 실제 `POST /jobs` |
| 3주차 | 프롬프트 튜닝 → 에러 코드 정리 → 백엔드 실연동 → trace 노출 | 통합 동작 |
| 4주차 | 골든셋 + 평가 스크립트 → `both` 병렬 → 실측 기록 → (스트레치) 임베딩 모델 비교 | eval 리포트 |

---

## 15. 리스크 & 자를 순서

**시간이 샐 구간**
1. 데이터 큐레이션 — 예상의 1.5~2배. 150건도 손으로 하면 하루 이상
2. 05 함정 2(이벤트 루프 블로킹) — 모르고 들어가면 반나절
3. 프롬프트 톤 잡기 — 3~4회 돌리고 만족 안 되면 멈출 것

**자를 순서**: ① 임베딩 모델 비교 → ② LLM-as-judge → ③ `both` 병렬 → ④ 향수 트랙 전체 → ⑤ 완화 체인 2단계

**절대 자르면 안 되는 것**: 하드 제약 필터(07), 0건일 때 LLM 건너뛰기(07), 환각 차단 프롬프트(09), 제약 위반율 체크(10), job 타임아웃 상한(04).

---

## 16. 포트폴리오 관점

**새로 얻는 것**
- 제약 조건 검색 설계 — 부정/필터를 벡터에서 분리하는 판단. 실무 감각으로 제일 값어치 큼
- 비동기 job API 설계와 상태 머신
- 이벤트 루프 블로킹을 직접 밟고 해결한 경험
- 평가 루프를 코드로 갖춘 경험
- 타인과의 API 계약, 의존 방향 설계

**이미 아는 것 (빠르게 지나갈 것)**
- LangGraph 그래프 구성, 기본 RAG 파이프라인, FastAPI 기본 서빙

**한 가지 참고** — 이 구조에서 각 에이전트는 검색·규칙 검수·생성이라는 명확한 책임 단위이고, 오케스트레이터가 트랙에 따라 분기시킨다. 면접에서 "에이전트가 어떻게 동작하나요"를 물으면 이 책임 분리와 조건부 라우팅을 그대로 설명하면 된다. 굳이 자율 루프가 있는 것처럼 말할 필요는 없고, 오히려 "결정론적으로 둘 곳과 LLM에 맡길 곳을 나눈 판단"이 더 좋은 답이 된다.

---
*musely ai-core 플랜 · 2026-09*

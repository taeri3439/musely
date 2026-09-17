# musely ai-core

FastAPI + LangGraph 추천 서비스. 프로필 JSON을 받아 추천 JSON을 돌려주는 게 전부이고,
백엔드 DB를 직접 조회하지 않는다.

**현재 상태: 1주차 — mock 서버만 동작한다.** 실제 벡터 검색과 LLM 호출은 2주차부터.

---

## 실행

`;`로 명령을 이어붙이지 말 것. cmd에서는 `;`가 구분자가 아니라 경로의 일부로 들어가서
`python -m venv .venv; ...`가 `.venv;`라는 이름의 venv를 만들려다 실패한다.
**한 줄씩 실행한다.**

cmd:

```bat
cd ai-core
python -m venv .venv
.venv\Scripts\activate.bat
copy .env.example .env
pip install -r requirements.txt
python -m scripts.check_contract
uvicorn mock.mock_server:app --host 0.0.0.0 --port 8000 --workers 1 --reload
```

PowerShell:

```powershell
cd ai-core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .env.example .env
pip install -r requirements.txt
python -m scripts.check_contract
uvicorn mock.mock_server:app --host 0.0.0.0 --port 8000 --workers 1 --reload
```

프롬프트 앞에 `(.venv)`가 붙었는지 확인하고 `pip install`을 한다. 안 붙은 상태로
설치하면 전역 파이썬이 오염되고, 2주차에 넣을 `langgraph`·`chromadb`가 다른
프로젝트의 버전과 충돌한다.

`--host 0.0.0.0`을 빼면 `127.0.0.1`에만 바인딩돼서 같은 PC 밖(다른 노트북,
docker-compose의 다른 컨테이너)에서는 붙지 못한다.

`python -m scripts.check_contract`는 서버 없이 돌아가고 `.env` 로딩, 충돌 규칙,
fixture ↔ 계약 정합성을 한 번에 확인한다. fixture를 손볼 때마다 먼저 돌릴 것.

## 로컬 인덱싱 (Render mock과 무관)

실제 검색은 로컬에서만 돌린다. Render의 mock은 그대로 둔다.

```bat
pip install -r requirements-retrieval.txt
python -m app.retrieval.index
python -m scripts.check_retrieval
```

임베딩은 Gemini(`gemini-embedding-001`)를 쓴다. Anthropic은 임베딩 API가 없어서
인덱싱에 쓸 수 없고, 나중에 설명 생성 LLM으로만 쓴다. `.env`에 아래가 있어야 한다.

```
EMBEDDING_PROVIDER=gemini
EMBEDDING_MODEL=gemini-embedding-001
GEMINI_API_KEY=...
```

`check_retrieval`의 통과 기준: 알코올 기피로 검색했을 때 세틸알코올이 들어간 `p_007`은
남고, 에탄올이 들어간 `p_002`는 빠진다.

---

## 백엔드용 시작 가이드

**백엔드가 설치할 건 아무것도 없다.** 배포된 mock URL을 받아서 설정에 넣으면 끝이다.

```yaml
# application.yml
ai-core:
  base-url: https://musely-ai-core-mock.onrender.com
```

**통합 지점은 이 설정값 하나뿐이다.** mock이 클라우드든 로컬이든 3주차의
docker-compose 안이든 이 값만 갈아끼우면 된다.

### ⚠️ 무료 티어는 잠든다

15분 동안 요청이 없으면 서비스가 스핀다운되고, 다시 깨어나는 데 **약 1분** 걸린다.
프론트 폴링 상한이 60초라서 **잠든 상태로 첫 추천 요청을 던지면 폴링 버그처럼 보인다.**
개발 시작 전에 한 번 깨워두고 시작할 것.

```bash
curl https://musely-ai-core-mock.onrender.com/health
```

이게 응답하면 그때부터 15분간은 즉시 응답한다.

### 로컬에서 직접 돌리고 싶을 때 (선택)

콜드 스타트가 거슬리거나 오프라인에서 작업할 때. Docker Desktop만 있으면 된다.

```bash
git clone <레포 주소>
cd musely/ai-core
docker compose up --build
```

이때 `base-url`은 `http://localhost:8000`이 된다.

3주차에 docker-compose로 백엔드와 같이 띄울 때는 **`localhost`가 아니라 서비스 이름인
`http://ai-core:8000`** 이다. 컨테이너 안에서 `localhost`는 자기 자신이라 흔히 여기서
한 번 막힌다.

---

## 환경 변수

`.env.example`을 `.env`로 복사해서 쓴다. `.env`는 `.gitignore`에 있으니 커밋되지 않는다.
**LLM 키는 ai-core의 `.env`에만 두고 Spring Boot는 모른다.**

1주차 mock 서버는 `.env` 없이도 뜬다. `OPENAI_API_KEY`는 비어 있어도 되고, 2주차에
LLM을 실제로 호출하는 지점에서 `Settings.require_openai_key()`가 없으면 알려준다.
키가 없다고 서버가 아예 안 떠버리면 mock 개발이 막히기 때문에 이렇게 나눠뒀다.

| 변수 | 기본값 | 언제 쓰나 |
|---|---|---|
| `APP_ENV` / `LOG_LEVEL` | `local` / `INFO` | 지금 |
| `JOB_TIMEOUT_SECONDS` | `30` | 2주차 — job 상한. 없으면 무한 RUNNING |
| `JOB_TTL_MINUTES` | `30` | 2주차 — job 저장소 TTL |
| `OPENAI_API_KEY` | (빈값) | 2주차 |
| `LLM_MODEL` / `EMBEDDING_MODEL` | `gpt-4o-mini` / `text-embedding-3-small` | 2주차 |
| `VECTOR_STORE` | `chroma` | 2주차 — `chroma` \| `qdrant` |
| `CHROMA_PATH` / `QDRANT_URL` | `./chroma` / `http://localhost:6333` | 2주차 |

---

`--workers 1`은 **고정이다.** job 상태를 in-memory dict로 들고 있어서 워커가 2개 이상이면
`POST /jobs`를 처리한 프로세스와 `GET /jobs/{id}`를 처리하는 프로세스가 달라지고,
방금 만든 job이 404로 나온다. 운에 따라 성공하기도 해서 재현이 들쭉날쭉하다.
이벤트 루프가 I/O 대기 중 다른 요청을 처리하므로 데모 트래픽에선 병목이 아니다.

스키마 문서는 서버를 띄운 뒤 <http://localhost:8000/docs> 에서 볼 수 있다.

---

## 엔드포인트

| 메서드 | 경로 | 응답 |
|---|---|---|
| POST | `/jobs` | 202 `{jobId, status}` |
| GET | `/jobs/{jobId}` | 200 `{jobId, status, steps, result, error, elapsedMs}` |
| GET | `/health` | 200 `{status, indexedCounts}` |

상태 머신: `PENDING → RUNNING → DONE | FAILED`

---

## mock 제어 필드

`POST /jobs` 본문에 아래를 섞으면 지연·실패·결과 종류를 조종할 수 있다.
밑줄로 시작하는 필드는 **mock에만 있고 실제 서버에는 없다.** 실제 서버는 무시한다.

| 필드 | 기본값 | 설명 |
|---|---|---|
| `_mockDelay` | `5` | DONE까지 걸리는 초. 이 시간 동안 `steps`가 순차적으로 채워진다 |
| `_mockFail` | `null` | `TIMEOUT` \| `LLM_ERROR` \| `INTERNAL` 중 하나. delay 경과 후 FAILED로 끝난다 |
| `_mockFixture` | 트랙에 따라 자동 | `cosmetic_only` \| `fragrance_only` \| `both` \| `no_candidates` |

`_mock_delay` / `mockDelay` 같은 변형도 받는다.

### fixture별로 재현되는 화면 상태

| fixture | 기획서 화면 상태 |
|---|---|
| `cosmetic_only` | 화면 3 정상 (화장품 4건 + 주의사항 1건) |
| `fragrance_only` | 향수 섹션만 렌더링 (화장품 섹션은 비어 있어야 한다) |
| `both` | 양쪽 섹션 + `relaxationLevel: 1` → **완화 안내 배너** + `severity: avoid` 주의 카드 |
| `no_candidates` | 결과 0건 + `blockedBy`로 걸린 조건 표시 + 완화 배너 |

---

## 호출 예시 (PowerShell)

```powershell
# 1) 정상 — 5초 후 DONE
$body = @{ profileId = "p1"; track = "cosmetic"; skinType = "combination"
           concerns = @("모공","트러블"); avoidIngredients = @("알코올")
           currentActives = @("레티놀") } | ConvertTo-Json
$job = Invoke-RestMethod -Method Post http://localhost:8000/jobs -ContentType application/json -Body $body
$job.jobId

# 2) 폴링 — steps가 채워지는 걸 확인
Invoke-RestMethod "http://localhost:8000/jobs/$($job.jobId)" | ConvertTo-Json -Depth 6
```

```bash
# 느린 응답 — 로딩 화면을 20초 동안 붙잡아둔다
curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -d '{"profileId":"p1","track":"both","_mockDelay":20}'

# 타임아웃 화면
curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -d '{"profileId":"p1","track":"cosmetic","_mockDelay":3,"_mockFail":"TIMEOUT"}'

# 결과 0건 화면
curl -X POST localhost:8000/jobs -H 'Content-Type: application/json' \
  -d '{"profileId":"p1","track":"cosmetic","_mockFixture":"no_candidates"}'
```

---

## 에러 코드

`error.code`로 분기하고, 사용자에게는 기획서 09절 톤 가이드대로 번역해서 보여준다.

| 코드 | HTTP | 의미 | 프론트 처리 |
|---|---|---|---|
| `TIMEOUT` | 200 (job FAILED) | 30초 내 미완료 | "시간이 오래 걸리고 있어요" + 다시 시도 |
| `LLM_ERROR` | 200 (job FAILED) | 설명 생성 실패 | "문제가 생겼어요" + 다시 시도 |
| `INTERNAL` | 200 (job FAILED) | 그 외 내부 오류 | "문제가 생겼어요" + 다시 시도 |
| `JOB_NOT_FOUND` | 404 | 없는 jobId 또는 TTL(30분) 만료 | 폴링 중단 + 다시 시도 |
| `VALIDATION_ERROR` | 400 | 요청 형식 오류 | 개발 중에만 발생해야 한다 |

---

## 계약 관련 결정사항

플랜 문서에 애매하게 남아 있던 부분을 아래처럼 정했다. **바꾸려면 공유할 것.**

1. **와이어 포맷은 camelCase로 통일한다.** 파이썬 내부는 snake_case를 쓰고
   `CamelModel`(`alias_generator=to_camel`)이 변환한다. Jackson 기본값과 맞으므로
   Spring Boot DTO에 `@JsonProperty`를 붙일 필요가 없다.

2. **`steps`는 `result` 밖, job 응답 최상위에 둔다.** 단계 표시는 RUNNING 중에
   필요한데 `result`는 DONE에서야 채워지기 때문이다. `label`은 이미 사용자 언어로
   내려가므로 프론트에서 다시 매핑하지 않아도 된다.

3. **후보 0건은 `FAILED`가 아니라 `DONE` + 빈 배열이다.** 오류가 아니고, 프론트는
   화면 3을 렌더링해서 "어떤 조건이 걸렸는지"를 보여줘야 한다. FAILED로 주면
   "문제가 생겼어요"로 잘못 분기된다. 걸린 조건은 `blockedBy: string[]`로 내려가고,
   그대로 화면에 출력할 수 있는 문장이다. (이 경우 LLM을 호출하지 않으므로
   `summary`는 코드에서 만든 고정 문구다.)

4. **향수 노트는 `Candidate.notes`에 담는다.** `family / top / heart / base` 구조이고
   화장품 후보는 `null`이다. 화장품 카드 부제에 쓰는 `category`도 향수에서는 `null`.

5. **`relaxationLevel`은 `both`일 때 두 트랙 중 최대값이다.**

---

## 데이터 스키마 메모

`data/products.jsonl`이 화장품 카탈로그의 원본이고, 인덱싱 시점에 벡터DB 메타데이터로
매핑된다. 필터 설계에서 짚어둘 게 두 가지 있다.

**기피 성분 칩은 성분명이 아니라 분류다.** 화면 1의 칩은 "알코올 / 향료 / 파라벤 /
에센셜오일"인데 전성분 표기는 "에탄올", "세틸알코올" 등으로 갈린다. 특히
**세틸알코올·스테아릴알코올은 점도를 위한 지방 알코올이라 기피 대상이 아니다.**
전성분 문자열에 "알코올"이 있는지로 필터링하면 `p_007`(무향 수분 젤크림)처럼
멀쩡한 제품이 탈락한다. 그래서 분류 단위는 `alcohol_free` / `fragrance_free` /
`paraben_free` / `essential_oil_free` 불리언으로 미리 정규화해두고, 사용자가 직접
입력한 개별 성분만 `ingredients`로 따로 처리한다. `p_007`과 `p_012`는 이 오탐을
잡기 위한 테스트 케이스로 일부러 세틸알코올을 포함시켜 뒀다.

**`actives`는 충돌 검수용이다.** 제품이 담고 있는 활성 성분 키이고,
`conflict_rules.yaml`의 `pair` 키와 같은 어휘를 쓴다. 요청의 `currentActives`와
교차해서 `cautions`를 만든다.

**Chroma를 쓸 경우 벡터DB 선택을 다시 봐야 한다 (2주차 결정).** ai-core 플랜 07절의
`where["ingredients"] = {"$nin": [...]}`는 Chroma에서 그대로 돌지 않는다. Chroma
메타데이터 값은 문자열·숫자·불리언만 허용해서 리스트 필드를 담을 수 없기 때문이다.
위의 불리언 플래그만 쓰면 Chroma로도 충분하지만, 사용자가 직접 입력한 임의의 성분을
필터링하려면 배열 필드를 지원하는 Qdrant를 쓰거나 검색 후 파이썬에서 후처리해야 한다.

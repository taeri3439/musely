# musely — 빌드 플랜

2인 사이드 프로젝트 · 나연(AI) · 백엔드(백엔드) · 최종판

| 항목 | 내용 |
|---|---|
| 프로젝트명 | musely — `musely` |
| 팀 구성 | 나연(AI) · 백엔드(백엔드) |
| 기간 | 2~4주 (아래 로드맵은 4주 기준) |
| 백엔드 | Spring Boot + PostgreSQL |
| AI | FastAPI + LangGraph + 벡터DB |
| 통신 | 비동기 job + 폴링 (REST) |
| 프론트 | 뼈대 공동 설계 + 바이브코딩 |

> 관련 문서: **ai-core 플랜**(AI 서비스 상세), **기획서**(제품 정의 + 화면 구성)

---

## 00. 개요

화장품 성분 매칭과 향수 취향 매칭을 하나의 서비스로 묶는다. 둘 다 이미지 없이 텍스트로 돌아가고 "사용자 프로필 → 검색 → 근거 있는 추천"이라는 같은 패턴을 쓰기 때문에, 하나의 백엔드 + 하나의 AI 서비스 위에 두 개의 추천 트랙으로 구현한다.

**두 도메인을 묶는 근거** — 향수 노트가 top/heart/base로 층을 이루고, 스킨케어도 성분을 층층이 올린다. 층을 쌓는다는 같은 구조를 공유하기 때문에 하나의 서비스로 묶는 게 자연스럽다.

**이 프로젝트의 목적**은 결과물보다 두 사람의 학습에 있다.
- 나연: 멀티 트랙 오케스트레이션, 제약 조건 검색 설계, 비동기 job API, 평가 루프
- 백엔드: REST/CRUD 기본기, 외부 AI 서비스 연동, 폴링 클라이언트 구현, 타임아웃·에러 처리

---

## 01. 제품 한 줄 정의

> 내 피부 타입과 향 취향을 한 번 등록해두면, 화장품과 향수를 **이유와 함께** 추천받는 서비스.

"이유와 함께"가 핵심이다. 단순 추천 목록이 아니라 왜 이 제품인지, 어떤 성분을 피했는지, 뭘 주의해야 하는지를 같이 준다.

---

## 02. 시스템 아키텍처

```
 [프론트엔드]
      │ REST (폴링)
      ▼
 [Spring Boot API] ── PostgreSQL
      │  · CRUD: 프로필 / 화장품 / 향수 / 추천 / 피드백
      │  · 추천 job 생성 및 상태 관리
      │ REST (job 접수 + 폴링)
      ▼
 [ai-core: FastAPI]
      │  · 오케스트레이터 (LangGraph)
      │  ├─ 성분 매칭 에이전트 ──► 벡터DB (화장품·성분)
      │  ├─ 성분 충돌 검수 에이전트 ──► 충돌 규칙 테이블
      │  ├─ 향수 매칭 에이전트 ──► 벡터DB (향수·노트)
      │  └─ 설명 생성 에이전트 (공용)
      ▼
 [LLM API]  텍스트 생성 전용
```

**호출 방향은 한쪽으로만 흐른다.** 프론트 → 백엔드 → ai-core. ai-core는 백엔드를 호출하지 않고, 프론트는 ai-core를 직접 부르지 않는다(LLM API 키를 쓰는 서비스를 브라우저에 노출하지 않기 위해).

---

## 03. 통신 방식 — 비동기 job + 폴링 (확정)

추천 1건에 5~10초가 걸리므로, 사용자 요청을 붙잡아두지 않고 job으로 접수한다.

```
[FE]              [Spring Boot]                    [ai-core]
 ├─ POST /recommendations ──►│                          │
 │                           ├─ Job(PENDING) 저장        │
 │                           ├─ POST /jobs ────────────►│ 즉시 202 반환
 │◄─ 202 {jobId} ────────────┤◄── {aiJobId} ────────────┤ (백그라운드 처리 시작)
 │                           │                          │
 ├─ GET /jobs/{id} (1초마다)─►│                          │
 │                           ├─ PENDING이면 ai-core 조회 ─►│
 │◄─ {status: RUNNING} ──────┤◄── {status: RUNNING} ────┤
 │                           │                          │
 ├─ GET /jobs/{id} ─────────►├─ 조회 ──────────────────►│
 │                           │◄── {status: DONE, result}┤
 │                           ├─ Recommendation 영속화     │
 │◄─ {status: DONE, result} ─┤                          │
```

**게으른 릴레이 폴링** — Spring Boot는 스케줄러를 돌리지 않는다. 프론트가 물어볼 때만 ai-core에 물어보고, 결과가 있으면 그때 DB에 저장한다. 스케줄러도 콜백도 메시지 큐도 없다.

**왜 MQ가 아닌가** — MQ+콜백은 처리 시간이 길고(수십 초~분) 신뢰성이 중요한 워크로드에 맞는 패턴이다. 이번 규모(요청량 적음, 처리 5~10초)에선 브로커 운영 비용이 얻는 것보다 크고, 백엔드의 CRUD 학습 시간을 잠식한다.

**알려진 한계** — 아무도 폴링하지 않으면(사용자가 창을 닫으면) 결과가 영속화되지 않고 Job이 PENDING으로 남는다. 데모 수준에선 문제없고, 거슬리면 4주차에 `@Scheduled`로 미완료 Job을 훑는 로직을 붙이면 된다. **지금은 넣지 않는다.**

---

## 04. 백엔드 설계 (백엔드)

### 엔티티

| 엔티티 | 주요 필드 | 비고 |
|---|---|---|
| `User` | id, email, name, createdAt | 최소 인증용 |
| `BeautyProfile` | id, userId, skinType, concerns, avoidIngredients, currentActives, preferredScentFamilies, occasion, createdAt | 두 트랙 공용 프로필 |
| `Product` | id, name, brand, category, ingredients, description | 화장품 카탈로그 |
| `Fragrance` | id, name, brand, noteFamily, topNotes, heartNotes, baseNotes, description | 향수 카탈로그 |
| `RecommendationJob` | id, userId, profileId, track, status, aiJobId, recommendationId, createdAt, finishedAt | 폴링 대상 |
| `Recommendation` | id, jobId, userId, track, items(json), summary, cautions(json), relaxationLevel, createdAt | 최종 결과 |
| `Feedback` | id, recommendationId, rating, comment, createdAt | 선택 |

`RecommendationJob.status`: `PENDING → RUNNING → DONE | FAILED`

### 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/profiles` | 프로필 등록 |
| GET | `/api/profiles/{id}` | 프로필 조회 |
| PUT | `/api/profiles/{id}` | 프로필 수정 |
| POST | `/api/recommendations` | 추천 요청 → **202 + jobId** |
| GET | `/api/recommendations/jobs/{jobId}` | **폴링 대상** — 상태/결과 조회 |
| GET | `/api/recommendations/{id}` | 저장된 추천 결과 조회 |
| GET | `/api/recommendations?userId=` | 추천 히스토리 |
| POST · GET | `/api/products` | 화장품 카탈로그 CRUD |
| POST · GET | `/api/fragrances` | 향수 카탈로그 CRUD |
| POST | `/api/feedback` | 추천 평가 기록 |

추천 관련 2개만 ai-core를 호출하고 나머지는 순수 CRUD다. JPA·DTO·검증·페이징을 익히기에 충분한 양.

### ai-core 호출 예시

```java
// 1) 작업 접수
AiJobResponse res = webClient.post()
    .uri(aiCoreBaseUrl + "/jobs")
    .bodyValue(request)
    .retrieve().bodyToMono(AiJobResponse.class)
    .timeout(Duration.ofSeconds(5))
    .block();
job.setAiJobId(res.jobId());

// 2) 폴링 시 상태 조회
AiJobStatus status = webClient.get()
    .uri(aiCoreBaseUrl + "/jobs/" + job.getAiJobId())
    .retrieve().bodyToMono(AiJobStatus.class)
    .block();
```

`aiCoreBaseUrl`은 `application.yml` 설정값으로 빼고, docker-compose에서는 `http://ai-core:8000`. **LLM API 키는 ai-core의 `.env`에만 있고 Spring Boot는 모른다.**

---

## 05. AI 서비스 개요 (나연)

상세는 별도 문서(ai-core 플랜) 참고. 요약만 적으면:

| 에이전트 | 역할 |
|---|---|
| 성분 매칭 | 프로필 제약으로 필터를 만들고 화장품 벡터DB 검색 |
| 성분 충돌 검수 | 후보 조합의 성분 충돌을 규칙 테이블로 검수 |
| 향수 매칭 | 선호 계열·상황으로 향수 벡터DB 검색 |
| 설명 생성 (공용) | 두 트랙 결과를 근거와 함께 자연어로 설명 |

오케스트레이터는 요청의 `track` 값으로 분기해 해당 트랙을 타고, 마지막에 설명 생성으로 합류한다. `track: "both"`면 두 트랙을 병렬 실행한다.

**절대 양보하지 않는 규칙 두 가지**
1. 기피 성분·알러지 같은 하드 제약은 벡터 유사도가 아니라 **메타데이터 필터**로 건다. (임베딩은 부정을 표현하지 못한다)
2. 검색 결과가 0건이면 LLM을 호출하지 않는다. 없는 제품을 지어내는 것을 구조적으로 차단.

---

## 06. 프론트엔드

화면 4개. 상세 레이아웃과 상태 정의는 기획서 문서 참고.

1. 프로필 입력
2. 추천 진행(폴링 중) — 단계 표시
3. 추천 결과
4. 히스토리

뼈대(라우팅, API 클라이언트, 폴링 훅)는 둘이 같이 잡고, 화면 디테일과 스타일링은 바이브코딩으로 채운다. **프론트가 병목이 되면 둘 다 배우려던 걸 못 배운다.**

---

## 07. 4주 로드맵

| 주차 | 나연 (ai-core) | 백엔드 (백엔드) |
|---|---|---|
| **1주차**<br>계약 확정 | 계약 스키마 확정 → **mock 서버(지연·실패 시뮬레이션 포함)** → 데이터 수집 착수(50건) → 인덱싱 스크립트 | DB 스키마 확정 → Spring Boot 셋업 → 엔티티·리포지토리 |
| **2주차**<br>각자 구현 | 데이터 완성(150건) → 필터 빌더 → 4개 에이전트 구현 → job API 실동작 | CRUD 엔드포인트 전체 → mock 서버 연동 → job 생성·폴링 릴레이 구현 |
| **3주차**<br>통합 | 실제 벡터 검색 연동 → 프롬프트 튜닝 → 에러 코드 정리 → 백엔드 실연동 | 프론트 뼈대(공동) → 바이브코딩으로 4화면 → 로딩·에러 UI |
| **4주차**<br>마무리 | 골든셋 + 평가 스크립트 → `both` 병렬 처리 → 데모 리허설 | 버그 픽스 → README → (여유 시) 배포 |

**1주차에 mock 서버가 안 나오면 전체 일정이 밀린다.** 데이터 수집이 지루해서 미루게 되는데, mock만 먼저 띄워두면 백엔드가 3주차까지 안 막힌다.

**2주로 압축할 경우** — 1·2주차를 1주로, 3·4주차를 1주로 병합하고 향수 트랙을 잘라낸다.

---

## 08. 역할 분담

**나연 — ai-core 전체**
- LangGraph 오케스트레이터와 4개 에이전트 설계·구현
- 데이터 큐레이션, 임베딩, 벡터DB 2종 색인·검색
- job API 설계, mock 서버 제공, 계약 스키마 소유
- 프롬프트 설계, 평가 스크립트

**백엔드 — 백엔드 + 프론트 통합**
- Spring Boot 셋업, DB 스키마, JPA 엔티티
- CRUD 엔드포인트, 검증·예외 처리
- job 생성 및 ai-core 폴링 릴레이, 타임아웃·에러 처리
- 프론트엔드 API 연동, (여유 시) 배포

**공동** — 계약 스키마 리뷰, 프론트 뼈대 설계, 데모 시나리오

---

## 09. 데모 & 배포

`docker-compose`로 4개 컨테이너를 한 번에: `backend`(8080), `ai-core`(8000), `postgres`(5432), `frontend`(3000).

배포는 필수가 아니라 여유가 있을 때의 보너스. 최소 목표는 로컬에서 전체 플로우 데모. 시간이 남으면 백엔드는 Render/Railway, 프론트는 Vercel.

> `ai-core`는 반드시 `--workers 1`로 띄운다. 이유는 ai-core 플랜 문서 참고.

---

## 10. 리스크 & 팁

| 리스크 | 대응 |
|---|---|
| **1주차 mock 지연** | 데이터 수집보다 mock 서버를 먼저. 이게 밀리면 전부 밀린다 |
| **데이터 큐레이션 공수** | 예상의 1.5~2배 걸린다. 150건으로 규모를 고정하고 늘리지 말 것 |
| **폴링 무한 대기** | ai-core에 30초 타임아웃 상한, 프론트에 60초 상한. 양쪽 다 필요 |
| **범위 확장 유혹** | 에이전트 4개, 화면 4개에서 고정. "하나만 더"가 제일 위험하다 |
| **두 트랙 동시 진행** | 화장품 트랙 먼저 완성하고 향수를 붙인다. 둘 다 어설픈 게 최악 |
| **인증** | 이메일 기반 최소 구현 또는 고정 테스트 계정. 학습 목표가 아니다 |

**시간 없을 때 자르는 순서**: ① 히스토리 화면 → ② 피드백 기능 → ③ `both` 병렬 처리 → ④ 향수 트랙 전체

**절대 자르면 안 되는 것**: 하드 제약 필터, 0건일 때 LLM 건너뛰기, job 타임아웃 상한. 이게 빠지면 "그럴듯한데 틀린 추천을 하는 시스템"이 된다.

---
*musely 빌드 플랜 · 2026-09*

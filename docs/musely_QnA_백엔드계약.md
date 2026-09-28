# musely — QnA 백엔드 계약

ai-core `POST /qna`를 Spring이 어떻게 중계하면 되는지. 추천 job과 별개다.

> 확정 스키마는 `ai-core/app/schemas.py`의 `QnaRequest`, `QnaResponse`다. 와이어 포맷은 camelCase.

---

## 01. 경계

프론트는 ai-core를 직접 부르지 않는다. Spring이 기존 `ai-core.base-url`로 중계한다. QnA 결과는 저장하지 않는다.

| | 추천 | QnA |
|---|---|---|
| Spring | `POST /api/recommendations` → 202, 이후 폴링 | `POST /api/qna` → 200, 폴링 없음 |
| ai-core | `POST /jobs` | `POST /qna` |
| 타임아웃 | 접수만 하므로 5초 | 답까지 기다리므로 35초. ai-core 한도는 30초 |
| 저장 | `Recommendation` | 없음 |

LLM 키는 ai-core `.env`에만 있다. Spring은 모른다.

`base-url`은 추천과 같다. 로컬 `http://localhost:8000`, compose `http://ai-core:8000`.

---

## 02. 요청

`POST {base-url}/qna`

```json
{ "question": "레티놀이랑 BHA 같이 써도 돼요?" }
```

`question`은 1~300자. 비어 있거나 300자를 넘으면 422. Spring에서 먼저 거르는 편이 낫다.

---

## 03. 응답 200

`cautions`는 추천 결과의 주의 카드와 같은 DTO다. `intent`가 `pair`일 때만 채워진다.

```json
{
  "intent": "pair",
  "answer": "레티놀·BHA: 둘 다 각질 주기에 영향을 줘서 같이 쓰면 건조하거나 따가울 수 있어요. 다른 날에 나눠 쓰는 걸 권해요.",
  "sources": [
    {
      "kind": "rule",
      "id": "retinol_bha",
      "title": "레티놀·BHA",
      "source": "일반적 스킨케어 가이드라인",
      "score": null,
      "confidence": "medium"
    }
  ],
  "cautions": [
    {
      "pair": ["retinol", "bha"],
      "pairLabels": ["레티놀", "BHA"],
      "severity": "caution",
      "message": "둘 다 각질 주기에 영향을 줘서 같이 쓰면 건조하거나 따가울 수 있어요. 다른 날에 나눠 쓰는 걸 권해요.",
      "source": "일반적 스킨케어 가이드라인",
      "confidence": "medium"
    }
  ],
  "redirect": null,
  "usedLlm": false
}
```

| 필드 | 값 |
|---|---|
| `intent` | `faq` 설명 · `pair` 성분 조합 · `recommend` 추천 요청 · `unknown` 범위 밖 |
| `sources[].kind` | `faq` 또는 `rule` |
| `sources[].score` | FAQ일 때만 0~100. 규칙이면 `null` |
| `sources[].confidence` | 규칙일 때만 `low` · `medium` · `high` |
| `redirect` | 추천 요청이면 `"recommend"`, 아니면 `null` |
| `usedLlm` | FAQ 문장을 다듬었으면 `true`. 규칙·거절·범위 밖·원문 답은 `false` |

Spring은 `intent`를 해석하지 않고 본문을 그대로 반환하면 된다. `redirect`가 `"recommend"`일 때 추천 화면으로 보내는 것은 프론트 일이다. QnA는 제품을 골라 주지 않는다.

---

## 04. 에러

`code`는 최상단이 아니라 `detail` 안에 있다.

```json
{ "detail": { "code": "TIMEOUT", "message": "답변 생성이 시간 안에 끝나지 않았습니다" } }
```

| HTTP | `detail.code` | 언제 |
|---|---|---|
| 504 | `TIMEOUT` | 30초 안에 답이 안 끝남 |
| 500 | `INTERNAL` | 그 외 서버 오류 |
| 422 | 없음 | `question` 검증 실패. FastAPI 기본 validation body |

---

## 05. 헬스

`GET /health`의 `indexedCounts`에 `faq`가 추가됐다.

```json
{ "status": "ok", "indexedCounts": { "cosmetic": 42, "fragrance": 30, "faq": 27 } }
```

`faq`가 0이면 QnA 검색이 비어 있다. 인덱스는 ai-core에서 `python -m app.retrieval.index`로 만든다.

---

## 06. Spring 스케치

```java
@PostMapping("/api/qna")
public QnaResponse ask(@Valid @RequestBody QnaRequest request) {
    return webClient.post()
        .uri(aiCoreBaseUrl + "/qna")
        .bodyValue(request)
        .retrieve()
        .bodyToMono(QnaResponse.class)
        .timeout(Duration.ofSeconds(35))
        .block();
}
```

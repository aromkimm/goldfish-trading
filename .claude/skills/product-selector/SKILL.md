---
name: product-selector
description: 금붕상사 상품 추천 에이전트를 실행해 도매매 후보를 수집·추천하고(비교표) 추천 상품의 판매 가능 조건을 확인한다(판매 조건서). "상품 추천해줘", "후보 뽑아줘", "판매 가능 조건 확인" 같은 요청에 사용한다.
---

# 상품 추천 에이전트 실행

설계와 기준은 [에이전트 설계](../../../docs/product-selection-agent.md)와 [상품 선정 기준](../../../docs/product-selection.md)을 따른다. 이 파일은 실행 절차만 다룬다.

## 준비

- `.env`에 키가 있어야 한다(`.env.example` 참고). 비어 있으면 실행하지 말고 어떤 키가 필요한지 알린다. 키 값은 출력·기록하지 않는다.
- 명령은 저장소 루트에서 `python3 -m selector <명령>`으로 실행한다. 표준 라이브러리만 쓴다.
- 네이버쇼핑은 크롤링하거나 브라우저로 대신 확인하지 않는다. 경쟁가·판매자 수는 사람이 확인한다.

## 절차

1. `search --kw <검색어>` 또는 `--ca <카테고리>`로 후보를 추가한다. 검색어는 사용자가 정하거나, 정하지 않았으면 제안하고 확인받는다.
2. `detail`로 상세를 받고 규칙 제외를 적용한다. 매일 실행할 때는 `detail --refresh`로 변동성 스냅샷을 쌓는다.
3. `triage-export` → `data/llm/triage_pending.jsonl`의 각 줄을 판정해 `data/llm/triage_done.jsonl`에 쓴다 → `triage-import data/llm/triage_done.jsonl`.
4. `measure`로 대표 키워드 검색량을 수집한다.
5. `manual-export`로 `data/manual/check-<날짜>.html`을 만들어 사용자에게 열어 보라고 안내한다. 사용자가 입력 후 'CSV 저장'한 파일 경로를 받으면 `manual-import <경로>`.
6. `review-export --top 10` → 각 줄을 검토해 `data/llm/review_done.jsonl`에 쓴다 → `review-import data/llm/review_done.jsonl`.
7. `report`로 `data/reports/<날짜>-candidates.md·csv`를 만들고 요약 보고한다.
8. `verify-export`로 `data/verify/verify-<날짜>.html`을 만들어 사용자에게 판매 가능 조건 확인을 안내한다. 받은 CSV 경로로 `verify-import <경로>` → `data/reports/<날짜>-sell-conditions.md`. 반려된 상품과 사유를 보고한다. 판매 조건서가 최종 산출물이며 등록·운영은 이 스킬 범위가 아니다. 통과 상품이 부족하면 `verify-export --nos`로 비교표의 다음 후보를 확인한다.

실패 건은 건너뛰고 출력에 남는다. 실패 수와 원인을 보고에 포함한다.

## triage 판정 (3단계)

각 줄에 `{"no": ..., "exclude": null 또는 "사유", "keywords": [...]}`를 쓴다.

- 제외: 상품 선정 기준의 초기 제외 기준·가치관 필터에 해당하면 사유를 쓴다. 규칙이 못 거른 경우를 본다 — 인증이 필요한 전기·유아·화장품·식품류, 사이즈·색상 선택이 핵심인 상품, 캐릭터·라이선스 굿즈, 일회용, 다이어트·건강 과장. 확실하지 않으면 제외하지 말고 키워드를 쓰되 review에서 리스크로 남긴다.
- 키워드: 고객이 네이버 쇼핑에서 실제로 칠 검색어 1~3개. 첫 번째가 지표 계산에 쓰이므로 가장 대표적인 것을 둔다. 도매 상품명의 수량·모델명·과장 문구는 뺀다.

## review 검토 (6단계)

각 줄에 `{"no": ..., "rationale": "...", "risks": "...", "unknowns": "..."}`를 쓴다.

- 입력된 지표만 근거로 쓴다. 새 점수나 판매량 예측을 만들지 않는다.
- risks: 수동 확인 메모, 이미지 사용 불허, KC 인증, 최저판매준수가 적용, 배송비 모름, 시즌성, 반품 부담 등.
- unknowns: `모름`으로 남은 지표와 확인 방법.

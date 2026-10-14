---
name: product-selector
description: 금붕상사 상품 추천 에이전트를 실행해 도매매 후보를 수집·추천하고(비교표) 추천 상품의 판매 가능 조건을 확인한다(판매 조건서). "상품 추천해줘", "후보 뽑아줘", "판매 가능 조건 확인" 같은 요청에 사용한다.
---

# 상품 추천 에이전트 실행

설계와 기준은 [에이전트 설계](../../../docs/product-selection-agent.md)와 [상품 선정 기준](../../../docs/product-selection.md)을 따른다. 이 파일은 실행 절차만 다룬다.

## 준비

- `.env`에 키가 있어야 한다(`.env.example` 참고). 비어 있으면 실행하지 말고 어떤 키가 필요한지 알린다. 키 값은 출력·기록하지 않는다.
- 명령은 저장소 루트에서 `.venv/bin/python -m selector <명령>`으로 실행한다. 처음이면 `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- 11번가 키는 등록한 IP에서만 동작한다. 실행 위치가 바뀌어 거부되면 11번가 API 관리에서 IP를 추가하라고 안내한다.
- 추천 파이프라인의 네이버쇼핑 표본 검증은 사용자 제공 화면과 `manual-export`·`manual-import`를 사용한다. 크롤링하거나 접근 차단을 다른 도구로 우회하지 않는다.

## 절차

1. `search --kw <검색어>` 또는 `--ca <카테고리>`로 후보를 추가한다. 검색어는 사용자가 정하거나, 정하지 않았으면 제안하고 확인받는다.
2. `detail`로 상세를 받고 규칙 제외를 적용한다. 매일 실행할 때는 `detail --refresh`로 변동성 스냅샷을 쌓는다.
3. `triage-export` → `data/llm/triage_pending.jsonl`의 각 줄을 판정해 `data/llm/triage_done.jsonl`에 쓴다 → `triage-import data/llm/triage_done.jsonl`.
4. `measure`로 대표 키워드 검색량을, `trend`로 검색어 트렌드·쇼핑 클릭 추이·블로그·카페 지표를 수집한다.
5. `compete`로 11번가 경쟁·가격을, `catalog`로 네이버 카탈로그 참고 지표(커머스API)를 수집한다. 네이버 대비 검증 표본이 필요할 때만 `manual-export`·`manual-import`를 쓴다.
6. `review-export --top <검토할 추천 수>`(전체 추천을 검토하려면 `config/selector.json`의 `scoring.recommend_top` 사용) → 각 줄을 검토해 `data/llm/review_done.jsonl`에 쓴다 → `review-import data/llm/review_done.jsonl`.
7. `report`로 `data/reports/<날짜>-candidates.md·csv`를 만들고 요약 보고한다.
8. 추천 목록과 검토 결과를 대조해 인계할 후보가 모두 검토됐는지 확인한다. `verify-export` 자체는 검토 완료를 검사하지 않는다. `verify-export`로 `data/verify/verify-<날짜>.html`을 만들어 사용자에게 판매 가능 조건 확인을 안내한다. 받은 CSV 경로로 `verify-import <경로>` → `data/reports/<날짜>-sell-conditions.md`. 반려된 상품과 사유를 보고한다. 판매 조건서가 최종 산출물이며 등록·운영은 이 스킬 범위가 아니다. 통과 상품이 부족하면 `verify-export --nos <상품번호,상품번호>`로 검토한 다음 후보를 지정한다.

`detail`·`compete`는 상품별 실패를 건너뛰지만 다른 API 명령은 중간에 중단될 수 있다. 종료 코드·실패 출력·DB 상태를 확인하고 완료·실패·미처리 범위를 구분해 보고한다. 중단된 실행을 전체 완료로 간주하지 않는다.

## triage 판정 (3단계)

각 줄에 `{"no": ..., "exclude": null 또는 "사유", "keywords": [...]}`를 쓴다.

- 제외: 상품 선정 기준의 초기 제외 기준·가치관 필터에 해당하면 사유를 쓴다. 규칙이 놓친 사례를 [제외 기준](../../../docs/product-selection.md#대상과-제외-기준)과 대조한다. 확실하지 않으면 제외하지 말고 키워드를 쓰되 review에서 리스크로 남긴다.
- 키워드: 고객이 네이버 쇼핑에서 실제로 칠 검색어 1~3개. 첫 번째가 지표 계산에 쓰이므로 가장 대표적인 것을 둔다. 도매 상품명의 수량·모델명·과장 문구는 뺀다.

## review 검토 (6단계)

먼저 대표 키워드를 확인한다. 각 줄의 `keyword_names`(11번가 키워드 검색 상위 상품명)가 상품과 다른 유형이면 검색 의도가 어긋난 것이다. 대체 키워드의 검색량을 확인해 `rekeyword <상품번호> "키워드1,키워드2" --reason "근거"`로 바꾸고 `measure` → `trend` → `compete` → `review-export --top <검토할 추천 수>`를 다시 실행한다. 새 `review_pending.jsonl`로 검토하고 `review-import` → `report`로 반영한다. 키워드 변경은 기존 review를 자동 삭제하지 않으므로 이전 검토를 새 지표의 검토로 재사용하지 않는다.

각 줄에 `{"no": ..., "rationale": "...", "risks": "...", "unknowns": "..."}`를 쓴다.

- 입력된 지표만 근거로 쓴다. 새 점수나 판매량 예측을 만들지 않는다.
- risks: 같은 유형 판매자가 많음, 가격비교 묶음 가능성(같은 사진 판매자 다수), 진입 장벽 모름, 이미지 사용 불허, KC 인증, 최저판매준수가 적용, 배송비 모름, 시즌성, 반품 부담 등.
- unknowns: `모름`으로 남은 지표와 확인 방법.

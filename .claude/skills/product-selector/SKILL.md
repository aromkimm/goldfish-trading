---
name: product-selector
description: 금붕상사 후보 선별 에이전트를 실행해 도매매 후보를 수집·선별하고(선별표) 선별 통과 상품의 판매 가능 조건을 확인한다(판매 조건서). "후보 뽑아줘", "팔 만한 상품 후보 찾아줘", "상품 추천해줘", "판매 가능 조건 확인" 같은 요청에 사용한다.
---

# 후보 선별 에이전트 실행

설계와 기준은 [에이전트 설계](../../../docs/product-selection-agent.md)와 [상품 선정 기준](../../../docs/product-selection.md)을 따른다. 이 파일은 실행 절차만 다룬다.

## 준비

- `.env`에 키가 있어야 한다(`.env.example` 참고). 비어 있으면 실행하지 말고 어떤 키가 필요한지 알린다. 키 값은 출력·기록하지 않는다.
- 명령은 저장소 루트에서 `.venv/bin/python -m selector <명령>`으로 실행한다. 처음이면 `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
- 기존 후보와 섞지 않을 평가 배치는 `selector --data-dir data/<폴더> <명령>`처럼 하위 명령 앞에 `--data-dir`를 두고, `search`에 `--skip-db data/selector.db <앞선 평가 배치 DB…>`를 준다(여러 경로 가능). DB와 llm·manual·verify·reports 파일이 그 폴더에 따로 생기고 지정한 DB들에 있던 상품번호는 추가되지 않는다. 같은 DB에 섞으면 평가 표본을 다시 뽑거나 재현할 수 없다.
- 11번가 키는 등록한 IP에서만 동작한다. 실행 위치가 바뀌어 거부되면 11번가 API 관리에서 IP를 추가하라고 안내한다.
- 네이버쇼핑 확인은 사용자 제공 화면과 `manual-export`(기본: 선별 통과 후보 전부)·`manual-import`를 사용한다. 크롤링하거나 접근 차단을 다른 도구로 우회하지 않는다. 사용자가 검색 결과 첫 페이지 캡처를 주면 도매 썸네일과 같은 사진의 판매가·배송비를 판독하고, 결제 총액이 가장 낮은 몇 곳만 수량·옵션·배송비·필수 추가옵션·URL 확인을 요청한다. `same_prices`에는 상품가+배송비 결제 총액을 넣는다.

## 절차

1. `search --kw <검색어>` 또는 `--ca <카테고리>`로 후보를 추가한다. 검색어는 사용자가 정하거나, 정하지 않았으면 제안하고 확인받는다.
2. `detail`로 상세를 받고 규칙 제외를 적용한다. 매일 실행할 때는 `detail --refresh`로 변동성 스냅샷을 쌓는다.
3. `triage-export` → `data/llm/triage_pending.jsonl`의 각 줄을 판정해 `data/llm/triage_done.jsonl`에 쓴다 → `triage-import data/llm/triage_done.jsonl`.
4. `measure`로 대표 키워드 검색량을, `trend`로 검색어 트렌드·쇼핑 클릭 추이·블로그·카페 지표를 수집한다.
5. `compete`로 11번가 경쟁·가격을, `catalog`로 네이버 카탈로그 참고 지표(커머스API)를 수집한다. 선별표에 `경쟁가 비교 조건 미확인`이 있으면 상품 단위 기록이 없는 이전 수집분이므로 `compete --redo`로 다시 수집한다. 선별 통과 후보의 네이버 가격·판매처는 `manual-export`·`manual-import`로 확인하고, 표본에서 내린 상품별 결론은 `judge <상품번호> <판정> --reason "근거" --source "자료·판정자"`로 저장한다(판정: `판매 실험 검토 가능`·`추가 확인`·`제외`).
6. `review-export`로 현재 근거로 검토되지 않은 선별 통과 후보를 전부 내보낸다(`--top`으로 개수 제한 가능) → 각 줄의 `evidence_at`·`decision_revision`을 보존해 검토 결과를 `data/llm/review_done.jsonl`에 쓴다 → `review-import data/llm/review_done.jsonl`.
7. `report`로 `data/reports/<날짜>-candidates.md·csv`(선별표)를 만들고 요약 보고한다. 순위·추천으로 보고하지 않는다.
8. `verify-export`로 출력된 `data/verify/verify-<실행ID>.html`에서 판매 가능 조건을 확인한다. `--nos`를 지정해도 현재 선별·검토 통과가 필요하다. 받은 CSV의 `batch_id`를 유지한 채 `verify-import <경로>`로 반영한다. 결과는 출력된 `data/reports/<날짜>-<실행ID>-sell-conditions.md`에서 확인한다. 두 명령 모두 도매 정보를 재조회하며 [유효성 검사](../../../docs/product-selection-agent.md#검토와-인계의-유효성)에 실패하면 인계를 중단한다. 이때 `report`로 탈락·변경 사유를 보고, 통과 후보는 `review-export`부터 재검토한 뒤 새 화면에서 입력을 재확인한다. 이전 검토 파일의 식별값만 바꿔 재사용하지 않는다. 반려 상품과 사유를 보고하며 판매 조건서 이후 등록·운영은 이 스킬 범위가 아니다.

`detail`·`compete`는 상품별 실패를 건너뛰지만 다른 API 명령은 중간에 중단될 수 있다. 종료 코드·실패 출력·DB 상태를 확인하고 완료·실패·미처리 범위를 구분해 보고한다. 중단된 실행을 전체 완료로 간주하지 않는다.

## triage 판정 (3단계)

각 줄에 `{"no": ..., "exclude": null 또는 "사유", "keywords": [...]}`를 쓴다.

- 제외: 상품 선정 기준의 초기 제외 기준·가치관 필터에 해당하면 사유를 쓴다. 규칙이 놓친 사례를 [제외 기준](../../../docs/product-selection.md#대상과-제외-기준)과 대조한다. 확실하지 않으면 제외하지 말고 키워드를 쓰되 review에서 리스크로 남긴다.
- 키워드: 고객이 네이버 쇼핑에서 실제로 칠 검색어 1~3개. 첫 번째가 지표 계산에 쓰이므로 가장 대표적인 것을 둔다. 도매 상품명의 수량·모델명·과장 문구는 뺀다.

## review 검토 (7단계)

먼저 대표 키워드를 확인한다. 각 줄의 `keyword_names`(11번가 키워드 검색 상위 상품명)가 상품과 다른 유형이면 검색 의도가 어긋난 것이다. 대체 키워드의 검색량을 확인해 `rekeyword <상품번호> "키워드1,키워드2" --reason "근거"`로 바꾸고 `measure` → `trend` → `compete` → `review-export`를 다시 실행한다. 새 `review_pending.jsonl`로 검토하고 `review-import` → `report`로 반영한다. 검토 입력이 바뀌면 이전 검토는 유효하지 않다. 새 `judge` 판정도 기존 검토를 무효화한다. 누락·오래된 `evidence_at`·`decision_revision`의 반영이 거부되면 새로 내보낸 자료를 검토한다.

다음으로 `compared_items`(경쟁가 계산에 쓴 같은 사진·같은 유형 상품명·가격·배송)와 `info_duty`(상품정보고시의 소재·크기·구성 등)를 대조한다. 경쟁 상품이 규격·용도·구성이 다른 상품이거나 상품명과 고시가 충돌하면(예: 상품명은 아크릴, 고시 소재는 PET) 마진·수요 근거로 쓰지 않고 판정에 반영한다. `price_dispersion`·`sensitive_to`·옵션 추가금·반품 부담 표시도 확인한다. 관측 비교가, 보정 추정가와 마진, 준수가 적용 시나리오와 마진을 구분하고 시나리오 상향을 시장의 가격 수용 근거로 해석하지 않는다.

각 줄에 `{"no": ..., "evidence_at": "내보낸 식별값 그대로", "decision_revision": 내보낸_판정버전, "verdict": "판매 실험 검토 가능|추가 확인|제외", "rationale": "...", "risks": "...", "unknowns": "..."}`를 쓴다. 판정 기준은 [후보 선별 평가](../../../docs/product-selection.md#판정과-보고)를 따르고, 판매 조건 확인 전에는 `판매 실험 검토 가능`을 쓰지 않는다. `제외`는 선별에서 빠지고 새 판정 전까지 다시 통과되지 않는다.

- 입력된 지표만 근거로 쓴다. 새 점수나 판매량 예측을 만들지 않는다.
- risks: 같은 유형 판매자가 많음, 가격비교 묶음 가능성(같은 사진 판매자 다수), 진입 장벽 모름, 이미지 사용 불허, KC 인증, 최저판매준수가 적용, 배송비 모름, 시즌성, 반품 부담 등.
- unknowns: `모름`으로 남은 지표와 확인 방법.

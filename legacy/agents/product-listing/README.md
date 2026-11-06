# 보관 등록 도구

국내 등록 자료의 `listing-2` 입력을 검사·출력하는 비활성 Python 도구다. 현재 사업의 등록 실행 지침은 [등록 원칙](../../../docs/product-listing-principles.md)을 따른다. 이 구현은 자동 게시·모델 API 호출·Amazon 연동을 하지 않는다.

## 사용하기

저장소 루트에서 Python 3.10 이상으로 실행한다. 등록 CLI 자체는 외부 패키지 설치가 필요 없다. 입력 데이터의 정의는 [데이터 계약](data-contract.md), 합성 예시는 [draft.json](examples/format-demo/draft.json)에 있다. 합성 예시·시험 입력은 실제 상품 사실·권한·판매 승인이 아니다.

```sh
python3 legacy/agents/product-listing/run.py --help
python3 legacy/agents/product-listing/run.py prepare brief.json --out records/artifacts/product-listing-runs/item-work
python3 legacy/agents/product-listing/run.py validate records/artifacts/product-listing-runs/item-work/draft.json
python3 legacy/agents/product-listing/run.py build records/artifacts/product-listing-runs/item-work/draft.json --out records/artifacts/product-listing-runs/item-v1
python3 legacy/agents/product-listing/run.py check records/artifacts/product-listing-runs/item-v1
python3 legacy/agents/product-listing/run.py review-template records/artifacts/product-listing-runs/item-v1
```

`brief.json`에는 `product_id`, 판매 범위 `scope`, `sources`(출처 ID·location)가 필요하다. prepare는 원문을 조회하지 않는다. 새 작업마다 새 출력 폴더를 사용한다. 수정은 입력을 고친 뒤 `build --previous`로 새 버전을 생성하며 기존 패키지를 직접 편집하지 않는다.

## 산출물과 검수

`listing-package.json`이 상품 사실·출처·판단·검수의 버전 원본이다. 파생 출력은 `proposal.md`, `fields.md`, `preview.html`, `customer.html`, `image-tasks.md`, `review.md`다. 부분 초안은 고객용 출력·승인이 차단될 수 있다.

검수는 판매 대상 일치(`identity`), 사실(`facts`), 검색/경쟁 판단(`strategy`), 권한(`rights`), PC/모바일(`desktop`/`mobile`), 실제 판매 채널(`channel`)로 나눈다. 직접 수행한 범위만 pass/fail로 기록하고 미실행은 not_run이다. 로컬 화면 확인을 채널 검수로 승계하지 않는다.

`review <폴더> --report <검수 JSON>`은 검사 근거를 적용한다. `approve <폴더> --reviewer <검토자> --revision <버전> [--decision <판단>]`은 해당 버전의 명시적 승인 뒤에만 기록하며 실제 게시 기능이 아니다. 게시 차단을 해제하려고 모름을 확인으로 바꾸지 않는다.

## 구조와 검증

`run.py`는 CLI, `bundle.py`는 입력 준비·버전·검수, `validation.py`는 계약 검사, `render.py`는 출력, `images.py`는 이미지 크기 확인을 담당한다. `tests/fixtures/`는 과거 조사 데이터의 보존 시험 입력이며 최신 판매 자료가 아니다.

```sh
python3 -m unittest discover -s legacy/agents/product-listing/tests
```

기록 원본은 [등록 검증 근거](../../../records/2026-10-13-listing-agent-implementation.md), 상품별 실행 산출물은 [records/artifacts](../../../records/artifacts/product-listing-runs/)에 있다. 구조·해시 검사는 사실의 진위·판매 효과·실제 권한을 검증하지 않는다.

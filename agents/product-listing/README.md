# 판매 등록 에이전트

상품 URL·자료와 판매할 옵션을 주면 대화형 에이전트가 검색 의도·경쟁 조건을 조사하고 등록 자료를 작성한다. `tools.py`는 근거 연결 검사·출력·버전별 검수 기록을 담당한다. 별도 모델 API 없이 현재 대화와 로컬 Python으로 실행한다.

## 사용하기

이 프로젝트에서 다음처럼 요청한다.

> 판매 등록 에이전트로 이 상품의 등록 자료를 만들어줘. 상품: [URL 또는 파일]. 판매 옵션: [규격·색상·구성].

에이전트는 [작업 절차](workflow.md)를 수행하고 필요한 자료만 추가로 묻는다. 사용자가 JSON을 직접 작성할 필요는 없다. URL 접근이 불가능해도 제공 자료로 부분 초안을 만들 수 있다. 도입 제목·사진·이미지 문구 처리는 [공통 포맷 기준](../../docs/product-listing-principles.md#상세페이지-포맷)을 적용한다. 사진 포함 내부 검토 시안과 게시 전 확인 사항은 [등록 자료 작성 절차](workflow.md#등록-자료-작성)에 따라 함께 제공한다. 아래 파일 표는 기본 CLI 패키지이며 별도 내부 시안은 같은 게시 준비 상태를 유지한다.

| 결과 파일 | 내용 |
| --- | --- |
| `proposal.md` | 상품명·태그 후보의 검색량·실제 경쟁·대안 비교와 채택/보류/제외 이유, 구매 질문·불확실성 |
| `fields.md` | 등록 입력값과 내부 확인 메모 |
| `preview.html` | 상태·미완성 자산 표시를 포함한 내부 상세 미리보기 |
| `customer.html` | 내부 메모 없는 고객용 화면. 부분 초안이면 제공 불가 안내 |
| `image-tasks.md` | 이미지 채택·편집·확보 작업과 권한 |
| `review.md` | 확인 과제·검사 증거·게시 차단·승인·작업시간 |
| `listing-package.json` | 출처·사실·판단·출력의 같은 버전 관리 원본 |

[가상 상품 미리보기](examples/format-demo/bundle/preview.html)와 [제안서](examples/format-demo/bundle/proposal.md)는 동작·포맷 예시다. 실제 상품을 조사하거나 게시 승인한 결과가 아니다. 실제 채널에 옮길 때는 확인된 필드·문구·허용 이미지만 사용하며 HTML 전체를 붙여 넣지 않는다.

## 실행 명령

프로젝트 루트에서 Python 3.10 이상을 사용한다. 외부 패키지 설치가 필요 없다. 아래 경로는 실행 예시이며 출력 폴더는 매번 새 이름으로 정한다.

```sh
python3 agents/product-listing/tools.py prepare brief.json --out agents/product-listing/runs/item-work
```

brief.json의 형식은 다음과 같다. 로컬 자료는 브리프 폴더 안의 상대 경로와 확인일을 추가한다. URL은 prepare가 조회하지 않으므로 에이전트가 원문을 확인해야 한다.

```json
{
  "product_id": "item-id",
  "scope": "판매할 규격·색상·구성",
  "sources": [{"id": "supplier", "location": "공급처 상품 URL"}]
}
```

준비된 request.md와 [데이터 계약](contract.md)에 따라 에이전트가 draft.json을 채운 다음 실행한다.

```sh
python3 agents/product-listing/tools.py validate agents/product-listing/runs/item-work/draft.json
python3 agents/product-listing/tools.py build agents/product-listing/runs/item-work/draft.json --out agents/product-listing/runs/item-v1
python3 agents/product-listing/tools.py check agents/product-listing/runs/item-v1
python3 agents/product-listing/tools.py review-template agents/product-listing/runs/item-v1 > agents/product-listing/runs/item-review.json
```

실제 검사 결과와 증거를 item-review.json에 기록한 뒤 적용한다. 모든 검사를 임의로 pass로 채우지 않는다.

```sh
python3 agents/product-listing/tools.py review agents/product-listing/runs/item-v1 --report agents/product-listing/runs/item-review.json
python3 agents/product-listing/tools.py check agents/product-listing/runs/item-v1
```

`approve <폴더> --reviewer <검토자> --revision <현재 버전> [--decision <판매 실험 판단>]`은 사람의 명시적 해당 버전 승인 후에만 사용한다. 필수 차단이 있으면 거부하며 전략이 가설 검증/상품 재검토 상태이면 decision이 필요하다. 내용 수정은 새 폴더로 build하고 `--previous <이전 결과 폴더>`를 연결한다. 검수·승인을 다시 수행한다.

## 구조와 검증 범위

- [설계](design.md): 역할·처리 책임·품질 기준. [공통 원칙](../../docs/product-listing-principles.md): 검색 전략과 상세페이지 포맷.
- `listing_agent/schema.py`: 새 계약·참조·준비 상태 검사. `package.py`: 자료 준비·버전·검수·승인. `render.py`: 문서·HTML 출력. `cli.py`: 명령 연결.
- `listing_tools/`, `tests/test_tools.py`, `examples/23824864/`는 보존된 이전 도구·회귀 자료다. 기본 tools.py는 이를 호출하지 않으며 이전 JSON 계약을 자동 변환하지 않는다. 과거 결과는 [기록](../../records/2026-10-12-listing-mvp.md)에 있다.
- `tests/test_agent.py`는 새 계약의 합성 시험이며 [구현 검증 기록](../../records/2026-10-13-listing-agent-implementation.md)에서 실행 결과와 범위를 확인한다. `runs/`는 Git 제외 작업 자료다.

```sh
python3 -m unittest discover -s agents/product-listing/tests -v
```

자동 테스트는 사실의 진위·검색 전략의 효과·이미지 실제 권한·사용자 신원을 인증하지 않는다. 실제 상품 실행과 판매자센터 검수·업무시간·판매 효과 검증은 별도다. 현재 사업 상태와 담당은 [STATUS.md](../../STATUS.md)에서 관리한다.

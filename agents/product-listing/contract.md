# 판매 등록 데이터 계약

`tools.py`의 `listing-2` 계약이다. JSON은 상품별 관리 원본이며 Markdown·HTML은 동일 버전의 파생본이다. 원칙은 [공통 기준](../../docs/product-listing-principles.md), 실행은 [작업 절차](workflow.md)를 따른다. 전체 입력 예시는 [가상 상품 초안](examples/format-demo/draft.json)이다. 예시의 상품값·채널 목록·권한 표시는 합성 테스트 설정이므로 실제 상품에 복사하지 않는다.

## 작성하는 데이터

| 키 | 필수 내용 |
| --- | --- |
| `schema_version`, `package_id`, `scope`, `scope_source_refs` | `listing-2`, 상품 ID, 판매 옵션·구성 범위, 범위의 출처 ID |
| `sources[]` | `id`, `kind`, `location`, `observed_at`, `scope`, `access`, `note`. 로컬 원문은 `local_path`, `sha256` 추가 |
| `facts[]` | `id`, `value`, `status`, `numeric_status`, `source_refs`, `locator`, `scope`, `note`, `issue_refs` |
| `observations[]` | `id`, `query`, `source_refs`, `observed_at`, `surface`, `device`, `login`, `sampling`, `ad`, `competitors[]` |
| `strategy` | `status`, `summary`, `reason_to_choose`, `counter_evidence`, `uncertainties`, `queries[]` |
| `questions[]` | `id`, `question`, `priority`, `reason`, `source_refs`, `hypothesis`(불리언), `fact_refs`, `issue_refs` |
| `fields[]` | `id`, `label`, `value`, `status`, `fact_refs`, `query_refs`, `issue_refs`, `scope`, `note` |
| `channel` | `status`, `category_field_id`, `source_refs`, `required_field_ids`, `note` |
| `assets[]` | `id`, `path`, `sha256`, `source_refs`, `rights`, `rights_source_refs`, `scope`, `alt`, `task`, `instruction`, `status`, `derived_from` |
| `content` | `main_asset_id`와 표시 순서대로 구성한 `blocks[]` |
| `issues[]` | `id`, `severity`, `status`, `question`, `resolve_by`, `impact`, `owner`, `source_refs`. 해결 시 `resolution` 추가 |
| `timing` | `unit: minutes`, `preparation`, `research`, `review`, `correction`, `entry`, `manual_baseline`. 미측정은 null |

본문·입력값·규격 값은 단위가 드러나는 문자열로 쓴다. 태그 등 복수 입력값은 문자열 배열을 사용할 수 있다. 사실의 수치 구분은 `confirmed`(확인), `estimated`(가정·산식·근거를 note에 명시), `unknown`(모름), `not_numeric`(수치 아님)이다. 사용자 제공 계획값은 실적과 구분해 note에 표시한다. 기여이익 산식·입력 근거도 사실로 기록하며 추정 입력을 쓰면 결과를 추정으로 표시한다.

## 출처와 사실

- `sources.kind`: `supplier`, `provided`, `verified`, `channel`, `search`, `competitor`, `reference`.
- `sources.access`: `available`, `blocked`, `not_checked`. 읽은 자료는 ISO 확인일·시각을 기록하고, 미조회는 날짜를 null로 둘 수 있다. URL과 원문 위치·적용 옵션·접근 제한을 남긴다.
- `facts.status`: `supplier_stated`, `user_provided`, `verified`, `conflict`, `unknown`. 모름은 value=null 및 확인 과제, 충돌은 충돌 내용과 확인 과제를 연결한다.
- 준비된 입력값·콘텐츠·적합성 판단에는 미확인·충돌 사실을 사용할 수 없다. 경쟁·검색·포맷 자료만으로 우리 상품을 주장할 수 없다. 사실의 실제 진위·동일 상품 여부·주장의 강도는 별도 의미 검수 대상이다.
- 로컬 자료는 패키지의 `sources/`, `assets/` 아래에만 두며 심볼릭 링크·상위 경로·절대 경로를 허용하지 않는다. 해시가 바뀌면 재작성·재빌드한다.

## 검색과 경쟁

`strategy.queries[]`는 `id`, `query`, `origin`(`observed`/`hypothesis`), `intent`, `decision`(`target`/`exclude`/`hold`), `fit`(`match`/`mismatch`/`unknown`), `reason`, `fact_refs`, `observation_refs`, `demand`를 담는다. 불일치 검색어는 제외하고, 관측어에는 관측 참조를 연결한다. 등록 필드의 query_refs는 채택 검색어만 가리킨다. `supported`는 적합한 관측 검색어가 있어야 하지만 판매 성과를 뜻하지 않는다.

[후보 비교 절차](workflow.md#조사와-방향-판단)의 결과는 기존 필드에 다음처럼 작성한다. 이 내용은 에이전트의 의미 검수 대상이며 JSON 구조 검사만으로 강제되지는 않는다.

- `queries[].reason`: 사용처(상품명/태그), 상품 적합성, 경쟁 표현·검색 의도와 관측 참조, 기존안/대안 대비 장단점, 채택·제외·보류 이유. 태그사전 확인 출처 ID와 결과도 기재한다.
- `demand`: 정확한 합계를 알면 value에 기록하고, PC·모바일 원문과 합산식은 note에 남긴다. `<10`처럼 정확한 합계가 없으면 value=null/status=unknown으로 두되 확인한 범위값·출처·기간·집계 정의는 보존한다. 미조회와 범위값 확인은 note에서 구별한다.
- `competitors[].name`: 실제 관측 상품명. `information`/`note`: 카테고리·관련 태그의 관측 원문, 검색 의도와 우리 상품의 차이·비교 한계. 상품 상세 URL과 확인 시각은 연결한 sources에 기록한다.
- `strategy.reason_to_choose`/`counter_evidence`: 완성 상품명 후보안과 채택 이유·대안의 한계. `fields[].note`: 최종 상품명·태그 구성의 선택 이유와 비교안의 query ID. 최종 값의 query_refs는 채택 검색어만 참조한다.
- `strategy.uncertainties`와 `issues`: 확인하지 못한 수요·경쟁·태그사전 항목, 영향과 다음 확인 방법. 근거 부족은 가설/재검토 상태에 반영한다.

수요 `demand`와 경쟁 총비용 `total_price`는 다음 형식이다.

```json
{
  "value": null,
  "status": "unknown",
  "source_refs": [],
  "period": "모름",
  "definition": "쇼핑 검색량",
  "device": "모름",
  "note": "접근 가능한 도구에서 집계 범위와 기간을 확인해야 함"
}
```

`confirmed`/`estimated`는 출처와 비음수 유한 수치가 필요하다. 총비용에는 통화·상품가와 배송비의 산식·옵션·할인 적용 조건을 definition/note에 적는다. 숫자의 저장 가능 범위는 Python 부동소수점의 유한 범위이며, 범위를 넘으면 오류로 처리한다. 모름은 null이며 영으로 대체하지 않는다.

관측의 `competitors[]`는 `name`, `relation`(`same`/`substitute`), `scope`, `total_price`, `delivery`, `information`, `trust`, `source_refs`, `note`를 담는다. 광고 포함 여부·표본 선정 기준·기기·로그인은 관측에 기록한다. 리뷰·문의에서 얻은 질문은 questions의 출처로 연결하며 우리 상품의 사실로 전환하지 않는다.

## 채널 필드·이미지·콘텐츠

- 준비 상태는 `ready`, `needs_confirmation`, `not_applicable`이다. 미확인·해당 없음의 value는 null, note에는 확인 방법 또는 적용하지 않는 이유를 남긴다. 준비된 값은 사실 참조가 필요하다.
- `title`, `category`, `price`, `options`, `shipping`, `returns`, `supply`는 게시 준비에 필요한 최소 내부 항목이다. 이것만으로 채널 필드의 완전성을 인정하지 않는다. `channel.status=verified`에는 실제 조회한 출처와 카테고리를 포함한 필수 필드 ID 목록이 필요하다. 해당 목록에 존재하지만 fields에 없거나 준비되지 않은 항목은 게시를 차단한다. 선택 항목을 제외하고 진행하려면 note에 그 범위를 적는다.
- 자산 상태는 `ready`/`missing`, 권한은 `unknown`/`use`/`edit`, 작업은 `use`/`edit`/`acquire`다. 권한을 확인한 출처를 rights_source_refs에 연결한다. PNG/JPEG/GIF/WebP를 사용하고 미완성 자산은 path·sha256=null로 둔다.
- 편집한 자산은 derived_from에 원본 자산 ID를 연결하고 수정 내용을 instruction에 적는다. 원본의 편집 권한까지 확인해야 한다. 미사용 후보의 권한 미확인은 전체를 막지 않지만 실제 사용하는 대표·상세 자산의 누락·권한 미확인은 차단한다.
- `blocks[]`는 `id`, `kind`(`hero`/`feature`/`specs`/`notice`), `heading`, `text`, `question_refs`, `fact_refs`, `asset_ids`, `rows`, `edit_reason`을 담는다. rows는 `[["항목", "값"]]` 형식이며 불필요한 요소는 빈 문자열·빈 배열로 둔다. 구매 질문·상품 사실 참조와 편집 목적은 필수다. 표·사진 속 주장도 연결된 사실과 대조한다.
- 원본 이미지 활용도 블록으로 표현한다. 사진·제목·짧은 설명·표를 필요에 맞게 조합한다. [상세페이지 작성 기준](../../docs/product-listing-principles.md#상세페이지-포맷)의 도입 순서를 적용하며, 이후 블록은 상품별 구매 결정 요인에 맞춰 배치한다.

## 상태와 게시 판단

`build`가 `revision`, `state`, `review`, `approval`, `integrity`를 생성한다. 초안에 넣은 검수·승인은 승계하지 않는다. 내용이 바뀌면 새 출력 폴더로 빌드한다. 검사·승인 기록만 바뀌는 경우 콘텐츠 버전은 유지하며, 검수 재기록은 이전 승인을 해제한다.

- 전략: `supported`(근거 확보) / `hypothesis`(가설 검증 필요) / `reconsider`(상품 재검토). 근거 확보도 판매 성과 입증은 아니다.
- 산출물: `partial`(부분 초안) / `complete`(검수 대상 완성). 필수 정보·채널 목록·사용 자산·주요 콘텐츠가 준비됐는지의 구조적 상태이며 의미 검수 합격이 아니다.
- 게시: `blocked`(보류) / `reviewable`(사람 검토 가능) / `approved`(해당 버전 승인). 산출물 차단과 필수 검수 결과로 도구가 계산한다.
- 검수 ID: `identity`, `facts`, `strategy`, `rights`, `desktop`, `mobile`, `channel`. 각각 `pass`/`fail`/`not_run`, 검사 범위 `detail`, 구체적인 확인 근거 `evidence`를 기록한다. 실제 채널을 확인하지 않았으면 channel은 not_run이다.
- 보고서에는 현재 revision·reviewer가 필요하다. 승인에는 명시적 사람 지시와 현재 버전이 필요하며, 전략이 hypothesis/reconsider이면 반대 근거를 확인한 판매 실험 판단을 decision에 남긴다. 이는 로컬 판단 기록이며 사용자 인증·전자 서명·자동 게시가 아니다.

전략·산출물·게시 상태는 독립적이다. 검색량·차별성의 불확실성은 판매 실험 가설로 남길 수 있으나 필수 정보·권한·자산·화면/채널 검수의 누락·실패는 승인으로 우회할 수 없다. 선택 정보는 관련 주장을 제외할 수 있다. 실제 판매 개시는 [사업 착수 조건](../../docs/execution-plan.md#착수-조건)을 함께 따른다.

JSON 구조·파일 해시 검사만으로 원문의 진실성, 상품 불일치, 무관 키워드, 실제 권한, 가독성을 증명할 수 없다. [작업 절차](workflow.md)의 대조·화면·채널 검수를 수행한다.

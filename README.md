# 금붕상사 문서 안내

프로젝트를 이해할 때는 [사업 기준](PROJECT.md) → [현재 상태](STATUS.md) → [실행 계획](docs/execution-plan.md) 순으로 읽는다. 실제 작업에서는 아래 담당 문서만 추가로 확인한다.

## 문서별 관리 범위

| 질문 | 관리 문서 | 이 문서에 두는 내용 |
| --- | --- | --- |
| 왜 하며 무엇을 목표로 하는가 | [PROJECT.md](PROJECT.md) | 목적·목표·사업 방향·제약·평가 기준 |
| 지금 어디까지 왔고 무엇을 해야 하는가 | [STATUS.md](STATUS.md) | 현재 상태·실행 담당·현재 검토 자료·미결 과제 |
| 어떤 순서와 조건으로 실행하는가 | [실행 계획](docs/execution-plan.md) | 단계별 결과·개발 범위·검증 흐름·행정 준비·착수 조건 |
| 어떤 상품을 고르는가 | [상품 선정 기준](docs/product-selection.md) | 확정 제외 기준·평가 방법·미확정 평가안·추천 결과 요건 |
| 어떤 검색·구매 정보를 제공하는가 | [상품 등록 원칙](docs/product-listing-principles.md) | 검색 전략·항목별 역할·콘텐츠 품질·상세페이지 포맷 |
| 등록 에이전트를 어떻게 쓰는가 | [사용법](agents/product-listing/README.md) | 책임 범위·상품 브리프·출력·명령·코드 진입점 |
| 상품별 작업을 어떻게 수행하는가 | [작업 절차](agents/product-listing/workflow.md) | 조사·작성·검수·전달·수정 순서 |
| 데이터를 어떻게 기록하는가 | [데이터 계약](agents/product-listing/data-contract.md) | listing-2 필드·참조·상태와 게시 판단·검수 기록 형식 |
| 에이전트가 어떤 원칙을 지키는가 | [AGENTS.md](AGENTS.md) | 공동 결정·행동·수치 표기·문서 관리 원칙 |
| Claude Code에서 무엇을 불러오는가 | [CLAUDE.md](CLAUDE.md) | 공통 지침과 사업 기준·상태의 진입점 |
| 어떤 근거로 판단했는가 | [records/](records/) | 의사결정·검증 이력과 [기록 양식](records/TEMPLATE.md) |

## 파일 배치와 원본

공통 문서는 루트와 `docs/`, 에이전트별 문서·코드는 `agents/<category>/`에 둔다. 카테고리명은 영문 소문자와 하이픈을 사용하며 실제 내용이 필요할 때 파일을 추가한다.

문서 변경은 [현재 스냅샷·전체 검토 원칙](AGENTS.md#필수-준수-원칙--현재-스냅샷과-전체-문서-검토)을 따른다.

상품별 자료의 원본·파생본 관계는 [데이터 계약](agents/product-listing/data-contract.md), 갱신은 [수정 절차](agents/product-listing/workflow.md#수정)를 따른다. `runs/`는 Git 제외 작업 공간이므로 공유·재검증에 필요한 근거는 최소 범위로 `records/`에 보존한다. 예시·시험 자료의 위치와 용도는 [에이전트 구조](agents/product-listing/README.md#구조와-검증-범위)를 따른다.

Claude Code는 프로젝트 폴더에서 실행한다. [CLAUDE.md](CLAUDE.md)가 공통 지침을 불러온다.

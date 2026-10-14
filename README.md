# 금붕상사

## 문서 안내

| 문서 | 관리 내용 |
| --- | --- |
| [PROJECT.md](PROJECT.md) | 사업 목표·제약·평가 기준 |
| [STATUS.md](STATUS.md) | 현재 상태·담당·미결 과제 |
| [실행 계획](docs/execution-plan.md) | 개발 범위·판매 준비·착수 조건 |
| [상품 선정 기준](docs/product-selection.md) | 평가 항목·제외 기준 |
| [상품 등록 원칙](docs/product-listing-principles.md) | 검색 전략·등록 항목·상세 콘텐츠·품질의 공통 기준 |
| [판매 등록 에이전트](agents/product-listing/README.md) | 실행 진입점·사용법·검증 범위 |
| [등록 에이전트 설계](agents/product-listing/design.md) | 입력·처리 책임·출력·상태·검증 계약 |
| [등록 작업 절차](agents/product-listing/workflow.md) | 대화형 에이전트의 수행 순서·검수 방법 |
| [등록 데이터 계약](agents/product-listing/contract.md) | listing-2 작성 형식·상태·참조 규칙 |
| [AGENTS.md](AGENTS.md) | 에이전트 행동·문서 관리 원칙 |
| [CLAUDE.md](CLAUDE.md) | Claude Code 공통 지침 불러오기 |
| [records/](records/) | 재검증·의사결정에 필요한 이력과 [기록 양식](records/TEMPLATE.md) |

## 파일 배치

- 공통 문서는 루트와 `docs/`, 에이전트별 기준·설계·코드는 `agents/<category>/`에 둔다. 카테고리명은 영문 소문자와 하이픈을 사용한다.
- 실제 내용이 필요할 때 파일을 추가한다. 문서 편집은 [전체 검토 원칙](AGENTS.md#필수-준수-원칙--현재-스냅샷과-전체-문서-검토)을 따른다.

Claude Code는 프로젝트 폴더에서 실행한다. [CLAUDE.md](CLAUDE.md)가 공통 지침을 불러온다.

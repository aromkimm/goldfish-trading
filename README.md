# 금붕상사

## 문서 안내

| 문서 | 관리 내용 |
| --- | --- |
| [PROJECT.md](PROJECT.md) | 사업 목표·제약·평가 기준 |
| [STATUS.md](STATUS.md) | 현재 상태·담당·미결 과제 |
| [실행 계획](docs/execution-plan.md) | 개발 범위·판매 준비·착수 조건 |
| [상품 선정 기준](docs/product-selection.md) | 평가 항목·제외 기준 |
| [판매 등록 에이전트](agents/product-listing/README.md) | 상세페이지 작성·검증 기준 |
| [AGENTS.md](AGENTS.md) | 에이전트 행동·문서 관리 원칙 |
| [CLAUDE.md](CLAUDE.md) | Claude Code 공통 지침 불러오기 |
| [records/](records/) | 재검증·의사결정에 필요한 이력과 [기록 양식](records/TEMPLATE.md) |

## 파일 배치

- 공통 문서는 루트와 `docs/`, 에이전트별 기준·설계·코드는 `agents/<category>/`에 둔다. 카테고리명은 영문 소문자와 하이픈을 사용한다.
- 실제 내용이 필요할 때 파일을 추가한다. 문서 편집은 [전체 검토 원칙](AGENTS.md#필수-준수-원칙--현재-스냅샷과-전체-문서-검토)을 따른다.

Claude Code는 프로젝트 폴더에서 실행한다. [CLAUDE.md](CLAUDE.md)가 공통 지침을 불러온다.

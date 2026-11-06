# 금붕상사 문서 안내

[사업 기준](PROJECT.md) → [현재 상태](STATUS.md) → [실행 계획](docs/execution-plan.md) 순으로 읽는다.

## 문서별 관리 범위

| 질문 | 원본 문서 | 관리 내용 |
| --- | --- | --- |
| 무엇을 목표로 하는가 | [PROJECT.md](PROJECT.md) | 사업 방향·제약·자원·성과 평가 |
| 지금 무엇이 확인됐고 무엇을 해야 하는가 | [STATUS.md](STATUS.md) | 공급처 판정·진행 상태·다음 행동·담당·미결 결정 |
| 어떤 순서로 검증하고 실행하는가 | [실행 계획](docs/execution-plan.md) | Accio 업무 분담·공급처 검증·손익 검토·판매 착수 조건 |
| 어떤 공급처와 상품을 선택하는가 | [선정 기준](docs/product-selection.md) | 네 가지 평가 기준·증거 수준·상품 비교·손익 산식 |
| 어떤 상품 정보를 게시하는가 | [등록 원칙](docs/product-listing-principles.md) | 판매 대상 일치·사실·자산 권한·Amazon 등록 전 확인 |
| 에이전트가 지킬 원칙은 무엇인가 | [AGENTS.md](AGENTS.md) | 공동 결정·행동·수치 표기·문서 관리 |
| Claude Code의 진입점은 무엇인가 | [CLAUDE.md](CLAUDE.md) | 공통 지침·사업 기준·상태 불러오기 |
| 판단 근거는 무엇인가 | [records/](records/) | 재검증에 필요한 결정·관측·출처. [기록 양식](records/TEMPLATE.md) 적용 |
| 보관 코드를 어떻게 재현하는가 | [legacy/README.md](legacy/README.md) | 비활성 에이전트·설정·테스트의 위치와 실행 환경 |

## 파일 배치와 원본

현재 사업 문서는 루트와 `docs/`, 과거 결정·검증 근거는 `records/`, 비활성 코드는 `legacy/`에서 관리한다. `legacy/`의 문서는 보관 구현의 사용·검증 계약이며 현재 사업의 실행 지침이 아니다. 세부 기술 문서의 관리 범위는 [보관 코드 안내](legacy/README.md)에 둔다.

상품별 실행 산출물은 Git 제외 `records/artifacts/selector-data/`와 `records/artifacts/product-listing-runs/`에 있다. 당시 자료이며 현재 재고·가격·승인으로 재사용하지 않는다. 공유에 필요한 최소 근거만 `records/`의 기록에 남긴다. API 키가 있는 루트 `.env`와 가상환경 `.venv/`는 Git 제외이며 현재 조사에 사용하지 않는다.

문서 변경은 [현재 스냅샷·전체 검토 원칙](AGENTS.md#필수-준수-원칙--현재-스냅샷과-전체-문서-검토)을 따른다. 기준과 사실은 위 원본 한 곳에서 관리하고 다른 문서는 링크한다.

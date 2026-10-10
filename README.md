# 금붕상사 프로젝트 관리

금붕상사 (goldfish trading)는 부부가 운영하는 스마트스토어 위탁판매 프로젝트다. 현재 진행 상황은 [STATUS.md](STATUS.md)에서 확인한다.

## 문서 구조

| 문서 | 관리 내용 | 갱신 시점 |
| --- | --- | --- |
| [AGENTS.md](AGENTS.md) | 에이전트 역할·행동·기록 원칙 | 협업 규칙 변경 시 |
| [CLAUDE.md](CLAUDE.md) | Claude Code의 공통 문서 불러오기 | 연결 대상 변경 시 |
| [PROJECT.md](PROJECT.md) | 사업 목표·채널·제약·성과 검토 기준 | 사업 결정 변경 시 |
| [STATUS.md](STATUS.md) | 현재 단계·다음 행동·미결 과제 | 진행 상황 변경 시 |
| [상품 선정 기준](docs/product-selection.md) | 평가 지표·제외 기준·가중치 | 기준 검증 또는 확정 시 |
| [상품 추천 에이전트](docs/product-selection-agent.md) | 추천·판매 가능 조건 확인의 범위·구조·데이터 출처 | 설계·구현 변경 시 |
| [실행 계획](docs/execution-plan.md) | 단계별 작업·자동화 우선순위·착수 조건 | 실행 계획 변경 시 |
| [records/](records/) | 날짜별 검증 결과·결정 근거·성과 검토 이력 | 의미 있는 검증·결정 시 |

## 관리 방식

- **[현재 스냅샷과 전체 문서 검토 원칙](AGENTS.md#필수-준수-원칙--현재-스냅샷과-전체-문서-검토)을 반드시 준수한다.**
- 금붕부부는 STATUS.md에서 다음 행동을 확인한다. 에이전트는 AGENTS.md → PROJECT.md → STATUS.md 순서로 읽는다.
- 실행 전 판단 기준을 정하고, 필요한 결과와 결정은 [기록 양식](records/TEMPLATE.md)에 남긴다.
- 담당자·기한·사업 기준은 임의로 확정하지 않는다.

## Claude Code 사용

이 프로젝트 폴더에서 Claude Code를 시작한다.

```sh
cd /Users/aromkim/workspace/goldfish-trading
claude
```

- CLAUDE.md는 AGENTS.md·PROJECT.md·STATUS.md를 직접 불러온다. 공통 지침과 사업 정보는 원본 문서에서만 수정한다.
- 세션에서 `/context`로 불러온 지침을 확인한다. 기존 세션은 새로 시작해 최신 문서를 적용한다.
- 일반 Claude 웹 채팅은 이 로컬 폴더와 자동 동기화되지 않는다. 이 설정은 같은 폴더를 사용하는 Claude Code용이다.
- 불러오기 방식과 확인 명령은 [Claude Code 공식 문서](https://code.claude.com/docs/en/memory)를 따른다.

## 확장 기준

- 상품 후보와 실측 데이터가 쌓이면 별도 데이터 파일을 만들고 평가 기록에서 연결한다.
- 운영 절차가 검증되면 주문·CS·정산 절차를 docs/에 추가한다.
- 기술 설계는 docs/에 둔다. 상품 추천 에이전트 코드는 `selector/`, 설정은 `config/`, 실행 절차는 `.claude/skills/`에 둔다. 수집 데이터와 비교표는 `data/`에 생성되며 커밋하지 않는다. 추천·확인 결과 중 남길 근거는 records/에 기록한다.
- API 키는 `.env`에만 두고 커밋하지 않는다. 필요한 항목은 `.env.example`을 따른다.

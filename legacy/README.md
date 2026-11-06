# 비활성 에이전트 코드

이 폴더는 국내 상품 선별·등록 도구의 구현 재현용이다. 현재 사업 조사에서 자동 실행하거나 개발 과제로 취급하지 않는다. 실행을 명시적으로 요청받았을 때만 사용하며 현재 방향은 [PROJECT.md](../PROJECT.md)를 따른다.

| 위치 | 관리 범위 |
| --- | --- |
| `selector/`, `config/selector.json`, `tests/` | 도매매·네이버/11번가 자료를 쓰는 선별 구현·설정·회귀 시험 |
| [선별 도구](docs/product-selection-agent.md) | CLI 흐름·계산·검토/인계 계약과 한계 |
| [등록 도구](agents/product-listing/README.md) | 등록 CLI·산출물·검수 실행 |
| [등록 데이터 계약](agents/product-listing/data-contract.md) | listing-2 입력·상태·검수 필드 |
| `requirements.txt`, `.env.example` | 선별 구현 의존 패키지·빈 인증정보 양식 |

## 실행 환경

모든 아래 명령은 저장소 루트에서 시작한다. 기존 가상환경 `.venv/`를 사용하며 새 환경이 필요하면 `python3 -m venv .venv` 후 `.venv/bin/pip install -r legacy/requirements.txt`로 준비한다. 외부 API 실행은 최신 접근·요금 조건을 확인해야 하며 오프라인 시험에는 키가 필요 없다.

```sh
(cd legacy && ../.venv/bin/python -m unittest discover -s tests)
.venv/bin/python -m unittest discover -s legacy/agents/product-listing/tests
(cd legacy && ../.venv/bin/python -m selector --help)
.venv/bin/python legacy/agents/product-listing/run.py --help
```

선별 설정은 `legacy/config/selector.json`, 기본 자료 경로는 `records/artifacts/selector-data/`, 인증정보는 Git 제외 루트 `.env`다. 인증정보의 내용은 이동·출력하지 않는다. 자료를 바꾸는 재현 작업은 `--data-dir`로 별도 사본 경로를 지정한다.

재검증에 필요한 상품별 실행 산출물은 Git 제외 [선별 자료](../records/artifacts/selector-data/)와 [등록 자료](../records/artifacts/product-listing-runs/)에 있다. 과거 기록의 인라인 `data/` 경로는 선별 자료 폴더, `agents/product-listing/runs/` 경로는 등록 자료 폴더에 대응한다. 당시 실행 로그·JSON 내부의 경로·해시·판정은 그대로 보존한다. 절대 경로가 들어간 외부 실행 스크립트는 이동 후 그대로 동작한다고 보장하지 않는다.

현재 사업 기준에 맞는 판매 도구로 검증된 구현이 아니다. 회귀 시험 통과는 코드 동작의 증거이며 실제 수요·권한·수익성·출고 성공을 증명하지 않는다.

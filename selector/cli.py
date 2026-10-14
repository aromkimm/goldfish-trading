"""사용법: .venv/bin/python -m selector <명령>. 전체 실행 순서는 .claude/skills/product-selector/SKILL.md."""
from __future__ import annotations

import argparse
import json

from . import db, pipeline


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="selector", description="금붕상사 상품 추천 에이전트")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="1. 도매매 상품 목록에서 후보 추가")
    s.add_argument("--kw", help="검색어")
    s.add_argument("--ca", help="카테고리 코드 (예: 01_11_00_00_00)")
    s.add_argument("--pages", type=int, default=1)
    s.add_argument("--size", type=int, default=200, help="페이지당 상품 수 (1~200)")
    s.add_argument("--sort", help="se 정확도, rd 랭킹, ha 인기, aa 낮은가격, da 최근등록")

    d = sub.add_parser("detail", help="2. 상세 수집·규칙 제외")
    d.add_argument("--refresh", action="store_true", help="진행 중 후보 전체의 변동성 스냅샷도 갱신")
    d.add_argument("--limit", type=int)

    sub.add_parser("triage-export", help="3. Claude 판정 대상 내보내기")
    ti = sub.add_parser("triage-import", help="3. Claude 판정 결과 반영")
    ti.add_argument("path")

    sub.add_parser("measure", help="4. 대표 키워드 검색량 수집")
    sub.add_parser("trend", help="4-2. 검색어 트렌드·쇼핑 클릭 추이·블로그·카페 수집 (NAVER API HUB)")

    cp = sub.add_parser("compete", help="5. 11번가 경쟁·가격 수집 (같은 상품 판매자·경쟁가·상품 수)")
    cp.add_argument("--limit", type=int)

    me = sub.add_parser("manual-export", help="검증 표본: 네이버쇼핑 수동 확인 화면 만들기")
    me.add_argument("--shortlist", type=int, help="확인할 상위 후보 수 (기본: 설정값)")
    me.add_argument("--nos", help="상품번호를 직접 지정 (쉼표 구분)")
    mi = sub.add_parser("manual-import", help="검증 표본: 수동 확인 CSV 반영")
    mi.add_argument("path")

    sub.add_parser("report", help="6. 마진·점수 계산, 비교표 작성")

    re_ = sub.add_parser("review-export", help="7. 상위 후보 검토 대상 내보내기")
    re_.add_argument("--top", type=int, default=10)
    ri = sub.add_parser("review-import", help="7. 검토 결과 반영")
    ri.add_argument("path")

    ve = sub.add_parser("verify-export", help="8. 판매 가능 조건 확인 화면 만들기")
    ve.add_argument("--top", type=int, help="비교표 상위 몇 개를 확인할지 (기본: 설정값)")
    ve.add_argument("--nos", help="상품번호를 직접 지정 (쉼표 구분)")
    vi = sub.add_parser("verify-import", help="8. 확인 CSV 반영 → 판매 조건서 작성")
    vi.add_argument("path")

    sub.add_parser("status", help="단계별 후보 수")

    args = p.parse_args(argv)
    conn = db.connect()

    if args.cmd == "search":
        print(f"추가 {pipeline.search_supply(conn, kw=args.kw, ca=args.ca, pages=args.pages, size=args.size, sort=args.sort)}건")
    elif args.cmd == "detail":
        stages = ("new", "detailed", "triaged", "measured", "checked") if args.refresh else ("new",)
        print(pipeline.fetch_details(conn, stages=stages, limit=args.limit))
    elif args.cmd == "triage-export":
        path, n = pipeline.export_triage(conn)
        print(f"{n}건 → {path}")
    elif args.cmd == "triage-import":
        print(pipeline.import_triage(conn, args.path))
    elif args.cmd == "measure":
        print(pipeline.measure(conn))
    elif args.cmd == "trend":
        print(pipeline.collect_trends(conn))
    elif args.cmd == "compete":
        print(pipeline.compete(conn, limit=args.limit))
    elif args.cmd == "manual-export":
        nos = [int(x) for x in args.nos.split(",")] if args.nos else None
        path, n = pipeline.export_manual(conn, args.shortlist, nos)
        print(f"{n}건 → {path}")
    elif args.cmd == "manual-import":
        print(f"{pipeline.import_manual(conn, args.path)}건 반영")
    elif args.cmd == "report":
        md, csv_path, n = pipeline.write_report(conn)
        print(f"{n}건 → {md}, {csv_path}")
    elif args.cmd == "review-export":
        path, n = pipeline.export_review(conn, args.top)
        print(f"{n}건 → {path}")
    elif args.cmd == "review-import":
        print(f"{pipeline.import_review(conn, args.path)}건 반영")
    elif args.cmd == "verify-export":
        nos = [int(x) for x in args.nos.split(",")] if args.nos else None
        path, n = pipeline.export_verify(conn, args.top, nos)
        print(f"{n}건 → {path}")
    elif args.cmd == "verify-import":
        print(pipeline.import_verify(conn, args.path))
    elif args.cmd == "status":
        rows = conn.execute("SELECT stage, COUNT(*) n FROM candidates GROUP BY stage").fetchall()
        print(json.dumps({r["stage"]: r["n"] for r in rows}, ensure_ascii=False))

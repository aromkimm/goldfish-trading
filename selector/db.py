from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    no INTEGER PRIMARY KEY,           -- 도매 상품번호
    title TEXT,
    url TEXT,
    source_query TEXT,                -- 후보를 찾은 검색 조건
    stage TEXT NOT NULL DEFAULT 'new',-- new → detailed → triaged → measured → checked(경쟁 정보 확보) → verified / excluded·returned
    exclude_reason TEXT,
    keywords TEXT,                    -- JSON 배열. triage에서 Claude가 작성
    review TEXT,                      -- JSON. 7단계 검토에서 Claude가 작성
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supply_snapshots (  -- 변동성 계산용 스냅샷
    no INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    summary TEXT NOT NULL,
    raw TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS keyword_stats (
    keyword TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    pc INTEGER, mobile INTEGER, comp_idx TEXT,
    raw TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trends (            -- NAVER API HUB 추세·관심도 (대표 키워드 단위)
    keyword TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    search_series TEXT,               -- JSON. 월별 검색어 트렌드 상대값
    shop_category TEXT,               -- 쇼핑 인사이트 분야 코드
    shop_series TEXT,                 -- JSON. 월별 쇼핑 클릭 상대값
    blog_total INTEGER,
    blog_dates TEXT,                  -- JSON. 최신 블로그 글 작성일
    cafe_total INTEGER
);
CREATE TABLE IF NOT EXISTS competition (       -- 11번가 경쟁 수집 (자동)
    no INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    title_query TEXT NOT NULL,        -- 도매 상품명에서 만든 검색어
    title_total INTEGER,              -- 그 검색어의 11번가 전체 결과 수
    checked INTEGER NOT NULL,         -- 이미지를 비교한 상품 수
    image_failed INTEGER NOT NULL,
    same_sellers INTEGER NOT NULL,    -- 같은 상품을 파는 판매자 수 (동일 상품 포화도)
    same_prices TEXT NOT NULL,        -- JSON 배열
    same_reviews INTEGER NOT NULL,    -- 같은 상품들의 리뷰 수 합계 (판매 흔적)
    keyword TEXT NOT NULL,
    keyword_total INTEGER,            -- 대표 키워드의 11번가 전체 상품 수
    similar_prices TEXT NOT NULL,     -- JSON 배열. 대표 키워드 인기도 상위 상품 가격
    type_sellers INTEGER,             -- 같은 유형(상품명 유사) 판매자 수
    type_prices TEXT,                 -- JSON 배열. 같은 유형 가격
    keyword_fit REAL,                 -- 대표 키워드 검색 상위 상품명이 도매 상품명 단어를 담는 평균 비율(참고)
    keyword_names TEXT,               -- JSON 배열. 대표 키워드 검색 상위 상품명 (키워드 검토용)
    items TEXT,                       -- JSON 배열. 상품명 검색 결과별 상품명·판매자·가격·배송·같은 사진/유형 여부
    keyword_items TEXT                -- JSON 배열. 대표 키워드 검색 결과별 상품명·가격·배송
);
CREATE TABLE IF NOT EXISTS catalog_checks (     -- 네이버 커머스API 카탈로그 조회 (참고 지표)
    no INTEGER NOT NULL,
    fetched_at TEXT NOT NULL,
    query TEXT NOT NULL,              -- 도매 상품명에서 만든 검색어
    total INTEGER,                    -- 검색된 카탈로그 전체 수 (넓게 잡힘)
    similar INTEGER NOT NULL,         -- 상위 결과 중 검색어 단어를 많이 담은 카탈로그 수 (같은 유형)
    exact INTEGER NOT NULL,           -- 검색어 단어를 전부 담은 카탈로그 수 (가격비교 묶음 가능성)
    names TEXT NOT NULL               -- JSON 배열. 같은 유형 카탈로그 이름 상위
);
CREATE TABLE IF NOT EXISTS manual_checks (     -- 네이버쇼핑 수동 확인 결과 (11번가 대비 검증 표본)
    no INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    total_results INTEGER,            -- 대표 키워드 검색 결과 전체 상품 수
    same_sellers INTEGER,             -- 같은 상품을 파는 판매자 수 (동일 상품 포화도)
    same_prices TEXT NOT NULL,        -- JSON 배열
    similar_prices TEXT NOT NULL,     -- JSON 배열. 같은 상품이 적을 때의 경쟁가
    note TEXT
);
CREATE TABLE IF NOT EXISTS judgments (         -- 사람·검토 단계의 상품별 판정. 최신 판정이 선별 통과 여부에 반영된다
    no INTEGER NOT NULL,
    judged_at TEXT NOT NULL,
    verdict TEXT NOT NULL,            -- 판매 실험 검토 가능 / 추가 확인 / 제외 (docs/product-selection.md 판정)
    reason TEXT NOT NULL,
    source TEXT NOT NULL              -- 판정 근거 자료·판정자 (예: 네이버 캡처 표본, 7단계 검토)
);
CREATE TABLE IF NOT EXISTS verifications (     -- 판매 가능 조건 확인
    no INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    conditions TEXT NOT NULL,         -- JSON. API로 채운 조건
    manual TEXT NOT NULL,             -- JSON. 사람이 입력한 값
    result TEXT NOT NULL,             -- verified / returned
    reasons TEXT NOT NULL,            -- JSON 배열. 반려 사유
    warnings TEXT NOT NULL            -- JSON 배열
);
"""


MIGRATIONS = {  # 이전 스키마로 만든 DB에 없는 열
    "competition": {"type_sellers": "INTEGER", "type_prices": "TEXT", "keyword_fit": "REAL", "keyword_names": "TEXT",
                    "items": "TEXT", "keyword_items": "TEXT"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    if path is None:
        DATA_DIR.mkdir(exist_ok=True)
        path = DATA_DIR / "selector.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, cols in MIGRATIONS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, kind in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {kind}")
    return conn


def latest_snapshot(conn: sqlite3.Connection, no: int) -> dict | None:
    row = conn.execute(
        "SELECT summary FROM supply_snapshots WHERE no=? ORDER BY fetched_at DESC LIMIT 1", (no,)
    ).fetchone()
    return json.loads(row["summary"]) if row else None


def latest_keyword_stats(conn: sqlite3.Connection, keyword: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM keyword_stats WHERE keyword=? ORDER BY fetched_at DESC LIMIT 1", (keyword,)
    ).fetchone()


def latest_trend(conn: sqlite3.Connection, keyword: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM trends WHERE keyword=? ORDER BY fetched_at DESC LIMIT 1", (keyword,)
    ).fetchone()


def latest_competition(conn: sqlite3.Connection, no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM competition WHERE no=? ORDER BY fetched_at DESC LIMIT 1", (no,)
    ).fetchone()


def latest_catalog(conn: sqlite3.Connection, no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM catalog_checks WHERE no=? ORDER BY fetched_at DESC LIMIT 1", (no,)
    ).fetchone()


def latest_manual_check(conn: sqlite3.Connection, no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM manual_checks WHERE no=? ORDER BY checked_at DESC LIMIT 1", (no,)
    ).fetchone()


VERDICTS = ("판매 실험 검토 가능", "추가 확인", "제외")


def add_judgment(conn: sqlite3.Connection, no: int, verdict: str, reason: str, source: str, at: str | None = None) -> None:
    if verdict not in VERDICTS:
        raise ValueError(f"판정은 {', '.join(VERDICTS)} 중 하나")
    if not reason.strip() or not source.strip():
        raise ValueError("판정 사유와 출처가 필요")
    conn.execute("INSERT INTO judgments VALUES (?,?,?,?,?)", (no, at or now(), verdict, reason.strip(), source.strip()))


def latest_judgment(conn: sqlite3.Connection, no: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM judgments WHERE no=? ORDER BY judged_at DESC, rowid DESC LIMIT 1", (no,)
    ).fetchone()

"""NAVER API HUB 클라이언트: 검색어 트렌드, 쇼핑 인사이트, 블로그·카페 검색.

명세 출처(2026-10-10 확인): api.ncloud-docs.com NAVER API HUB 문서. 실호출 확인.
요금: 검색어 트렌드·쇼핑 인사이트는 월 30,000건까지 기본 무료. 콘솔 한도로 과금을 막는다.
"""
from __future__ import annotations

from .. import http
from ..config import secret

BASE = "https://naverapihub.apigw.ntruss.com"

# 네이버쇼핑 대분류 코드. 2026-10-10 실호출로 키워드별 클릭이 몰리는 분야를 확인했다.
SHOP_CATEGORY = {"생활/건강": "50000008", "가구/인테리어": "50000004", "스포츠/레저": "50000007"}


def _headers() -> dict:
    return {"X-NCP-APIGW-API-KEY-ID": secret("NAVER_HUB_CLIENT_ID"),
            "X-NCP-APIGW-API-KEY": secret("NAVER_HUB_CLIENT_SECRET")}


def search_total(kind: str, query: str) -> int:
    """kind: blog, cafearticle, image. 총 결과 수."""
    return http.get_json(f"{BASE}/search/v1/{kind}", params={"query": query, "display": 1},
                         headers=_headers())["total"]


def blog_recent(query: str) -> list[str]:
    """최신순 블로그 글 100개의 작성일(yyyymmdd)."""
    data = http.get_json(f"{BASE}/search/v1/blog", params={"query": query, "display": 100, "sort": "date"},
                         headers=_headers())
    return [i["postdate"] for i in data.get("items", []) if i.get("postdate")]


def search_trend(keywords: list[str], start: str, end: str) -> dict[str, list[float]]:
    """통합검색 월간 추이. 한 번에 최대 5개. 같은 호출 안에서 가장 큰 값이 100인 상대값."""
    data = http.post_json(f"{BASE}/search-trend/v1/search", {
        "startDate": start, "endDate": end, "timeUnit": "month",
        "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
    }, headers=_headers())
    return {r["title"]: _monthly(r["data"], start, end) for r in data["results"]}


def shopping_keywords(category: str, keywords: list[str], start: str, end: str) -> dict[str, list[float]]:
    """쇼핑 분야 안 키워드별 월간 클릭 추이. 한 번에 최대 5개."""
    data = http.post_json(f"{BASE}/shopping/v1/category/keywords", {
        "startDate": start, "endDate": end, "timeUnit": "month", "category": category,
        "keyword": [{"name": k, "param": [k]} for k in keywords],
    }, headers=_headers())
    return {r["title"]: _monthly(r["data"], start, end) for r in data["results"]}


def _monthly(points: list[dict], start: str, end: str) -> list[float]:
    """빠진 달(클릭·검색이 없어 응답에 없는 달)을 0으로 채운 월별 값."""
    by_month = {p["period"][:7]: p["ratio"] for p in points}
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= end[:7]:
        out.append(by_month.get(f"{y:04d}-{m:02d}", 0.0))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out

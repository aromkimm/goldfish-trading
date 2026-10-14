"""네이버 검색광고 키워드 도구 클라이언트.

명세 출처(2026-10-10 확인): github.com/naver/searchad-apidoc
쇼핑 검색 API는 제공되지 않아 쓰지 않는다(docs/product-selection-agent.md 데이터 출처).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .. import http
from ..config import secret

SEARCHAD_BASE = "https://api.searchad.naver.com"


def _signature(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def keyword_stats(keywords: list[str]) -> list[dict]:
    """키워드 도구. 힌트 키워드는 최대 5개, 공백은 제거해 보낸다.

    반환 행: relKeyword, monthlyPcQcCnt, monthlyMobileQcCnt(10 미만은 "<10"), compIdx 등.
    """
    if not 1 <= len(keywords) <= 5:
        raise ValueError("hintKeywords는 1~5개")
    uri = "/keywordstool"
    ts = str(round(time.time() * 1000))
    headers = {
        "X-Timestamp": ts,
        "X-API-KEY": secret("SEARCHAD_API_KEY"),
        "X-Customer": secret("SEARCHAD_CUSTOMER_ID"),
        "X-Signature": _signature(ts, "GET", uri, secret("SEARCHAD_SECRET_KEY")),
    }
    data = http.get_json(SEARCHAD_BASE + uri, params={
        "hintKeywords": ",".join(k.replace(" ", "") for k in keywords), "showDetail": 1,
    }, headers=headers)
    return data.get("keywordList", []) if isinstance(data, dict) else data


LESS_THAN_10 = -1


def parse_count(value) -> int | None:
    """검색수를 정수로. "<10"은 임의값으로 채우지 않고 LESS_THAN_10(-1), 값 없음은 None."""
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().startswith("<"):
        return -1
    return int(value)

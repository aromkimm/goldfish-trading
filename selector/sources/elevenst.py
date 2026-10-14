"""11번가 Open API 상품검색(ProductSearch) 클라이언트.

명세 출처(2026-10-10 확인): openapi.11st.co.kr 개발가이드. 응답은 EUC-KR XML이고 검색어는 UTF-8로 보낸다(실호출 확인).
키는 등록한 IP에서만 동작한다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .. import http
from ..config import secret

API_URL = "https://openapi.11st.co.kr/openapi/OpenApiService.tmall"


def _int(text) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse(xml_bytes: bytes) -> tuple[int, list[dict]]:
    # 파이썬 XML 파서는 EUC-KR을 지원하지 않아 CP949(EUC-KR 상위 호환)로 먼저 디코딩하고 선언을 뗀다.
    text = xml_bytes.decode("cp949", "replace")
    root = ET.fromstring(re.sub(r"^<\?xml[^>]*\?>", "", text.lstrip()))
    if root.tag == "ErrorResponse":
        raise RuntimeError(f"11번가 오류 {root.findtext('ErrorCode')}: {root.findtext('ErrorMessage')}")
    products = root.find("Products")
    total = _int(products.findtext("TotalCount")) or 0
    items = []
    for p in products.findall("Product"):
        items.append({
            "code": p.findtext("ProductCode"),
            "name": (p.findtext("ProductName") or "").strip(),
            "image": p.findtext("ProductImage200") or p.findtext("ProductImage"),
            "seller": p.findtext("Seller"),
            "price": _int(p.findtext("SalePrice")) or _int(p.findtext("ProductPrice")),
            "delivery": (p.findtext("Delivery") or "").strip(),
            "reviews": _int(p.findtext("ReviewCount")) or 0,
            "rating": p.findtext("Rating") or None,
        })
    return total, items


def search(keyword: str, *, size: int = 100, page: int = 1, sort: str | None = None) -> tuple[int, list[dict]]:
    """sort: CP 인기도, A 누적판매, G 평가, I 리뷰 많은 순, L 낮은가격, H 높은가격, N 최근등록. size ≤ 200."""
    raw = http.request("GET", API_URL, params={
        "key": secret("ELEVENST_API_KEY"), "apiCode": "ProductSearch", "keyword": keyword,
        "pageNum": page, "pageSize": size, "sortCd": sort,
    })
    return parse(raw)


def query_from_title(title: str, words: int = 5) -> str:
    """도매 상품명에서 검색어를 만든다. 위탁 판매자가 도매 상품명을 거의 그대로 쓰는 경우가 많아 같은 상품이 잘 잡힌다."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", title or "")
    t = re.sub(r"[^0-9A-Za-z가-힣 ]", " ", t)
    kept = [w for w in t.split() if len(w) > 1 and not re.fullmatch(r"[A-Za-z]?\d+[A-Za-z]*", w)]
    return " ".join(kept[:words])

"""11번가 검색 표본의 같은 사진·같은 유형 판매자 수를 추정한다.

사진은 dHash 거리, 유형은 검색어 단어의 상품명 포함 비율로 판정한다.
동일 제조사·동일 상품을 확정하지 않으며 조회 범위 밖 경쟁자는 세지 않는다.
임계값은 config/selector.json, 검증 근거는 records/2026-10-10-product-selection-agent.md를 따른다.
"""
from __future__ import annotations

import hashlib
import io
import re
from concurrent.futures import ThreadPoolExecutor

from . import http
from .config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache" / "img"


def fetch_image(url: str) -> bytes:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    if path.exists():
        return path.read_bytes()
    data = http.request("GET", url, retries=1, timeout=15)
    path.write_bytes(data)
    return data


def dhash(image_bytes: bytes, size: int = 8) -> int:
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as img:
        gray = img.convert("L").resize((size + 1, size), Image.LANCZOS)
        px = list(gray.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return bits


def distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def word_overlap(query: str, name: str) -> float:
    """검색어 단어(2글자 이상) 중 상품명에 들어 있는 비율. 띄어쓰기 차이는 무시한다."""
    words = [w for w in query.split() if len(w) >= 2]
    text = (name or "").replace(" ", "")
    return sum(w in text for w in words) / len(words) if words else 0.0


_COUNT = re.compile(r"(\d+)\s*(?:개입|개|팩|매입|매|입|세트|set|p)(?![가-힣a-z])", re.I)
_DIMS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:cm|mm)?\s*[x×*]\s*(\d+(?:\.\d+)?)", re.I)


def spec(name: str) -> dict:
    """상품명에 적힌 수량·가로×세로. 표기가 없으면 None(모름)."""
    name = name or ""
    counts = [int(m.group(1)) for m in _COUNT.finditer(name)]
    dims = _DIMS.search(name)
    return {"count": max(counts) if counts else (2 if "묶음" in name else None),
            "dims": tuple(sorted((float(dims.group(1)), float(dims.group(2))))) if dims else None}


def spec_conflict(title: str, name: str, tolerance: float = 0.25) -> str | None:
    """도매 상품과 경쟁 상품의 표기된 수량·치수가 다르면 사유. 한쪽이라도 표기가 없으면 비교하지 않는다.
    수량은 도매 상품명에 표기가 없으면 1개로 본다〔추정 — 묶음 판매가가 낱개 경쟁가로 섞이는 것을 막는 용도〕."""
    a, b = spec(title), spec(name)
    if b["count"] and b["count"] > 1 and b["count"] != (a["count"] or 1):
        return "수량 다름"
    if a["dims"] and b["dims"] and any(abs(x - y) > tolerance * max(x, y) for x, y in zip(a["dims"], b["dims"])):
        return "치수 다름"
    return None


def reverse_overlap(title: str, name: str) -> float:
    """경쟁 상품명 단어 중 도매 상품명에 들어 있는 비율. 도매 상품명 단어를 담았어도 다른 종류(수납장·진열장 등)의 단어가 많으면 낮다."""
    words = re.sub(r"[^0-9A-Za-z가-힣 ]", " ", name or "").split()
    return word_overlap(" ".join(words), title)


def same_type(query: str, items: list[dict], min_overlap: float) -> dict:
    """사진과 관계없이 상품명 단어 포함 비율로 같은 유형 후보를 찾는다."""
    typed = [it for it in items if word_overlap(query, it.get("name")) >= min_overlap]
    return {
        "sellers": len({it.get("seller") for it in typed}),
        "prices": sorted(it["price"] for it in typed if it.get("price")),
    }


def match(supplier_image: bytes, items: list[dict], max_distance: int, fetch=None) -> dict:
    """items는 11번가 검색 결과(image, seller, price, reviews). 같은 사진으로 추정한 결과를 요약한다."""
    fetch = fetch or fetch_image
    base = dhash(supplier_image)

    def hash_of(item):
        try:
            return dhash(fetch(item["image"]))
        except Exception:
            return None

    with ThreadPoolExecutor(8) as ex:
        hashes = list(ex.map(hash_of, items))
    flags = [h is not None and distance(base, h) <= max_distance for h in hashes]
    matched = [it for it, f in zip(items, flags) if f]
    return {
        "flags": flags,  # items 순서대로 같은 사진 여부
        "checked": len(items),
        "image_failed": sum(h is None for h in hashes),
        "matched": len(matched),
        "sellers": len({m.get("seller") for m in matched}),
        "prices": sorted(m["price"] for m in matched if m.get("price")),
        "reviews": sum(m.get("reviews") or 0 for m in matched),
    }

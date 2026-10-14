"""11번가 검색 표본의 같은 사진·같은 유형 판매자 수를 추정한다.

사진은 dHash 거리, 유형은 검색어 단어의 상품명 포함 비율로 판정한다.
동일 제조사·동일 상품을 확정하지 않으며 조회 범위 밖 경쟁자는 세지 않는다.
임계값은 config/selector.json, 검증 근거는 records/2026-10-10-product-selection-agent.md를 따른다.
"""
from __future__ import annotations

import hashlib
import io
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
    matched = [it for it, h in zip(items, hashes) if h is not None and distance(base, h) <= max_distance]
    return {
        "checked": len(items),
        "image_failed": sum(h is None for h in hashes),
        "matched": len(matched),
        "sellers": len({m.get("seller") for m in matched}),
        "prices": sorted(m["price"] for m in matched if m.get("price")),
        "reviews": sum(m.get("reviews") or 0 for m in matched),
    }

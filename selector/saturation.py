"""동일 상품 포화도: 도매 원본 썸네일과 11번가 검색 결과 썸네일의 dHash 거리로 같은 상품을 센다.

한계: 판매자가 이미지를 가공하면 놓치고(과소 추정), 검색 결과 상위 범위 밖 판매자는 세지 않는다.
거리 임계값은 2026-10-10 표본 12건에서 같은 사진이 0~6, 다른 상품이 대부분 12 이상으로 나온 것을 근거로 한 제안값이다.
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


def match(supplier_image: bytes, items: list[dict], max_distance: int, fetch=None) -> dict:
    """items는 11번가 검색 결과(image, seller, price, reviews). 같은 상품으로 판정된 결과를 요약한다."""
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

"""네이버 커머스API 클라이언트 (조회 전용).

명세 출처(2026-10-14 확인): apicenter.commerce.naver.com/llms (인증, GET /v1/product-models, GET /v1/categories/{id}).
인증: OAuth2 Client Credentials. 시크릿 대신 bcrypt(client_id_timestamp, salt=client_secret)를 Base64로 보낸다.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request

from .. import http
from ..config import secret

BASE = "https://api.commerce.naver.com/external"
_token: dict = {}


def signature(client_id: str, client_secret: str, timestamp: int) -> str:
    import bcrypt

    hashed = bcrypt.hashpw(f"{client_id}_{timestamp}".encode(), client_secret.encode())
    return base64.urlsafe_b64encode(hashed).decode()


def token() -> str:
    """토큰을 발급해 만료 1분 전까지 재사용한다."""
    if _token.get("value") and _token["expires"] > time.time() + 60:
        return _token["value"]
    client_id, client_secret = secret("COMMERCE_CLIENT_ID"), secret("COMMERCE_CLIENT_SECRET")
    ts = int(time.time() * 1000)
    body = urllib.parse.urlencode({
        "client_id": client_id, "timestamp": ts, "grant_type": "client_credentials", "type": "SELF",
        "client_secret_sign": signature(client_id, client_secret, ts),
    }).encode()
    req = urllib.request.Request(f"{BASE}/v1/oauth2/token", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise http.HttpError(e.code, "oauth2/token", e.read().decode("utf-8", "replace")) from None
    _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 0)))
    return _token["value"]


def _get(path: str, params: dict | None = None) -> dict:
    return http.get_json(BASE + path, params=params, headers={"Authorization": f"Bearer {token()}"})


def catalogs(name: str, size: int = 20) -> tuple[int, list[dict]]:
    """네이버쇼핑 카탈로그(가격비교 모델)를 이름으로 검색. (전체 개수, 목록[id, name, wholeCategoryName, brandName, manufacturerName])"""
    data = _get("/v1/product-models", {"name": name, "page": 1, "size": size})
    return data.get("totalElements") or 0, data.get("contents") or []


def category(category_id: str) -> dict:
    return _get(f"/v1/categories/{category_id}")

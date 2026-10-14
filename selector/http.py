from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "goldfish-trading-selector/0.1"


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str):
        super().__init__(f"HTTP {status} {url}: {body[:300]}")
        self.status = status


def request(method: str, url: str, *, params: dict | None = None, headers: dict | None = None,
            body: dict | None = None, retries: int = 3, timeout: float = 20) -> bytes:
    """429·5xx·네트워크 오류는 지수 백오프로 재시도한다. 그 외 오류는 즉시 HttpError."""
    if params:
        url = f"{url}?{urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if (e.code == 429 or e.code >= 500) and attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise HttpError(e.code, url, text) from None
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise
    raise AssertionError("unreachable")


def get_json(url: str, **kw) -> dict | list:
    return json.loads(request("GET", url, **kw))


def post_json(url: str, body: dict, **kw) -> dict | list:
    return json.loads(request("POST", url, body=body, **kw))

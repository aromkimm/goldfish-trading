from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "selector.json"


def load_env(path: Path = ROOT / ".env") -> None:
    """.env의 KEY=VALUE를 환경변수로 읽는다. 이미 설정된 값은 덮어쓰지 않는다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def secret(name: str) -> str:
    load_env()
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name}이(가) 비어 있다. .env.example을 참고해 .env에 입력한다.")
    return value


def settings() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

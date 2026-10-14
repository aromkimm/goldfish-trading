"""규칙 기반 1차 제외. 명백한 경우만 거르고, 나머지는 triage에서 Claude가 판정한다."""
from __future__ import annotations


def rule_exclusion(summary: dict, cfg: dict) -> str | None:
    """제외 사유 문자열 또는 None(통과)."""
    if summary.get("status") not in (None, "판매중"):
        return f"판매상태: {summary.get('status')}"
    if cfg.get("exclude_adult") and summary.get("adult"):
        return "성인 상품"
    if cfg.get("exclude_oversea") and summary.get("from_oversea"):
        return "해외직배송"
    if summary.get("supply_price") is None:
        return "도매매 단가 없음(도매매 미판매)"
    category = " ".join(summary.get("category_path") or [])
    title = summary.get("title") or ""
    for reason, rule in cfg["rules"].items():
        for word in rule.get("category", []):
            if word in category:
                return f"{reason} (카테고리: {word})"
        for word in rule.get("title", []):
            if word in title:
                return f"{reason} (상품명: {word})"
    return None

"""경쟁가·마진 시나리오와 배치 내 상대 점수.

마진 가정〔추정치〕: 무료배송으로 판매해 도매 배송비를 판매가 안에서 부담한다.
마진율 분모는 판매가다. 플랫폼 수수료율이 설정되지 않으면 수수료 반영 마진은 None(모름).
"""
from __future__ import annotations

from statistics import median


def drop_outliers(prices: list[int]) -> list[int]:
    """중앙값의 절반 미만 가격을 뺀다. 옵션 최저가만 표시한 상품, 다른 부속품이 섞여 최저가가 왜곡되는 것을 막는다〔추정치 — 기준 제안값〕."""
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return prices
    mid = median(prices)
    return [p for p in prices if p >= mid * 0.5]


def competitor_prices(matched_prices: list[int], keyword_prices: list[int], min_matched: int,
                      type_prices: list[int] = ()) -> tuple[list[int], str]:
    """경쟁가 출처 우선순위: 같은 사진 → 같은 유형 → 키워드 상위 결과."""
    if len(matched_prices) >= min_matched:
        return drop_outliers(matched_prices), "동일 상품"
    if len(type_prices) >= min_matched:
        return drop_outliers(list(type_prices)), "같은 유형"
    return drop_outliers(keyword_prices), "키워드 상위 결과"


def price_scenarios(prices: list[int], resale_min: int | None) -> dict:
    """최저가·경쟁 중앙가. 도매처 최저판매준수가격이 있으면 하한으로 올린다."""
    if not prices:
        return {"lowest": None, "median": None, "floored": False}
    lowest, mid = min(prices), int(median(prices))
    floor = resale_min or 0
    return {"lowest": max(lowest, floor), "median": max(mid, floor), "floored": floor > lowest}


def margin(sale_price: int | None, supply_price: int | None, ship_cost: int | None,
           fee_rate: float | None) -> dict:
    if sale_price is None or supply_price is None or ship_cost is None:
        return {"gross": None, "gross_rate": None, "net": None, "net_rate": None}
    gross = sale_price - supply_price - ship_cost
    net = None if fee_rate is None else round(gross - sale_price * fee_rate)
    return {
        "gross": gross,
        "gross_rate": round(gross / sale_price, 4) if sale_price else None,
        "net": net,
        "net_rate": None if net is None or not sale_price else round(net / sale_price, 4),
    }


def percentile_ranks(values: dict, higher_is_better: bool) -> dict:
    """값이 있는 후보끼리 0~1 순위. 값이 None인 후보는 결과에서 빠진다."""
    known = {k: v for k, v in values.items() if v is not None}
    if not known:
        return {}
    ordered = sorted(known.values())
    n = len(ordered)
    ranks = {}
    for k, v in known.items():
        below = sum(1 for x in ordered if x < v)
        equal = sum(1 for x in ordered if x == v)
        pct = (below + (equal - 1) / 2) / (n - 1) if n > 1 else 0.5
        ranks[k] = pct if higher_is_better else 1 - pct
    return ranks


DIRECTION = {
    "saturation": False,           # 같은 상품 판매 쇼핑몰 수: 적을수록 좋다
    "gross_margin_rate": True,
    "competition_density": False,  # 상품 수 ÷ 월 검색수
    "search_volume": True,
    "trend_growth": True,          # 최근 3개월 검색 관심 증감
}


def score(metrics: dict[int, dict], weights: dict, required: list[str] = ()) -> dict[int, dict]:
    """metrics: {후보번호: {지표: 값|None}}. 빠진 지표는 가중치에서 제외하고 missing에 남긴다.
    required 지표가 하나라도 없으면 점수를 매기지 않는다(빠진 지표가 유리하게 작용하지 않도록)."""
    ranks = {
        name: percentile_ranks({no: m.get(name) for no, m in metrics.items()}, DIRECTION[name])
        for name in weights
    }
    result = {}
    for no in metrics:
        total = weight_sum = 0.0
        missing = []
        for name, w in weights.items():
            if no in ranks[name]:
                total += w * ranks[name][no]
                weight_sum += w
            else:
                missing.append(name)
        blocked = [name for name in required if metrics[no].get(name) is None]
        result[no] = {
            "score": round(total / weight_sum * 100, 1) if weight_sum and not blocked else None,
            "missing": missing + [n for n in blocked if n not in missing],
        }
    return result

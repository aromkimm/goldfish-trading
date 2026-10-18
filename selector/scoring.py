"""경쟁가·마진 시나리오.

마진 가정〔추정치〕: 무료배송으로 판매해 도매 배송비를 판매가 안에서 부담한다.
마진율 분모는 판매가다. 플랫폼 수수료율이 설정되지 않으면 수수료 반영 마진은 None(모름).
"""
from __future__ import annotations

from statistics import median, quantiles

from . import saturation


def drop_outliers(prices: list[int]) -> list[int]:
    """중앙값의 절반 미만 가격을 뺀다. 옵션 최저가만 표시한 상품, 다른 부속품이 섞여 최저가가 왜곡되는 것을 막는다〔추정치 — 기준 제안값〕."""
    prices = [p for p in prices if p and p > 0]
    if len(prices) < 3:
        return prices
    mid = median(prices)
    return [p for p in prices if p >= mid * 0.5]


FREE_SHIPPING = "무료"  # 11번가 Delivery 값: 무료·조건부무료·착불/선결제 (2026-10-15 실호출 관측)


def comparable_prices(items: list[dict], title: str | None = None,
                      min_reverse_overlap: float | None = None) -> tuple[list[int], dict, list[int]]:
    """(무료배송 경쟁 가격, 사유별로 뺀 가격 수, 배송 조건만 달라 뺀 가격).
    - 수량·치수: 상품명에 표기된 수량·치수가 도매 상품과 다르면 뺀다(title이 있을 때).
    - 다른 종류: 경쟁 상품명 단어 중 도매 상품명에 있는 비율이 min_reverse_overlap 미만이면 뺀다(같은 유형 집합용).
    - 배송 조건: 조건부무료·착불·미표시는 한 개 주문 배송비를 알 수 없어 무료배송 가격과 섞지 않는다.
      그 표시가는 고객 결제 총액의 하한이므로 따로 돌려준다(최저가 시나리오용)."""
    kept, paid, dropped = [], [], {"배송 조건": 0, "수량·치수": 0, "다른 종류": 0}
    for i in items:
        if not i.get("price"):
            continue
        if title and saturation.spec_conflict(title, i.get("name")):
            dropped["수량·치수"] += 1
        elif min_reverse_overlap is not None and saturation.reverse_overlap(title, i.get("name")) < min_reverse_overlap:
            dropped["다른 종류"] += 1
        elif i.get("delivery") != FREE_SHIPPING:
            dropped["배송 조건"] += 1
            paid.append(i["price"])
        else:
            kept.append(i["price"])
    return sorted(kept), dropped, sorted(paid)


def paid_lower_bound(prices: list[int], paid: list[int]) -> int | None:
    """배송비 별도 경쟁 상품의 표시가 중 비교 가격 중앙값의 절반 이상인 최저값(drop_outliers와 같은 기준). 고객 결제 총액의 하한."""
    if not prices:
        return None
    floor = median(prices) * 0.5 if len(prices) >= 3 else 0
    return min((p for p in paid if p >= floor), default=None)


def dispersion(prices: list[int]) -> float | None:
    """상위 4분위 가격 ÷ 하위 4분위 가격. 크면 다른 상품이 섞였을 가능성이 있다. 가격 4개 미만은 None."""
    if len(prices) < 4:
        return None
    q1, _, q3 = quantiles(prices, n=4)
    return round(q3 / q1, 2) if q1 else None


def competitor_prices(matched_prices: list[int], keyword_prices: list[int], min_matched: int,
                      type_prices: list[int] = (), drop: bool = True) -> tuple[list[int], str]:
    """경쟁가 출처 우선순위: 같은 사진 → 같은 유형 → 키워드 상위 결과. drop=False면 저가 제거 없이 양수 가격만 쓴다(민감도 시험용)."""
    clean = drop_outliers if drop else (lambda ps: [p for p in ps if p and p > 0])
    if len(matched_prices) >= min_matched:
        return clean(matched_prices), "동일 상품"
    if len(type_prices) >= min_matched:
        return clean(list(type_prices)), "같은 유형"
    return clean(keyword_prices), "키워드 상위 결과"


def price_scenarios(prices: list[int], resale_min: int | None,
                    lowest_factor: float = 1.0, median_factor: float = 1.0, lowest_bound: int | None = None) -> dict:
    """최저가·경쟁 중앙가. 네이버 보정 계수를 곱한 뒤, 도매처 최저판매준수가격이 있으면 하한으로 올린다.
    lowest_bound: 배송비 별도 경쟁 상품의 표시가. 최저가 시나리오는 이 값이 더 낮으면 이 값을 쓴다(불리한 쪽)."""
    if not prices:
        return {"lowest": None, "median": None, "floored": False}
    low = min(prices) if lowest_bound is None else min(min(prices), lowest_bound)
    lowest, mid = round(low * lowest_factor), round(median(prices) * median_factor)
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


def return_burden(return_fee: int | None, double: bool | None, gross: int | None) -> dict:
    """반품 1건의 공급처 반품 배송비(무료배송 판매 시 2배 조건이면 2배)와, 그 비용을 메우는 데 필요한 판매 건수(비용 ÷ 주문당 마진).
    반품률·비용 부담 주체는 모르므로 손익에 넣지 않고 크기만 보인다. 값이 없거나 마진이 0 이하면 None."""
    if return_fee is None:
        return {"cost": None, "sales_to_cover": None}
    cost = return_fee * (2 if double else 1)
    return {"cost": cost, "sales_to_cover": round(cost / gross, 1) if gross and gross > 0 else None}

"""도매꾹 Open API 클라이언트. market=supply가 도매매다.

명세 출처(2026-10-10 확인): openapi.domeggook.com — 상품리스트 v4.1, 상품상세정보 v4.6.
JSON 응답의 최상위 래핑 구조는 문서에 예시가 없어 unwrap()으로 관대하게 푼다. 첫 실호출 후 확정한다.
"""
from __future__ import annotations

from .. import http
from ..config import secret

API_URL = "https://www.domeggook.com/ssl/api/"  # 2026-08-12 변경된 엔드포인트


def unwrap(data: dict) -> dict:
    """{"domeggook": {...}}처럼 키 하나로 감싼 응답을 벗긴다."""
    while isinstance(data, dict) and len(data) == 1:
        (only,) = data.values()
        if not isinstance(only, dict):
            break
        data = only
    return data


def as_list(value) -> list:
    """XML→JSON 변환에서 항목이 하나면 dict로 오는 경우를 리스트로 맞춘다."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def item_list(*, kw: str | None = None, ca: str | None = None, page: int = 1, size: int = 200,
              sort: str | None = None, **filters) -> tuple[dict, list[dict]]:
    """도매매 판매중 상품 목록. kw·ca 등 검색 조건이 하나 이상 필요하다. size ≤ 200."""
    if not (kw or ca or filters.get("id") or filters.get("itemNo")):
        raise ValueError("검색 조건(kw, ca, id, itemNo) 중 하나 이상 필요")
    data = unwrap(http.get_json(API_URL, params={
        "ver": "4.1", "mode": "getItemList", "aid": secret("DOMEGGOOK_API_KEY"),
        "market": "supply", "om": "json", "kw": kw, "ca": ca, "pg": page, "sz": size, "so": sort,
        **filters,
    }))
    if "errors" in data or "error" in data:
        raise RuntimeError(f"도매꾹 오류: {data}")
    items = as_list((data.get("list") or {}).get("item"))
    return data.get("header", {}), items


def item_view(no: int) -> dict:
    data = unwrap(http.get_json(API_URL, params={
        "ver": "4.6", "mode": "getItemView", "aid": secret("DOMEGGOOK_API_KEY"), "om": "json", "no": no,
    }))
    if "errors" in data or "error" in data:
        raise RuntimeError(f"도매꾹 오류: {data}")
    return data


def tiered_price(value, qty: int = 1) -> int | None:
    """정수 단가 또는 '1+3800|20+3500' 형식의 수량별 차등 단가에서 qty개 구매 시 단가."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    if "+" not in text:
        return int(float(text))
    price = None
    for tier in text.split("|"):
        min_qty, unit = tier.split("+")
        if qty >= int(min_qty):
            price = int(float(unit))
    return price


def ship_cost(pay, fee_type, fee, tbl, qty: int = 1) -> int | None:
    """qty개 주문 시 도매 배송비. 문서 규칙(상품상세정보 deli.dome.tbl):
    수량별차등 '1+2500|20+2350'은 구간별 금액, 수량별비례 '50+2500|100+2000'은 50개까지 2,500원·이후 100개마다 2,000원 추가.
    금액비노출·착불·형식 불명은 None(모름)."""
    if pay == "무료배송":
        return 0
    if pay == "착불":
        return None
    try:
        if fee_type == "고정배송비":
            return int(fee) if fee not in (None, "") else None
        if fee_type == "수량별차등":
            return tiered_price(tbl, qty)
        if fee_type == "수량별비례":
            tiers = [tuple(int(float(x)) for x in t.split("+")) for t in str(tbl).split("|")]
            (base_qty, base_fee), (step_qty, step_fee) = tiers[0], tiers[-1]
            if qty <= base_qty:
                return base_fee
            return base_fee + -(-(qty - base_qty) // step_qty) * step_fee
    except (ValueError, IndexError):
        return None
    return None


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _flag(value) -> bool | None:
    """JSON 변환 과정에서 문자열로 올 수 있는 불리언을 해석한다."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("true", "y", "1")
    return bool(value)


def _get(d: dict, path: str):
    for part in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def safety_cert(view: dict) -> dict:
    """detail.safetyCert는 dict 또는 인증별 dict 목록으로 온다(2026-10-16 실응답, 목록 1건 관측).
    목록이면 인증 유무는 하나라도 Y면 Y, 나머지 값은 ' / '로 합친다."""
    certs = [c for c in as_list(_get(view, "detail.safetyCert")) if isinstance(c, dict)]
    if len(certs) <= 1:
        return certs[0] if certs else {}
    merged = {k: " / ".join(str(c[k]) for c in certs if c.get(k) not in (None, "", "-")) or None
              for k in ("certType", "no", "type", "name")}
    merged["cert"] = "Y" if any(c.get("cert") == "Y" for c in certs) else certs[0].get("cert")
    merged["exem"] = "Y" if any(c.get("exem") == "Y" for c in certs) else certs[0].get("exem")
    return merged


def summarize(view: dict) -> dict:
    """상세 응답에서 선정에 필요한 값만 뽑는다. 확인되지 않는 값은 None으로 남긴다."""
    deli = _get(view, "deli.supply") or _get(view, "deli.dome") or {}  # 도매매 배송비가 없으면 도매 배송비 적용
    pay = deli.get("pay") or _get(view, "deli.pay")
    fee_type = deli.get("type")
    parents = as_list(_get(view, "category.parents.elem"))
    category_path = [p.get("name", "") for p in parents] + [_get(view, "category.current.name") or ""]
    return {
        "no": int(_get(view, "basis.no")),
        "status": _get(view, "basis.status"),
        "title": _get(view, "basis.title"),
        "adult": _flag(_get(view, "basis.adult")),
        "category_path": [c for c in category_path if c],
        "supply_price": tiered_price(_get(view, "price.supply")),
        "resale_min": _int(_get(view, "price.resale.minumum")),
        "resale_recommended": _int(_get(view, "price.resale.Recommand")),
        "inventory": _int(_get(view, "qty.inventory")),
        "ship_pay": pay,
        "ship_fee_type": fee_type,
        "ship_cost": ship_cost(pay, fee_type, deli.get("fee"), deli.get("tbl")),
        "merge_enable": _get(view, "deli.merge.enable"),
        "from_oversea": _flag(_get(view, "deli.fromOversea")),
        "image_usable": _flag(_get(view, "desc.license.usable")),
        "kc_cert": safety_cert(view).get("cert"),
        "return_fee": _int(_get(view, "return.deliAmt")),
        # 자동 대체 신호 후보. 수동 확인 결과와 비교해 쓸모를 검증한다.
        "price_compare_min": _int(_get(view, "priceCompare.min")),  # 타 사이트 동일 상품 최저가
        "price_compare_max": _int(_get(view, "priceCompare.max")),
        "sole": _flag(_get(view, "priceCompare.sole")),         # 도매꾹·도매매 단독판매
        "popular": _get(view, "popular.name"),                  # 도매꾹 인기상품 분류
        "thumb": _get(view, "thumb.large") or _get(view, "thumb.original"),
        "thumb_hash": _get(view, "thumb.hash"),
        "seller": _get(view, "seller.id"),
    }

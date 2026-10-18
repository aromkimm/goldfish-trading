"""판매 가능 조건 확인. 선별 통과 후보가 실제로 등록 가능한지 확인하고, 조건 불충족·정보 미확보면 선정 단계로 돌려보낸다.

확인 항목과 판정 규칙은 docs/product-selection-agent.md '판매 가능 조건 확인'을 따른다.
API로 얻는 값은 자동으로 채우고, 상세페이지가 이미지라 API로 얻을 수 없는 값은 사람이 입력한다.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime

from . import manual
from .sources import domeggook

FIELDS = ["no", "options", "cutoff", "return_method", "info_confirmed", "restriction_confirmed", "note"]


def info_deferred(desc) -> bool:
    """고시 값이 비었거나 상세페이지로 미뤄졌는지. 공급처마다 '상세정보 별도표기'·'[상세정보 별도표기]'·'상세정보별도표시'·
    '상품 상세정보에 별도 표기'처럼 띄어쓰기·괄호·표기/표시가 다르다."""
    s = re.sub(r"[\s\[\]()]", "", desc or "")
    return not s or ("상세" in s and "별도" in s and ("표기" in s or "표시" in s))


def _get(d, path: str):
    for part in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(part)
    return d


def parse_options(view: dict, base_price: int | None) -> list[dict]:
    """selectOpt(JSON 문자열)의 data를 옵션 목록으로. 옵션이 없으면 빈 목록.

    해석〔추정 — 옵션 문서 미확인, 실응답 형태 기준〕: sup=1 도매매 판매, supPrice 도매매 추가금, qty 옵션 재고, hid=1 숨김.
    """
    raw = view.get("selectOpt")
    if not raw:
        return []
    data = (json.loads(raw) if isinstance(raw, str) else raw).get("data") or {}
    options = []
    for i, (key, o) in enumerate(sorted(data.items()), 1):
        extra = int(float(o.get("supPrice") or 0))
        options.append({
            "index": i, "key": key, "name": o.get("name"),
            "price": None if base_price is None else base_price + extra, "extra": extra,
            "qty": int(o["qty"]) if str(o.get("qty", "")).lstrip("-").isdigit() else None,
            "sellable": o.get("sup") == "1" and o.get("hid") != "1",
        })
    return options


def collect(view: dict, today: date | None = None) -> dict:
    """판매 가능 조건 6개 묶음을 API 응답에서 채운다. 없는 값은 None."""
    today = today or date.today()
    s = domeggook.summarize(view)
    addr = _get(view, "return.addr") or {}
    vacation = _get(view, "seller.vacation") or {}
    date_end = _get(view, "basis.dateEnd")
    cert = domeggook.safety_cert(view)
    info = domeggook.as_list(_get(view, "detail.infoDuty.item"))
    return {
        "no": s["no"], "title": s["title"], "thumb": s["thumb"],
        # ① 상품번호·옵션·공급가
        "supply_price": s["supply_price"], "options": parse_options(view, s["supply_price"]),
        # ② 품절·출고
        "status": s["status"], "inventory": s["inventory"],
        "prep": _get(view, "deli.wating"), "prep_days": domeggook._int(_get(view, "deli.periodDeli")),
        "send_avg": float(_get(view, "deli.sendAvg")) if _get(view, "deli.sendAvg") not in (None, "") else None,
        "sale_end": date_end,
        "sale_end_days": (datetime.strptime(date_end[:10], "%Y-%m-%d").date() - today).days if date_end else None,
        "vacation": vacation or None,
        # ③ 배송비
        "ship_pay": s["ship_pay"], "ship_fee_type": s["ship_fee_type"], "ship_cost": s["ship_cost"],
        "fee_jeju": domeggook._int(_get(view, "deli.feeExtra.jeju")),
        "fee_islands": domeggook._int(_get(view, "deli.feeExtra.islands")),
        "merge": s["merge_enable"], "merge_base": domeggook._int(_get(view, "deli.merge.basePrice")),
        "shipping_area": _get(view, "deli.shippingArea"),
        # ④ 교환·반품
        "return_address": " ".join(x for x in (addr.get("zipcode"), addr.get("address1"), addr.get("address2")) if x) or None,
        "return_fee": s["return_fee"],
        "return_fee_double": domeggook._flag(_get(view, "return.deliAmtDouble")),
        # ⑤ 이미지 사용
        "image_usable": s["image_usable"], "image_msg": _get(view, "desc.license.msg"),
        # ⑥ 인증·표시·판매 제한
        "cert": cert.get("cert"), "cert_type": cert.get("certType"), "cert_no": cert.get("no"),
        "cert_exempt": cert.get("exem"),
        "country": _get(view, "detail.country"), "manufacturer": _get(view, "detail.manufacturer"),
        "info_duty_type": _get(view, "detail.infoDuty.type"),
        "info_duty_pending": [i.get("name") for i in info if info_deferred(i.get("desc"))],
        "deny_market": domeggook._flag(_get(view, "etc.denyMarket")),
        "resale_min": s["resale_min"], "adult": s["adult"], "tax": _get(view, "basis.tax"),
    }


def evaluate(c: dict, m: dict | None, rules: dict) -> tuple[str, list[str], list[str]]:
    """(결과, 반려 사유, 주의). 결과: verified 또는 returned. m은 사람이 입력한 값(없으면 None).

    반려는 두 경우뿐이다: 필요한 정보를 확보하지 못함, 배송·반품 조건이 맞지 않음(판매 불가 상태 포함).
    그 밖의 값은 판매 조건서에 그대로 적고 필요하면 주의로 표시한다.
    """
    fail, warn = [], []
    # ② 품절·출고
    if c["status"] != "판매중":
        fail.append(f"판매상태 {c['status']}")
    if c["inventory"] is None:
        fail.append("재고 정보 없음")
    elif c["inventory"] <= 0:
        fail.append("품절")
    if c["prep_days"] is None or c["send_avg"] is None:
        fail.append("출고 소요 기간 정보 없음")
    elif max(c["prep_days"], c["send_avg"]) > rules["prep_warn_days"]:
        warn.append(f"출고 소요 {rules['prep_warn_days']}일 초과 (준비 {c['prep_days']}일, 평균발송 {c['send_avg']}일)")
    if c["sale_end_days"] is not None and c["sale_end_days"] <= rules["sale_end_warn_days"]:
        warn.append(f"도매 판매기간 종료 {c['sale_end'][:10]} — 연장 여부 확인")
    if c["vacation"]:
        warn.append(f"공급사 휴가 {c['vacation']}")
    # ③ 배송비
    if c["ship_cost"] is None:
        fail.append(f"배송비 확정 불가({c['ship_pay']}/{c['ship_fee_type']})")
    if c["fee_jeju"] is None or c["fee_islands"] is None:
        fail.append("제주·도서산간 추가배송비 정보 없음")
    if c["merge"] not in ("y", "n", "c"):
        fail.append("묶음배송 조건 정보 없음")
    elif c["merge"] != "y":
        warn.append(f"묶음배송 {'불가' if c['merge'] == 'n' else '조건부'}")
    # ④ 교환·반품
    if not c["return_address"]:
        fail.append("반품 주소 없음")
    if c["return_fee"] is None:
        fail.append("반품 비용 없음")
    elif c["return_fee_double"]:
        warn.append(f"무료배송 판매 시 반품비 2배({c['return_fee'] * 2:,}원)")
    # ⑤ 이미지
    if c["image_usable"] is None:
        fail.append("이미지 사용 범위 정보 없음")
    elif not c["image_usable"]:
        warn.append("상세페이지 이미지 사용 불허 — 자체 이미지 필요")
    # ⑥ 판매 제한
    if c["deny_market"]:
        fail.append("denyMarket=true — 판매 제한 내용 미확보(의미 미확인)")
    if c["adult"]:
        fail.append("성인 상품")
    if c["resale_min"]:
        warn.append(f"최저판매준수가 {c['resale_min']:,}원")
    # 사람이 확인할 항목
    if m is None:
        fail.append("수동 확인 미입력")
    else:
        if c["options"]:
            picked = [int(x) for x in manual.parse_prices(m.get("options", ""))]
            if not picked:
                fail.append("판매할 옵션 미선택")
            for i in picked:
                opt = next((o for o in c["options"] if o["index"] == i), None)
                if opt is None:
                    fail.append(f"옵션 {i} 없음")
                elif not opt["sellable"]:
                    fail.append(f"옵션 {i} 도매매 판매 불가·숨김")
                elif opt["qty"] is not None and opt["qty"] <= 0:
                    fail.append(f"옵션 {i} 품절")
        if not (m.get("cutoff") or "").strip():
            fail.append("주문 마감 시간 미확보")
        if not (m.get("return_method") or "").strip():  # 반품 주소·비용은 API로 확인했고, 접수 경로는 등록 단계에서 확인한다
            warn.append("반품 접수 방법 미확인 — 등록 단계에서 확인")
        for key, label in (("info_confirmed", "상품정보고시·인증 확인"), ("restriction_confirmed", "판매 제한 확인")):
            if (m.get(key) or "").strip().upper() != "Y":
                fail.append(f"{label} 미완료")
    return ("returned" if fail else "verified"), fail, warn


_GUIDE = """<b>판매 가능 조건 확인</b> — API로 채운 값을 보고, 아래 항목만 입력한다. 빨간 글씨는 자동 확인에서 이미 걸린 항목이다.
<ol>
<li><b>판매할 옵션</b>: 옵션 표의 번호를 공백으로 (옵션이 없으면 비워 둔다).</li>
<li><b>주문 마감 시간</b>: 도매 상세페이지 이미지나 도매매 상품 문의로 확인 (예: 평일 14시).</li>
<li><b>반품 접수 방법</b>(선택): 상세에 공급사 안내가 있으면 적는다. 비어 있어도 반려하지 않고 등록 단계 확인 과제로 남긴다.</li>
<li><b>상품정보고시·인증 확인</b>: '상세정보 별도표기' 항목의 실제 값과 인증 필요 여부를 상세페이지에서 확인했으면 Y.</li>
<li><b>판매 제한 확인</b>: 상세페이지·판매자 공지에 스마트스토어 판매 제한이 없으면 Y.</li>
</ol>"""

_CARD = """<div class="card" data-no="{no}">
<img src="{thumb}" alt="" loading="lazy">
<div>
<b>{title}</b> <a href="{url}" target="_blank" rel="noopener">도매 상품</a>
<div class="meta">{meta}</div>
{fails}
{options}
<label>판매할 옵션 번호<input data-no="{no}" name="options"></label>
<label>주문 마감 시간<input data-no="{no}" name="cutoff"></label>
<label>반품 접수 방법<input data-no="{no}" name="return_method"></label>
<label>상품정보고시·인증 확인 (Y/N){info}<input data-no="{no}" name="info_confirmed"></label>
<label>판매 제한 확인 (Y/N)<input data-no="{no}" name="restriction_confirmed"></label>
<label>메모<input data-no="{no}" name="note"></label>
</div></div>"""


def _won(v) -> str:
    return "모름" if v is None else f"{v:,}원"


def render(items: list[dict], urls: dict, rules: dict, stamp: str) -> str:
    cards = []
    for c in items:
        _, fails, _ = evaluate(c, {"options": "", "cutoff": "-", "return_method": "-",
                                   "info_confirmed": "Y", "restriction_confirmed": "Y"}, rules)
        fails = [f for f in fails if f != "판매할 옵션 미선택"]
        opts = ""
        if c["options"]:
            rows = "".join(
                f"<tr><td>{o['index']}</td><td>{html.escape(o['name'] or '')}</td><td>{_won(o['price'])}</td>"
                f"<td>{'모름' if o['qty'] is None else o['qty']}</td><td>{'가능' if o['sellable'] else '불가'}</td></tr>"
                for o in c["options"])
            opts = f"<table><tr><th>번호</th><th>옵션</th><th>공급가</th><th>재고</th><th>도매매</th></tr>{rows}</table>"
        meta = (f"상품번호 {c['no']} · 공급가 {_won(c['supply_price'])} · 배송비 {_won(c['ship_cost'])} · "
                f"반품비 {_won(c['return_fee'])} · 출고 {c['prep'] or '모름'}(평균 {c['send_avg']}일)")
        info = f" — 별도표기 {len(c['info_duty_pending'])}항목" if c["info_duty_pending"] else ""
        cards.append(_CARD.format(
            no=c["no"], thumb=html.escape(c["thumb"] or ""), title=html.escape(c["title"] or ""),
            url=html.escape(urls.get(c["no"]) or ""), meta=html.escape(meta),
            fails="".join(f'<div class="warn">자동 확인 반려: {html.escape(f)}</div>' for f in fails),
            options=opts, info=html.escape(info)))
    return manual.page(kind="verify", title="판매 가능 조건 확인", guide=_GUIDE, cards=cards, fields=FIELDS,
                       done_field="info_confirmed", stamp=stamp)


def read_csv(path) -> dict[int, dict]:
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {int(r["no"]): r for r in csv.DictReader(f)}


def sheet(c: dict, m: dict, warn: list[str]) -> str:
    """등록에 쓸 판매 조건서(Markdown)."""
    picked = {int(x) for x in manual.parse_prices(m.get("options", ""))}
    opts = [o for o in c["options"] if o["index"] in picked]
    opt_text = ", ".join(f"{o['name']} {_won(o['price'])}" for o in opts) if opts else "단일 상품"
    lines = [
        f"### {c['title']} (상품번호 {c['no']})", "",
        f"- 옵션·공급가: {opt_text} / 기본 공급가 {_won(c['supply_price'])}",
        f"- 재고·출고: 재고 {c['inventory']}, {c['prep']}, 평균발송 {c['send_avg']}일, 주문 마감 {m.get('cutoff')}, 도매 판매기간 ~{(c['sale_end'] or '모름')[:10]}",
        f"- 배송비: {_won(c['ship_cost'])} ({c['ship_pay']}/{c['ship_fee_type']}), 제주 {_won(c['fee_jeju'])}, 도서산간 {_won(c['fee_islands'])}, 묶음배송 {c['merge']} (출고지 {c['shipping_area']})",
        f"- 교환·반품: {c['return_address']}, 반품비 {_won(c['return_fee'])}{' (무료배송 시 2배)' if c['return_fee_double'] else ''}, 접수 {(m.get('return_method') or '').strip() or '미확인(등록 단계에서 확인)'}",
        f"- 이미지: {'사용 가능' if c['image_usable'] else '불허'} — {c['image_msg'] or ''}",
        f"- 인증·표시: KC {c['cert'] or '정보 없음'} {c['cert_type'] or ''} {c['cert_no'] or ''}, 원산지 {c['country']}, 제조사 {c['manufacturer']}, 고시 품목 {c['info_duty_type']}, 과세 {c['tax']}",
        f"- 판매 제한: 확인 완료{' — 최저판매준수가 ' + _won(c['resale_min']) if c['resale_min'] else ''}",
    ]
    if warn:
        lines.append(f"- 주의: {'; '.join(warn)}")
    if (m.get("note") or "").strip():
        lines.append(f"- 메모: {m['note'].strip()}")
    return "\n".join(lines) + "\n"

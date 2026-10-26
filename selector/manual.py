"""수동 입력 화면(HTML) 생성과 CSV 반영. 네이버쇼핑 경쟁 확인에 쓰고, 판매 가능 조건 확인도 같은 틀을 쓴다.

쇼핑 검색 API가 없고 크롤링은 하지 않으므로, 경쟁가·동일 상품 판매자 수·검색 결과 상품 수는 사람이 확인한다.
화면(HTML)에서 입력하고 'CSV 저장'으로 받은 파일을 import한다.
"""
from __future__ import annotations

import csv
import html
import json
import re
import urllib.parse

FIELDS = ["no", "same_sellers", "same_prices", "note"]

_PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#fff; --fg:#1b1b1b; --muted:#666; --line:#ddd; --accent:#03a94f; --warn:#c0392b; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#161616; --fg:#eee; --muted:#aaa; --line:#333; --accent:#3ccf7a; --warn:#ff7b6b; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system, "Apple SD Gothic Neo", sans-serif; margin:0 auto; max-width:960px; padding:16px; }}
.guide {{ border:1px solid var(--line); border-radius:8px; padding:10px 16px; margin-bottom:8px; }}
.guide ol {{ margin:4px 0; padding-left:20px; }}
.card {{ display:grid; grid-template-columns:140px 1fr; gap:16px; border-top:1px solid var(--line); padding:16px 0; }}
.card img {{ width:140px; height:140px; object-fit:contain; border:1px solid var(--line); border-radius:6px; }}
.meta {{ color:var(--muted); font-size:13px; }}
.warn {{ color:var(--warn); font-size:13px; }}
table {{ border-collapse:collapse; font-size:13px; margin:6px 0; }}
td, th {{ border:1px solid var(--line); padding:2px 6px; text-align:left; }}
a.search {{ display:inline-block; margin:6px 6px 6px 0; padding:4px 10px; border-radius:6px; background:var(--accent); color:#fff; text-decoration:none; }}
label {{ display:block; margin-top:6px; font-size:13px; }}
input {{ width:100%; box-sizing:border-box; padding:6px; border:1px solid var(--line); border-radius:4px; background:var(--bg); color:var(--fg); }}
.done {{ opacity:.55; }}
button {{ position:sticky; bottom:16px; padding:10px 18px; border:0; border-radius:8px; background:var(--accent); color:#fff; font-size:15px; }}
@media (max-width:600px) {{ .card {{ grid-template-columns:1fr; }} }}
</style></head><body>
<h1>{title} ({count}건)</h1>
<div class="guide">{guide}
입력은 자동 저장된다. 끝나면 'CSV 저장' → 파일 경로를 Claude에게 전달.</div>
{cards}
<button onclick="save()">CSV 저장</button>
<script>
const KEY = "goldfish-{kind}-{stamp}";
const DONE_FIELD = "{done_field}";
let store = {{}};
try {{ store = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{}}
document.querySelectorAll("input").forEach(el => {{
  const k = el.dataset.no + ":" + el.name;
  if (store[k] !== undefined) el.value = store[k];
  el.addEventListener("input", () => {{
    store[k] = el.value;
    try {{ localStorage.setItem(KEY, JSON.stringify(store)); }} catch (e) {{}}
    mark();
  }});
}});
function mark() {{
  document.querySelectorAll(".card").forEach(c => {{
    c.classList.toggle("done", c.querySelector("[name=" + DONE_FIELD + "]").value !== "");
  }});
}}
mark();
function save() {{
  const fields = {fields};
  const q = v => '"' + String(v).replace(/"/g, '""') + '"';
  const rows = [fields.join(",")];
  document.querySelectorAll(".card").forEach(c => {{
    rows.push(fields.map(f => f === "no" ? c.dataset.no : q(c.querySelector("[name=" + f + "]").value)).join(","));
  }});
  const blob = new Blob(["\\ufeff" + rows.join("\\n")], {{type: "text/csv"}});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "{kind}_done.csv";
  a.click();
}}
</script></body></html>
"""

_CHECK_GUIDE = """'네이버 검색'을 열고 첫 페이지에서 왼쪽 사진과 <b>같은 사진·같은 옵션</b>을 파는 판매처를 찾는다.
<ol>
<li><b>판매처 수</b>: 같은 상품을 파는 판매처 수 (없으면 0)</li>
<li><b>결제 총액</b>: 판매처별 상품가+배송비, 공백 구분 (예: 24500 26000)</li>
<li><b>메모</b>: 판매처 URL, 규격·수량이 다르면 그 내용, 착불이면 "착불"</li>
</ol>"""

_CHECK_CARD = """<div class="card" data-no="{no}">
<img src="{thumb}" alt="" loading="lazy">
<div>
<b>{no} {title}</b>
<div class="meta">{cost} · <a href="{url}" target="_blank" rel="noopener">도매 상품</a></div>
<a class="search" href="{search_url}" target="_blank" rel="noopener">네이버 검색</a>
<label>판매처 수<input data-no="{no}" name="same_sellers" inputmode="numeric"></label>
<label>결제 총액<input data-no="{no}" name="same_prices"></label>
<label>메모<input data-no="{no}" name="note"></label>
</div></div>"""


def page(*, kind: str, title: str, guide: str, cards: list[str], fields: list[str], done_field: str,
         stamp: str) -> str:
    """수동 입력 화면 공통 틀. 각 card는 data-no와 fields 이름의 input을 가져야 한다."""
    return _PAGE.format(kind=kind, title=title, guide=guide, cards="\n".join(cards), count=len(cards),
                        fields=json.dumps(fields), done_field=done_field, stamp=stamp)


def search_url(keyword: str) -> str:
    return "https://search.shopping.naver.com/search/all?" + urllib.parse.urlencode({"query": keyword})


def cost_text(supply_price: int | None, ship_cost: int | None) -> str:
    """도매 원가 표기. 네이버 결제 총액과 같은 기준(배송 포함)으로 비교하게 한다."""
    if supply_price is None:
        return "도매가 모름"
    if ship_cost is None:
        return f"도매가 {supply_price:,}원 (배송비 모름)"
    return f"도매 원가 {supply_price + ship_cost:,}원 (공급가 {supply_price:,} + 배송 {ship_cost:,})"


def render(items: list[dict], stamp: str) -> str:
    """같은 상품 확인 화면. items: no, title, thumb, url, keyword, supply_price, ship_cost, title_query."""
    cards = [_CHECK_CARD.format(
        no=i["no"], thumb=html.escape(i.get("thumb") or ""), title=html.escape(i.get("title") or ""),
        cost=cost_text(i.get("supply_price"), i.get("ship_cost")), url=html.escape(i.get("url") or ""),
        search_url=html.escape(search_url(i.get("title_query") or i.get("title") or i["keyword"])),
    ) for i in items]
    return page(kind="manual", title="네이버 같은 상품 확인", guide=_CHECK_GUIDE, cards=cards, fields=FIELDS,
                done_field="same_sellers", stamp=stamp)


def parse_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def parse_prices(text: str) -> list[int]:
    """'12,900 13500원 / 9,900'처럼 섞인 입력에서 가격만 뽑는다."""
    return [int(p.replace(",", "")) for p in re.findall(r"\d[\d,]*", text or "") if p.replace(",", "")]


def read_csv(path) -> list[dict]:
    """빈 행(판매자 수 미입력)은 건너뛴다. 전체 상품 수·비슷한 상품 가격은 이전 형식 CSV에만 있다."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if not (r.get("same_sellers") or "").strip():
            continue
        out.append({
            "no": int(r["no"]),
            "total_results": parse_int(r.get("total_results", "")),
            "same_sellers": parse_int(r["same_sellers"]),
            "same_prices": parse_prices(r.get("same_prices", "")),
            "similar_prices": parse_prices(r.get("similar_prices", "")),
            "note": (r.get("note") or "").strip() or None,
        })
    return out

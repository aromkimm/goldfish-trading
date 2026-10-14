"""처리 흐름 단계. 단계 정의는 docs/product-selection-agent.md의 처리 흐름을 따른다."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date

from . import db, filters, manual, saturation, scoring, trend, verify
from .config import DATA_DIR, settings
from .sources import domeggook, elevenst, naver, naver_hub

LLM_DIR = DATA_DIR / "llm"
MANUAL_DIR = DATA_DIR / "manual"
VERIFY_DIR = DATA_DIR / "verify"
REPORT_DIR = DATA_DIR / "reports"


# 1. 후보 생성 ---------------------------------------------------------------

def search_supply(conn: sqlite3.Connection, *, kw=None, ca=None, pages=1, size=200, sort=None) -> int:
    added = 0
    query = json.dumps({"kw": kw, "ca": ca, "sort": sort, "size": size}, ensure_ascii=False)
    for page in range(1, pages + 1):
        header, items = domeggook.item_list(kw=kw, ca=ca, page=page, size=size, sort=sort)
        for item in items:
            cur = conn.execute(
                "INSERT OR IGNORE INTO candidates(no, title, url, source_query, added_at) VALUES (?,?,?,?,?)",
                (int(item["no"]), item.get("title"), item.get("url"), query, db.now()),
            )
            added += cur.rowcount
        if page >= int(header.get("numberOfPages") or 1):
            break
    conn.commit()
    return added


# 2. 상세 수집·규칙 제외 (매일 실행하면 변동성 스냅샷이 쌓인다) -------------------

def fetch_details(conn: sqlite3.Connection, *, stages=("new",), limit=None) -> dict:
    cfg = settings()["exclusion"]
    marks = ",".join("?" * len(stages))
    rows = conn.execute(f"SELECT no, stage FROM candidates WHERE stage IN ({marks})", stages).fetchall()
    counts = {"fetched": 0, "excluded": 0, "failed": 0}
    for row in rows[:limit]:
        try:
            view = domeggook.item_view(row["no"])
            summary = domeggook.summarize(view)
        except Exception as e:  # 한 상품 실패로 전체를 멈추지 않는다.
            counts["failed"] += 1
            print(f"상세 실패 {row['no']}: {e}")
            continue
        conn.execute("INSERT INTO supply_snapshots VALUES (?,?,?,?)",
                     (row["no"], db.now(), json.dumps(summary, ensure_ascii=False),
                      json.dumps(view, ensure_ascii=False)))
        counts["fetched"] += 1
        reason = filters.rule_exclusion(summary, cfg)
        if reason:
            conn.execute("UPDATE candidates SET stage='excluded', exclude_reason=? WHERE no=?",
                         (f"규칙: {reason}", row["no"]))
            counts["excluded"] += 1
        elif row["stage"] == "new":
            conn.execute("UPDATE candidates SET stage='detailed', title=? WHERE no=?",
                         (summary["title"], row["no"]))
    conn.commit()
    return counts


# 3. triage — Claude가 제외 판정·키워드 작성 -------------------------------------

def export_triage(conn: sqlite3.Connection) -> tuple[str, int]:
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    path = LLM_DIR / "triage_pending.jsonl"
    rows = conn.execute("SELECT no FROM candidates WHERE stage='detailed'").fetchall()
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            s = db.latest_snapshot(conn, row["no"])
            f.write(json.dumps({k: s.get(k) for k in (
                "no", "title", "category_path", "supply_price", "kc_cert", "image_usable", "merge_enable",
            )}, ensure_ascii=False) + "\n")
    return str(path), len(rows)


def import_triage(conn: sqlite3.Connection, path) -> dict:
    counts = {"triaged": 0, "excluded": 0}
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("exclude"):
            conn.execute("UPDATE candidates SET stage='excluded', exclude_reason=? WHERE no=? AND stage='detailed'",
                         (f"triage: {r['exclude']}", r["no"]))
            counts["excluded"] += 1
        else:
            keywords = [k.strip() for k in r.get("keywords", []) if k.strip()][:3]
            if not keywords:
                raise ValueError(f"{r['no']}: 제외가 아니면 키워드가 1개 이상 필요")
            conn.execute("UPDATE candidates SET stage='triaged', keywords=? WHERE no=? AND stage='detailed'",
                         (json.dumps(keywords, ensure_ascii=False), r["no"]))
            counts["triaged"] += 1
    conn.commit()
    return counts


# 4. 검색량 수집 ------------------------------------------------------------------------

def _keyword_stats(conn, keywords: list[str]) -> None:
    today = db.now()[:10]
    todo = [k for k in keywords
            if not ((r := db.latest_keyword_stats(conn, k)) and r["fetched_at"][:10] == today)]
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        rows = {r["relKeyword"]: r for r in naver.keyword_stats(batch)}
        for k in batch:
            r = rows.get(k.replace(" ", ""))
            conn.execute("INSERT INTO keyword_stats VALUES (?,?,?,?,?,?)", (
                k, db.now(),
                naver.parse_count(r.get("monthlyPcQcCnt")) if r else None,
                naver.parse_count(r.get("monthlyMobileQcCnt")) if r else None,
                r.get("compIdx") if r else None,
                json.dumps(r or {}, ensure_ascii=False),
            ))


def measure(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT no, keywords FROM candidates WHERE stage='triaged'").fetchall()
    _keyword_stats(conn, sorted({json.loads(r["keywords"])[0] for r in rows}))
    conn.executemany("UPDATE candidates SET stage='measured' WHERE no=?", [(r["no"],) for r in rows])
    conn.commit()
    return {"measured": len(rows)}


def _search_volume(ks) -> tuple[int | None, str]:
    """(순위·계산용 값, 표시 문자열). 10 미만은 계산에서 0으로, 표시는 '<10 포함'."""
    if not ks or ks["pc"] is None or ks["mobile"] is None:
        return None, "모름"
    if naver.LESS_THAN_10 in (ks["pc"], ks["mobile"]):
        return 0, "<10 포함"
    return ks["pc"] + ks["mobile"], f"{ks['pc'] + ks['mobile']:,}"


# 4-2. 추세·관심도 수집 — NAVER API HUB -------------------------------------------------------

def _shop_categories(category_path: list[str]) -> list[str]:
    """쇼핑 인사이트 분야를 조회할 순서〔추정 — 도매 카테고리 기준 매핑, 설정 trend 참조〕."""
    path = " ".join(category_path or [])
    order = ["생활/건강", "가구/인테리어", "스포츠/레저"]
    if "침구" in path:
        order = ["가구/인테리어", "생활/건강", "스포츠/레저"]
    elif (category_path or [""])[0] == "스포츠/레저":
        order = ["스포츠/레저", "생활/건강", "가구/인테리어"]
    return [naver_hub.SHOP_CATEGORY[n] for n in order]


def collect_trends(conn: sqlite3.Connection) -> dict:
    """대표 키워드별 검색어 트렌드·쇼핑 클릭 추이·블로그·카페 지표. 같은 날 수집한 키워드는 건너뛴다."""
    cfg = settings()["trend"]
    start, end = trend.window()
    today = db.now()[:10]
    keywords: dict[str, list[str]] = {}
    for c in conn.execute("SELECT no, keywords FROM candidates WHERE stage IN ('measured', 'checked', 'verified')"):
        k = json.loads(c["keywords"])[0]
        if k not in keywords:
            keywords[k] = _shop_categories(db.latest_snapshot(conn, c["no"])["category_path"])
    todo = [k for k in keywords if not ((r := db.latest_trend(conn, k)) and r["fetched_at"][:10] == today)]
    counts = {"keywords": len(todo), "failed": 0}
    search, shop = {}, {}
    for i in range(0, len(todo), 5):  # 한 호출에 5개. 상대값이 같은 배수로 바뀌어도 증감·계절 비율은 그대로다.
        search.update(naver_hub.search_trend(todo[i:i + 5], start, end))
    for attempt in range(3):  # 1순위 분야부터, 데이터가 부족한 키워드만 다음 분야로
        by_cat: dict[str, list[str]] = {}
        for k in todo:
            if k in shop and trend.months_with_data(shop[k][1]) >= cfg["min_months"]:
                continue
            by_cat.setdefault(keywords[k][attempt], []).append(k)
        for cat, ks in by_cat.items():
            for i in range(0, len(ks), 5):
                for k, series in naver_hub.shopping_keywords(cat, ks[i:i + 5], start, end).items():
                    if k not in shop or trend.months_with_data(series) > trend.months_with_data(shop[k][1]):
                        shop[k] = (cat, series)
    for k in todo:
        try:
            blog_total = naver_hub.search_total("blog", k)
            blog_dates = naver_hub.blog_recent(k)
            cafe_total = naver_hub.search_total("cafearticle", k)
        except Exception as e:
            counts["failed"] += 1
            print(f"관심도 수집 실패 {k}: {e}")
            blog_total = blog_dates = cafe_total = None
        cat, series = shop.get(k, (None, None))
        conn.execute("INSERT INTO trends VALUES (?,?,?,?,?,?,?,?,?,?)", (
            k, db.now(), start, end, json.dumps(search.get(k)), cat, json.dumps(series),
            blog_total, json.dumps(blog_dates), cafe_total))
        conn.commit()
    return counts


def _trend_metrics(conn, keyword: str) -> dict:
    t = db.latest_trend(conn, keyword)
    if t is None:
        return {"trend_growth": None, "season_index": None, "shop_growth": None, "shop_months": None,
                "blog_total": None, "blog_rate": None, "cafe_total": None}
    search = json.loads(t["search_series"] or "null") or []
    shop = json.loads(t["shop_series"] or "null") or []
    min_months = settings()["trend"]["min_months"]
    shop_ok = trend.months_with_data(shop) >= min_months
    return {
        "trend_growth": trend.growth(search), "season_index": trend.season_index(search),
        "shop_growth": trend.growth(shop) if shop_ok else None, "shop_months": trend.months_with_data(shop),
        "blog_total": t["blog_total"], "blog_rate": trend.blog_rate(json.loads(t["blog_dates"] or "[]")),
        "cafe_total": t["cafe_total"],
    }


# 5. 경쟁·가격 수집 — 11번가 ------------------------------------------------------------------

def compete(conn: sqlite3.Connection, *, limit: int | None = None) -> dict:
    """도매 상품명 검색으로 같은 상품 판매자·가격을, 대표 키워드 검색으로 전체 상품 수·비슷한 상품 가격을 모은다."""
    cfg = settings()["competition"]
    rows = conn.execute("SELECT no, keywords FROM candidates WHERE stage='measured'").fetchall()[:limit]
    keyword_cache: dict[str, tuple[int, list[int]]] = {}
    counts = {"checked": 0, "failed": 0}
    for row in rows:
        s = db.latest_snapshot(conn, row["no"])
        keyword = json.loads(row["keywords"])[0]
        query = elevenst.query_from_title(s["title"])
        try:
            title_total, items = elevenst.search(query, size=cfg["title_top"])
            result = saturation.match(saturation.fetch_image(s["thumb"]), items, cfg["dhash_max_distance"])
            if keyword not in keyword_cache:
                total, kw_items = elevenst.search(keyword, size=cfg["keyword_top"], sort="CP")
                keyword_cache[keyword] = (total, [i["price"] for i in kw_items if i.get("price")])
        except Exception as e:  # 한 상품 실패로 전체를 멈추지 않는다.
            counts["failed"] += 1
            print(f"경쟁 수집 실패 {row['no']}: {e}")
            continue
        kw_total, kw_prices = keyword_cache[keyword]
        conn.execute("INSERT INTO competition VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
            row["no"], db.now(), query, title_total, result["checked"], result["image_failed"],
            result["sellers"], json.dumps(result["prices"]), result["reviews"],
            keyword, kw_total, json.dumps(kw_prices)))
        conn.execute("UPDATE candidates SET stage='checked' WHERE no=?", (row["no"],))
        counts["checked"] += 1
        conn.commit()
    return counts


# 네이버쇼핑 수동 확인 — 11번가 결과가 네이버를 반영하는지 검증하는 표본용 ------------------------

def export_manual(conn: sqlite3.Connection, shortlist: int | None = None, nos: list[int] | None = None) -> tuple[str, int]:
    """검색량 순으로 상위 후보를 골라 확인 화면을 만든다. 대표 키워드당 개수를 제한한다〔선별 기준은 제안값〕."""
    cfg = settings()["manual_check"]
    shortlist = shortlist or cfg["shortlist"]
    items = []
    for c in conn.execute("SELECT * FROM candidates WHERE stage IN ('measured', 'checked')"):
        keyword = json.loads(c["keywords"])[0]
        volume, _ = _search_volume(db.latest_keyword_stats(conn, keyword))
        s = db.latest_snapshot(conn, c["no"])
        items.append({"no": c["no"], "title": s["title"], "thumb": s.get("thumb"), "url": c["url"],
                      "keyword": keyword, "supply_price": s.get("supply_price"), "_volume": volume})
    items.sort(key=lambda i: (i["_volume"] is None, -(i["_volume"] or 0), i["no"]))
    picked, per_keyword = [], {}
    for i in items:
        if per_keyword.get(i["keyword"], 0) < cfg["per_keyword"]:
            picked.append(i)
            per_keyword[i["keyword"]] = per_keyword.get(i["keyword"], 0) + 1
    items = [i for i in items if i["no"] in nos] if nos else picked[:shortlist]
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    path = MANUAL_DIR / f"check-{stamp}.html"
    path.write_text(manual.render(items, stamp), encoding="utf-8")
    return str(path), len(items)


def import_manual(conn: sqlite3.Connection, path) -> int:
    rows = manual.read_csv(path)
    for r in rows:
        conn.execute("INSERT INTO manual_checks VALUES (?,?,?,?,?,?,?)", (
            r["no"], db.now(), r["total_results"], r["same_sellers"],
            json.dumps(r["same_prices"]), json.dumps(r["similar_prices"]), r["note"]))
    conn.commit()
    return len(rows)


# 6. 마진·점수·비교표 -------------------------------------------------------------

def volatility(conn: sqlite3.Connection, no: int) -> dict:
    snaps = [json.loads(r["summary"]) | {"_at": r["fetched_at"]} for r in conn.execute(
        "SELECT summary, fetched_at FROM supply_snapshots WHERE no=? ORDER BY fetched_at", (no,))]
    changes = 0
    for prev, cur in zip(snaps, snaps[1:]):
        for key in ("supply_price", "status", "ship_cost"):
            changes += prev.get(key) != cur.get(key)
        changes += (prev.get("inventory") == 0) != (cur.get("inventory") == 0)
    days = (date.fromisoformat(snaps[-1]["_at"][:10]) - date.fromisoformat(snaps[0]["_at"][:10])).days
    return {"snapshots": len(snaps), "days": days, "changes": changes}


def build_rows(conn: sqlite3.Connection) -> list[dict]:
    cfg = settings()
    fee = cfg["pricing"]["platform_fee_rate"]
    rows = []
    for c in conn.execute("SELECT * FROM candidates WHERE stage IN ('checked', 'verified')"):
        s = db.latest_snapshot(conn, c["no"])
        keyword = json.loads(c["keywords"])[0]
        ks = db.latest_keyword_stats(conn, keyword)
        comp = db.latest_competition(conn, c["no"])
        if comp is None:
            continue
        prices, basis = scoring.competitor_prices(
            json.loads(comp["same_prices"]), json.loads(comp["similar_prices"]),
            cfg["pricing"]["min_matched_for_same_product_price"])
        sc = scoring.price_scenarios(prices, s.get("resale_min"))
        m_low = scoring.margin(sc["lowest"], s["supply_price"], s["ship_cost"], fee)
        m_mid = scoring.margin(sc["median"], s["supply_price"], s["ship_cost"], fee)
        volume, volume_text = _search_volume(ks)
        total = comp["keyword_total"]
        density = round(total / volume, 2) if total is not None and volume else None
        rows.append({
            "no": c["no"], "stage": c["stage"], "title": s["title"], "keyword": keyword,
            "keywords": json.loads(c["keywords"]),
            "url": c["url"],
            "search_volume": volume, "search_volume_text": volume_text, "comp_idx": ks["comp_idx"] if ks else None,
            "shop_total": total, "competition_density": density,
            "saturation": comp["same_sellers"], "same_reviews": comp["same_reviews"],
            "sat_checked": comp["checked"], "sat_title_total": comp["title_total"], "title_query": comp["title_query"],
            "checked_at": comp["fetched_at"][:10],
            "price_basis": basis, "price_floored": sc["floored"],
            "price_lowest": sc["lowest"], "price_median": sc["median"],
            "supply_price": s["supply_price"], "ship_cost": s["ship_cost"], "ship_fee_type": s["ship_fee_type"],
            "resale_min": s.get("resale_min"), "return_fee": s.get("return_fee"),
            "margin_lowest": m_low, "margin_median": m_mid,
            "gross_margin_rate": m_low["gross_rate"],  # 점수는 보수적으로 최저가 시나리오 기준
            "image_usable": s.get("image_usable"), "kc_cert": s.get("kc_cert"), "merge_enable": s.get("merge_enable"),
            **_trend_metrics(conn, keyword),
            "price_compare_min": s.get("price_compare_min"), "price_compare_max": s.get("price_compare_max"),
            "sole": s.get("sole"), "popular": s.get("popular"),
            "volatility": volatility(conn, c["no"]),
            "review": json.loads(c["review"]) if c["review"] else None,
        })
    scores = scoring.score({r["no"]: r for r in rows}, cfg["scoring"]["weights"], cfg["scoring"]["required"])
    for r in rows:
        r.update(scores[r["no"]])
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
    picked, per_keyword = 0, {}
    for r in rows:  # 추천 목록: 점수 순, 대표 키워드당 개수 제한
        ok = (r["score"] is not None and picked < cfg["scoring"]["recommend_top"]
              and per_keyword.get(r["keyword"], 0) < cfg["scoring"]["recommend_per_keyword"])
        r["recommended"] = ok
        if ok:
            picked += 1
            per_keyword[r["keyword"]] = per_keyword.get(r["keyword"], 0) + 1
    return rows


def _fmt(v, pct=False) -> str:
    if v is None:
        return "모름"
    if pct:
        return f"{v * 100:.1f}%"
    return f"{v:,}" if isinstance(v, int) else str(v)


def write_report(conn: sqlite3.Connection) -> tuple[str, str, int]:
    rows = build_rows(conn)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stem = REPORT_DIR / f"{date.today().isoformat()}-candidates"
    fee_set = settings()["pricing"]["platform_fee_rate"] is not None
    lines = [
        f"# 상품 후보 비교표 — {date.today().isoformat()}",
        "",
        "- 점수·마진은 추정치다. 점수는 이번 배치 안의 상대 순위이며 판매량 예측이 아니다(가중치 미확정 제안값). 마진·같은 상품 판매자 수가 없으면 점수를 매기지 않는다.",
        "- 추천: 점수 순 상위 후보 중 같은 대표 키워드는 2개까지. 판매 가능 조건 확인 대상이다.",
        "- 마진 가정: 무료배송으로 판매해 도매 배송비를 판매가에서 부담한다. 마진율 분모는 판매가다.",
        "- 수수료 반영 마진: " + ("설정된 수수료율 적용." if fee_set else "수수료율 미확인이라 모름. 표의 마진은 수수료 차감 전이다."),
        "- 포화도·상품 수·경쟁가: 11번가 상품검색 기준(수집일 표기). 같은 상품 판매자 수는 도매 상품명 검색 상위 결과에서 도매 이미지와 같은 사진을 쓴 판매자 수다. 이미지 가공·검색 범위 밖 판매자는 세지 않아 과소 추정될 수 있고, 네이버와의 일치 여부는 검증 전이다.",
        "- 같은 상품 리뷰 수: 11번가에서 같은 사진을 쓴 상품들의 리뷰 합계. 판매 흔적이며 판매량이 아니다.",
        "- 검색 추세: 네이버 검색어 트렌드 기준 최근 3개월 ÷ 그 전 3개월(증감), 직전 달 ÷ 12개월 평균(계절). 상대값 비율이며 검색량이 아니다. 블로그 글 수·작성 속도는 참고용이고 점수에 넣지 않는다.",
        "",
        "| 순위 | 추천 | 상품 | 키워드 | 월 검색수 | 검색 추세(증감/계절) | 11번가 상품 수 | 경쟁 밀도 | 같은 상품 판매자(리뷰) | 경쟁가 기준 | 최저가 / 마진 | 중앙가 / 마진 | 도매가+배송 | 점수 | 모름·주의 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(rows, 1):
        notes = [f"지표 없음: {', '.join(r['missing'])}"] if r["missing"] else []
        if r["image_usable"] is False:
            notes.append("이미지 사용 불허")
        if r["price_floored"]:
            notes.append(f"최저판매준수가 {r['resale_min']:,} 적용")
        if r["ship_cost"] is None:
            notes.append(f"배송비 모름({r['ship_fee_type']})")
        if r["sat_title_total"] and r["sat_title_total"] > r["sat_checked"]:
            notes.append(f"상품명 검색 {r['sat_title_total']:,}건 중 {r['sat_checked']}건만 비교")
        v = r["volatility"]
        notes.append(f"변동 {v['changes']}회/{v['days']}일")
        ml, mm = r["margin_lowest"], r["margin_median"]
        lines.append(" | ".join([
            f"| {i}", "✓" if r["recommended"] else "", f"[{r['title']}]({r['url']})", r["keyword"], r["search_volume_text"],
            f"{_fmt(r['trend_growth'])} / {_fmt(r['season_index'])}", _fmt(r["shop_total"]),
            _fmt(r["competition_density"]), f"{_fmt(r['saturation'])} ({_fmt(r['same_reviews'])})",
            r["price_basis"],
            f"{_fmt(r['price_lowest'])} / {_fmt(ml['gross_rate'], True)}",
            f"{_fmt(r['price_median'])} / {_fmt(mm['gross_rate'], True)}",
            f"{_fmt(r['supply_price'])}+{_fmt(r['ship_cost'])}", _fmt(r["score"]), "; ".join(notes) + " |",
        ]))
    reviewed = [r for r in rows if r["review"]]
    if reviewed:
        lines += ["", "## 상위 후보 검토", ""]
        for r in reviewed:
            rv = r["review"]
            lines += [f"### {r['title']}", "", f"- 근거: {rv.get('rationale', '')}",
                      f"- 리스크: {rv.get('risks', '')}", f"- 모름: {rv.get('unknowns', '')}", ""]
    md_path = f"{stem}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    csv_path = f"{stem}.csv"
    flat_keys = ["no", "recommended", "title", "keyword", "search_volume_text", "comp_idx", "shop_total", "competition_density",
                 "saturation", "same_reviews", "sat_checked", "sat_title_total", "title_query", "checked_at", "price_basis", "price_lowest", "price_median",
                 "resale_min", "supply_price", "ship_cost", "return_fee", "image_usable", "kc_cert",
                 "merge_enable", "trend_growth", "season_index", "shop_growth", "shop_months", "blog_total", "blog_rate",
                 "cafe_total", "price_compare_min", "price_compare_max", "sole", "popular", "score", "url"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(flat_keys + ["gross_rate_lowest", "gross_rate_median", "net_rate_lowest", "net_rate_median"])
        for r in rows:
            w.writerow([r[k] for k in flat_keys] + [r["margin_lowest"]["gross_rate"], r["margin_median"]["gross_rate"],
                                                    r["margin_lowest"]["net_rate"], r["margin_median"]["net_rate"]])
    return md_path, csv_path, len(rows)


# 7. 상위 후보 검토 — Claude가 근거·리스크·모름 작성 --------------------------------------

def export_review(conn: sqlite3.Connection, top: int) -> tuple[str, int]:
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    path = LLM_DIR / "review_pending.jsonl"
    rows = [r for r in build_rows(conn) if r["recommended"]][:top]
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != "review"}, ensure_ascii=False) + "\n")
    return str(path), len(rows)


def import_review(conn: sqlite3.Connection, path) -> int:
    n = 0
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if line.strip():
            r = json.loads(line)
            conn.execute("UPDATE candidates SET review=? WHERE no=?", (json.dumps(
                {k: r.get(k) for k in ("rationale", "risks", "unknowns")}, ensure_ascii=False), r["no"]))
            n += 1
    conn.commit()
    return n


# 8. 판매 가능 조건 확인 — 추천 후보를 등록 가능한지 확인하고, 안 되면 선정 단계로 돌려보낸다 -------------

def export_verify(conn: sqlite3.Connection, top: int | None = None, nos: list[int] | None = None) -> tuple[str, int]:
    rules = settings()["verification"]
    if not nos:
        nos = [r["no"] for r in build_rows(conn) if r["stage"] == "checked" and r["recommended"]][:top or rules["top"]]
    items, urls = [], {}
    for no in nos:
        view = domeggook.item_view(no)  # 확인 시점의 최신 정보로 판단한다
        conn.execute("INSERT INTO supply_snapshots VALUES (?,?,?,?)", (
            no, db.now(), json.dumps(domeggook.summarize(view), ensure_ascii=False),
            json.dumps(view, ensure_ascii=False)))
        items.append(verify.collect(view))
        urls[no] = conn.execute("SELECT url FROM candidates WHERE no=?", (no,)).fetchone()["url"]
    conn.commit()
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    (VERIFY_DIR / f"pending-{stamp}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    path = VERIFY_DIR / f"verify-{stamp}.html"
    path.write_text(verify.render(items, urls, rules, stamp), encoding="utf-8")
    return str(path), len(items)


def import_verify(conn: sqlite3.Connection, path) -> dict:
    rules = settings()["verification"]
    pending = sorted(VERIFY_DIR.glob("pending-*.json"))
    if not pending:
        raise FileNotFoundError("verify-export를 먼저 실행한다")
    conditions = {c["no"]: c for c in json.loads(pending[-1].read_text(encoding="utf-8"))}
    entered = verify.read_csv(path)
    counts, sheets, returned = {"verified": 0, "returned": 0}, [], []
    for no, c in conditions.items():
        m = entered.get(no)
        result, reasons, warnings = verify.evaluate(c, m, rules)
        conn.execute("INSERT INTO verifications VALUES (?,?,?,?,?,?,?)", (
            no, db.now(), json.dumps(c, ensure_ascii=False), json.dumps(m or {}, ensure_ascii=False),
            result, json.dumps(reasons, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False)))
        if result == "verified":
            conn.execute("UPDATE candidates SET stage='verified' WHERE no=?", (no,))
            sheets.append(verify.sheet(c, m, warnings))
        else:
            conn.execute("UPDATE candidates SET stage='returned', exclude_reason=? WHERE no=?",
                         ("검증 반려: " + "; ".join(reasons), no))
            returned.append(f"- {c['title']} ({no}): {'; '.join(reasons)}")
        counts[result] += 1
    conn.commit()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"{date.today().isoformat()}-sell-conditions.md"
    out.write_text("\n".join([
        f"# 판매 조건서 — {date.today().isoformat()}", "",
        "상품 추천 에이전트가 추천하고 판매 가능 조건 확인을 통과한 상품. 등록에 필요한 값을 정리했다.", "",
        *sheets,
        "## 선정 단계로 돌려보낸 상품", "", *(returned or ["- 없음"]), "",
    ]), encoding="utf-8")
    counts["sheet"] = str(out)
    return counts

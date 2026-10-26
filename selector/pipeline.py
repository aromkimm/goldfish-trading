"""처리 흐름 단계. 단계 정의는 docs/product-selection-agent.md의 처리 흐름을 따른다."""
from __future__ import annotations

import csv
import hashlib
import uuid
import json
import sqlite3
from datetime import date

from . import db, filters, manual, saturation, scoring, trend, verify
from .config import DATA_DIR, settings
from .sources import commerce, domeggook, elevenst, naver, naver_hub

LLM_DIR = DATA_DIR / "llm"
MANUAL_DIR = DATA_DIR / "manual"
VERIFY_DIR = DATA_DIR / "verify"
REPORT_DIR = DATA_DIR / "reports"


def use_data_dir(path) -> None:
    """작업 파일(llm·manual·verify·reports)을 path 아래에 둔다. 별도 평가 배치를 기존 실행과 섞지 않기 위해 쓴다."""
    global LLM_DIR, MANUAL_DIR, VERIFY_DIR, REPORT_DIR
    LLM_DIR, MANUAL_DIR, VERIFY_DIR, REPORT_DIR = (path / "llm", path / "manual", path / "verify", path / "reports")


# 1. 후보 생성 ---------------------------------------------------------------

def search_supply(conn: sqlite3.Connection, *, kw=None, ca=None, pages=1, size=200, sort=None, skip=frozenset()) -> int:
    """skip: 이미 다른 배치에서 쓴 상품번호. 새 표본에 넣지 않는다."""
    added = 0
    query = json.dumps({"kw": kw, "ca": ca, "sort": sort, "size": size}, ensure_ascii=False)
    for page in range(1, pages + 1):
        header, items = domeggook.item_list(kw=kw, ca=ca, page=page, size=size, sort=sort)
        for item in items:
            if int(item["no"]) in skip:
                print(f"건너뜀 {item['no']}: 다른 DB에 있는 후보")
                continue
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


def set_keywords(conn: sqlite3.Connection, no: int, keywords: list[str], reason: str) -> None:
    """대표 키워드 교체. 검토에서 검색 의도가 상품과 다르다고 판단한 경우에 쓴다. 이후 measure·trend·compete를 다시 돈다."""
    keywords = [k.strip() for k in keywords if k.strip()][:3]
    if not keywords:
        raise ValueError("키워드가 1개 이상 필요")
    cur = conn.execute("UPDATE candidates SET keywords=?, stage='triaged' WHERE no=? AND stage IN "
                       "('triaged', 'measured', 'checked')", (json.dumps(keywords, ensure_ascii=False), no))
    if cur.rowcount == 0:
        raise ValueError(f"{no}: 키워드를 바꿀 수 있는 단계가 아님")
    print(f"{no}: 대표 키워드 → {keywords} ({reason})")
    conn.commit()


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
    """(순위·계산용 하한, 표시 문자열). `<10`은 0~9 범위라 임의값으로 채우지 않고, 확실한 하한(알려진 값 + 0)을 계산에 쓴다.
    표시는 범위로 한다(예: PC <10·모바일 1,000 → '1,000~1,009')."""
    if not ks or ks["pc"] is None or ks["mobile"] is None:
        return None, "모름"
    parts = (ks["pc"], ks["mobile"])
    ranged = sum(p == naver.LESS_THAN_10 for p in parts)
    low = sum(p for p in parts if p != naver.LESS_THAN_10)
    if not ranged:
        return low, f"{low:,}"
    return low, f"{low:,}~{low + 9 * ranged:,}" if low else f"<{10 * ranged}"


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

def compete(conn: sqlite3.Connection, *, limit: int | None = None, redo: bool = False) -> dict:
    """도매 상품명 검색으로 같은 사진·같은 유형 판매자와 가격을, 대표 키워드 검색으로 전체 상품 수·비슷한 상품 가격·키워드 적합도를 모은다."""
    cfg = settings()["competition"]
    stages = "('measured', 'checked')" if redo else "('measured')"
    rows = conn.execute(f"SELECT no, keywords FROM candidates WHERE stage IN {stages}").fetchall()[:limit]
    keyword_cache: dict[str, tuple[int, list[int], list[str]]] = {}
    counts = {"checked": 0, "failed": 0}
    for row in rows:
        s = db.latest_snapshot(conn, row["no"])
        keyword = json.loads(row["keywords"])[0]
        query = elevenst.query_from_title(s["title"])
        try:
            title_total, items = elevenst.search(query, size=cfg["title_top"])
            result = saturation.match(saturation.fetch_image(s["thumb"]), items, cfg["dhash_max_distance"])
            typed = saturation.same_type(query, items, cfg["same_type_overlap"])
            if keyword not in keyword_cache:
                keyword_cache[keyword] = elevenst.search(keyword, size=cfg["keyword_top"], sort="CP")
        except Exception as e:  # 한 상품 실패로 전체를 멈추지 않는다.
            counts["failed"] += 1
            print(f"경쟁 수집 실패 {row['no']}: {e}")
            continue
        kw_total, kw_items = keyword_cache[keyword]
        kw_names = [i.get("name") or "" for i in kw_items]
        fit = (round(sum(saturation.word_overlap(query, n) for n in kw_names) / len(kw_names), 2)
               if kw_names else None)
        # 가격 비교 조건(배송·규격)을 나중에 다시 판정할 수 있도록 검색 결과를 상품 단위로 남긴다.
        stored = [{"name": it.get("name"), "seller": it.get("seller"), "price": it.get("price"),
                   "delivery": it.get("delivery"), "photo": photo,
                   "type": saturation.word_overlap(query, it.get("name")) >= cfg["same_type_overlap"]}
                  for it, photo in zip(items, result["flags"])]
        kw_stored = [{"name": i.get("name"), "price": i.get("price"), "delivery": i.get("delivery")} for i in kw_items]
        conn.execute(
            "INSERT INTO competition (no, fetched_at, title_query, title_total, checked, image_failed, same_sellers,"
            " same_prices, same_reviews, keyword, keyword_total, similar_prices, type_sellers, type_prices,"
            " keyword_fit, keyword_names, items, keyword_items) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                row["no"], db.now(), query, title_total, result["checked"], result["image_failed"],
                result["sellers"], json.dumps(result["prices"]), result["reviews"],
                keyword, kw_total, json.dumps([i["price"] for i in kw_items if i.get("price")]),
                typed["sellers"], json.dumps(typed["prices"]), fit,
                json.dumps(kw_names[:15], ensure_ascii=False), json.dumps(stored, ensure_ascii=False),
                json.dumps(kw_stored, ensure_ascii=False)))
        conn.execute("UPDATE candidates SET stage='checked' WHERE no=?", (row["no"],))
        counts["checked"] += 1
        conn.commit()
    return counts


# 5-2. 네이버 카탈로그 조회 — 커머스API (참고 지표) ------------------------------------------

def collect_catalogs(conn: sqlite3.Connection, *, redo: bool = False) -> dict:
    """도매 상품명 검색어로 네이버쇼핑 카탈로그를 조회해 같은 유형·이름 일치 카탈로그 수를 남긴다. 같은 날 조회한 후보는 건너뛴다."""
    import time as _time

    cfg = settings()["catalog"]
    today = db.now()[:10]
    counts = {"checked": 0, "skipped": 0, "failed": 0}
    for c in conn.execute("SELECT no FROM candidates WHERE stage IN ('measured', 'checked', 'verified')").fetchall():
        last = db.latest_catalog(conn, c["no"])
        if last and last["fetched_at"][:10] == today and not redo:
            counts["skipped"] += 1
            continue
        title = db.latest_snapshot(conn, c["no"])["title"]
        query, full = elevenst.query_from_title(title), elevenst.query_from_title(title, words=50)
        try:
            total, items = commerce.catalogs(query, size=cfg["size"])
        except Exception as e:
            counts["failed"] += 1
            print(f"카탈로그 조회 실패 {c['no']}: {e}")
            continue
        scored = sorted(((saturation.word_overlap(query, i.get("name")), i.get("name") or "") for i in items), reverse=True)
        similar = [name for ov, name in scored if ov >= cfg["similar_overlap"]]
        exact = [i.get("name") for i in items  # 도매 상품명 전체와 거의 같은 이름 = 이미 가격비교 묶음이 있을 가능성
                 if saturation.word_overlap(full, i.get("name")) >= cfg["exact_title_overlap"]]
        conn.execute("INSERT INTO catalog_checks VALUES (?,?,?,?,?,?,?)", (
            c["no"], db.now(), query, total, len(similar), len(exact), json.dumps(similar[:10], ensure_ascii=False)))
        conn.commit()
        counts["checked"] += 1
        _time.sleep(cfg["pause_seconds"])
    return counts


# 네이버쇼핑 수동 확인 — 11번가 결과가 네이버를 반영하는지 검증하는 표본용 ------------------------

def export_manual(conn: sqlite3.Connection, nos: list[int] | None = None) -> tuple[str, int]:
    """네이버쇼핑 수동 확인 화면. 기본 대상은 선별 통과 후보 전부이고, nos로 직접 지정할 수 있다."""
    nos = nos or [r["no"] for r in build_rows(conn, sensitivity=False) if r["selected"]]
    items = []
    for no in nos:
        c = conn.execute("SELECT * FROM candidates WHERE no=?", (no,)).fetchone()
        if c is None or not c["keywords"]:
            raise ValueError(f"{no}: 키워드가 있는 후보가 아님")
        s = db.latest_snapshot(conn, no)
        items.append({"no": no, "title": s["title"], "thumb": s.get("thumb"), "url": c["url"],
                      "keyword": json.loads(c["keywords"])[0], "supply_price": s.get("supply_price"),
                      "ship_cost": s.get("ship_cost"),
                      "title_query": elevenst.query_from_title(s["title"])})
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


# 6. 마진·선별·선별표 -------------------------------------------------------------

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


def _catalog_metrics(conn, no: int) -> dict:
    cat = db.latest_catalog(conn, no)
    if cat is None:
        return {"catalog_similar": None, "catalog_exact": None, "catalog_names": []}
    return {"catalog_similar": cat["similar"], "catalog_exact": cat["exact"],
            "catalog_names": json.loads(cat["names"] or "[]")}


def _price_sets(comp, title: str, min_reverse_overlap: float) -> dict[str, tuple[list[int], dict | None, list[int]]]:
    """경쟁가 출처별 (무료배송 비교 가격, 사유별로 뺀 가격 수, 배송비 별도 표시가). 상품 단위 기록이 없는 이전 수집분은 비교 조건을 모른다(None)."""
    if not comp["items"]:
        return {"동일 상품": (json.loads(comp["same_prices"]), None, []),
                "같은 유형": (json.loads(comp["type_prices"] or "[]"), None, []),
                "키워드 상위 결과": (json.loads(comp["similar_prices"]), None, [])}
    items = json.loads(comp["items"])
    return {"동일 상품": scoring.comparable_prices([i for i in items if i["photo"]], title),
            "같은 유형": scoring.comparable_prices([i for i in items if i["type"]], title, min_reverse_overlap),
            "키워드 상위 결과": scoring.comparable_prices(json.loads(comp["keyword_items"] or "[]"))}


def _evidence_key(conn, no: int, keyword: str, comp, supply: dict, cfg: dict) -> str:
    """검토 입력의 내용 식별값. 공급 재조회 시점만 바뀐 경우에는 동일하다."""
    payload = {
        "version": 2, "keyword": keyword, "competition": dict(comp),
        "supply": supply, "raw": _latest_raw(conn, no), "settings": cfg,
        "support": [dict(r) if r is not None else None for r in (
            db.latest_keyword_stats(conn, keyword), db.latest_trend(conn, keyword),
            db.latest_catalog(conn, no), db.latest_manual_check(conn, no))],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _merged(base: dict, override: dict) -> dict:
    out = json.loads(json.dumps(base))
    for k, v in override.items():
        out[k] = _merged(out.get(k) or {}, v) if isinstance(v, dict) else v
    return out


def build_rows(conn: sqlite3.Connection, cfg: dict | None = None, sensitivity: bool = True) -> list[dict]:
    cfg = cfg or settings()
    fee = cfg["pricing"]["platform_fee_rate"]
    rows = []
    for c in conn.execute("SELECT * FROM candidates WHERE stage IN ('checked', 'verified')"):
        s = db.latest_snapshot(conn, c["no"])
        keyword = json.loads(c["keywords"])[0]
        ks = db.latest_keyword_stats(conn, keyword)
        comp = db.latest_competition(conn, c["no"])
        if comp is None:
            continue
        sets = _price_sets(comp, s["title"], cfg["competition"]["type_reverse_overlap"])
        prices, basis = scoring.competitor_prices(
            sets["동일 상품"][0], sets["키워드 상위 결과"][0],
            cfg["pricing"]["min_matched_for_same_product_price"], sets["같은 유형"][0], cfg["pricing"]["drop_outliers"])
        cal = cfg["naver_calibration"]
        # 최저가 시나리오 하한: 배송비 별도 표시가, 그리고 같은 사진 가격이 부족해 다른 집합을 쓸 때는 같은 사진 가격 전체
        # (같은 사진은 상품명 유사보다 강한 동일 상품 근거라 건수가 적어도 최저가를 부풀리지 않게 쓴다).
        bounds = [scoring.paid_lower_bound(prices, sets[basis][2])]
        if basis != "동일 상품":
            bounds += sets["동일 상품"][0] + sets["동일 상품"][2]
        low_bound = min((b for b in bounds if b), default=None)
        sc = scoring.price_scenarios(prices, s.get("resale_min"), cal["lowest_price"], cal["median_price"], low_bound)
        m_low = scoring.margin(sc["lowest"], s["supply_price"], s["ship_cost"], fee)
        m_mid = scoring.margin(sc["median"], s["supply_price"], s["ship_cost"], fee)
        proposed_low = scoring.margin(sc["proposed_lowest"], s["supply_price"], s["ship_cost"], fee)
        proposed_mid = scoring.margin(sc["proposed_median"], s["supply_price"], s["ship_cost"], fee)
        volume, volume_text = _search_volume(ks)
        total = comp["keyword_total"]
        density = round(total / volume, 2) if total is not None and volume else None
        rows.append({
            "no": c["no"], "stage": c["stage"], "title": s["title"], "keyword": keyword,
            "keywords": json.loads(c["keywords"]),
            "url": c["url"],
            "search_volume": volume, "search_volume_text": volume_text, "comp_idx": ks["comp_idx"] if ks else None,
            "shop_total": total, "competition_density": density,
            "saturation": comp["type_sellers"] if comp["type_sellers"] is not None else comp["same_sellers"],
            "same_photo": comp["same_sellers"], "same_reviews": comp["same_reviews"],
            "naver_same_photo_est": round(comp["same_sellers"] * cfg["naver_calibration"]["same_photo_sellers"]),
            "keyword_fit": comp["keyword_fit"],
            "keyword_names": json.loads(comp["keyword_names"] or "[]"),
            "sat_checked": comp["checked"], "sat_title_total": comp["title_total"], "title_query": comp["title_query"],
            "checked_at": comp["fetched_at"][:10],
            "price_basis": basis, "price_floored": sc["floored"],
            "price_excluded": sets[basis][1],  # None이면 경쟁 상품 단위 기록이 없는 이전 수집분
            "price_dispersion": scoring.dispersion(prices),
            # 같은 사진·같은 유형 가격이 부족하면 선별 대신 확인 대상으로 남긴다. 경쟁이 적은 후보가 소리 없이 빠지지 않게 한다.
            "price_shortage": None if basis != "키워드 상위 결과" else {
                "same_photo_prices": sorted(sets["동일 상품"][0] + sets["동일 상품"][2]),
                "same_type_free": len(sets["같은 유형"][0]), "same_photo_sellers": comp["same_sellers"],
                "type_sellers": comp["type_sellers"]},
            "price_low_bound": low_bound,  # 최저가 시나리오에 쓴 하한(배송비 별도 표시가·같은 사진 가격)
            "price_lowest": sc["lowest"], "price_median": sc["median"],
            "observed_price_lowest": sc["observed_lowest"], "observed_price_median": sc["observed_median"],
            "proposed_price_lowest": sc["proposed_lowest"], "proposed_price_median": sc["proposed_median"],
            "proposed_margin_lowest": proposed_low, "proposed_margin_median": proposed_mid,
            "supply_price": s["supply_price"], "ship_cost": s["ship_cost"], "ship_fee_type": s["ship_fee_type"],
            "resale_min": s.get("resale_min"), "return_fee": s.get("return_fee"),
            "margin_lowest": m_low, "margin_median": m_mid,
            **(opt := _option_costs(conn, c["no"], s["supply_price"])),
            # 판매 옵션이 정해지기 전이라 기본 옵션 마진으로 판정하고, 가장 비싼 판매 가능 옵션의 최저가 마진을 함께 보인다.
            "return_burden": scoring.return_burden(
                s.get("return_fee"), domeggook._flag((_latest_raw(conn, c["no"]).get("return") or {}).get("deliAmtDouble")),
                m_low["gross"]),
            "margin_lowest_max_option": scoring.margin(sc["lowest"], opt["option_supply_max"], s["ship_cost"], fee)
            if opt["option_supply_max"] and opt["option_supply_max"] != s["supply_price"] else None,
            "gross_margin_rate": m_low["gross_rate"],  # 보수적으로 최저가 시나리오 기준
            "image_usable": s.get("image_usable"), "kc_cert": s.get("kc_cert"), "merge_enable": s.get("merge_enable"),
            **_trend_metrics(conn, keyword),
            **_catalog_metrics(conn, c["no"]),
            "price_compare_min": s.get("price_compare_min"), "price_compare_max": s.get("price_compare_max"),
            "sole": s.get("sole"), "popular": s.get("popular"),
            "volatility": volatility(conn, c["no"]),
            "review": json.loads(c["review"]) if c["review"] else None,
            "judgment": dict(j) if (j := db.latest_judgment(conn, c["no"])) else None,
            "decision_revision": j["revision"] if j else 0,
            "evidence_at": _evidence_key(conn, c["no"], keyword, comp, s, cfg),
        })
    rate = {"gross": "gross_rate", "net": "net_rate"}[cfg["selection"]["margin_basis"]]  # net은 수수료율 미설정이면 모름 → 통과 안 함
    for r in rows:
        r["missing"] = [k for k in ("search_volume", "same_photo", "gross_margin_rate", "trend_growth", "competition_density")
                        if r.get(k) is None]
        # 준수가 적용 시나리오로 선별하는 현행 방침은 유지한다. 허용 여부는 사업 미결이다.
        median_margin, lowest_margin = r["proposed_margin_median"][rate], r["proposed_margin_lowest"][rate]
        # 선별 조건. 순위·점수는 쓰지 않는다(2026-10-16 평가에서 점수가 품질을 가르지 못함). 통과 후보는 모두 목록에 둔다.
        r["eligible"] = (median_margin is not None and median_margin >= cfg["selection"]["min_median_margin"]
              and lowest_margin is not None and lowest_margin >= cfg["selection"]["min_lowest_margin"]
              and r["price_basis"] in cfg["selection"]["price_basis"]  # 같은 사진 가격이 아니면 다른 디자인·규격이 섞여 마진을 믿을 수 없다
              and not (r["judgment"] and r["judgment"]["verdict"] == "제외"))  # 사람·검토의 제외 판정은 재계산으로 뒤집지 않는다
        r["selected"] = r["eligible"]
        r["sensitive_to"] = []
        r["review_current"] = bool(r["review"] and r["review"].get("evidence_at") == r["evidence_at"]
                                   and r["review"].get("decision_revision") == r["decision_revision"])
    rows.sort(key=lambda r: (not r["selected"], r["keyword"], r["no"]))  # 순서에 품질 의미가 없다
    if sensitivity:  # 가격 가정을 바꾸면 선별에서 빠지는지. 더 나은 설정을 고르는 시험이 아니라 근거의 견고함 표시다.
        for name, override in cfg["selection"]["sensitivity"].items():
            if name.startswith("_"):
                continue
            kept = {v["no"] for v in build_rows(conn, _merged(cfg, override), sensitivity=False) if v["eligible"]}
            for r in rows:
                if r["selected"] and r["no"] not in kept:
                    r["sensitive_to"].append(name)
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
    cfg_pricing = settings()["pricing"]
    fee_set = cfg_pricing["platform_fee_rate"] is not None
    lines = [
        f"# 후보 선별표 — {date.today().isoformat()}",
        "",
        "- 마진은 추정치다. 점수·순위는 매기지 않는다. 표 순서는 선별 통과 여부·대표 키워드 순이며 판매 우선순위가 아니다.",
        "- 선별 통과(✓): 경쟁가가 같은 사진 상품 가격이고, 준수가 적용 시나리오의 중앙가·최저가 마진이 설정 기준을 충족한 후보 전부. 사람·검토 단계에서 제외로 판정한 후보는 다시 통과시키지 않는다(새 판정으로만 바뀜). 통과는 현행 가격 가정을 충족했다는 뜻이며 손실 회피나 판매 가능성의 보장이 아니다. 판매 가능 조건 확인 대상이다.",
        "- 가격 구분: 관측 비교가(정규화·저가 제거 후, 배송비 별도 표시가 하한 포함) → 네이버 보정 추정가 → 준수가 적용 시나리오. 앞의 두 값은 준수가로 올리지 않는다. 선별에는 현행대로 준수가 적용 시나리오 마진을 사용하며, 그 허용 여부는 미결이다. 시나리오 가격은 시장에서 받을 수 있다는 증거가 아니다.",
        "- 경쟁가 기준: 같은 사진(동일 상품) 가격만 판단 근거다. 같은 유형·키워드 상위 결과 기준 행의 경쟁가·마진은 다른 디자인·규격이 섞인 참고값이며 표에 `참고`로 표시한다.",
        "- 마진 가정: 무료배송으로 판매해 도매 배송비를 판매가에서 부담한다. 마진율 분모는 판매가다. 공급가는 기본 옵션 기준이며, 추가금 있는 옵션은 최고 옵션 기준 마진을 모름·주의 열에 함께 적는다. 경쟁 중앙가는 11번가 배송 표시가 `무료`인 상품끼리 비교하고, 최저가는 조건부무료·착불/선결제 상품의 표시가(배송비 미포함, 결제 총액의 하한)나, 같은 사진 가격이 부족해 다른 집합을 쓸 때의 같은 사진 가격이 더 낮으면 그 값을 쓴다. 상품명에 표기된 수량·치수가 다른 상품과 같은 유형 중 상품명 단어 대부분이 도매 상품명에 없는 상품(다른 종류)을 뺀다. 경쟁가 분산(상위÷하위 4분위)이 크면 혼입 의심으로 표시한다〔제거·표시 기준은 추정 제안값〕. 반품 비용은 반품률을 몰라 마진에 넣지 않고, 반품 1건의 공급처 반품배송비(무료배송 판매 시 2배 조건 반영)가 최저가 기준 몇 건의 마진에 해당하는지 표시한다. 선별 통과 후보는 설정의 가격 가정 대안(저가 제거·같은 사진 최소 건수·네이버 보정)으로 다시 계산해 통과에서 빠지면 그 가정을 표시한다.",
        "- 네이버 보정〔추정치〕: 네이버 캡처 표본에서 네이버 가격이 11번가보다 낮아, 경쟁 최저가 ×0.76, 중앙가 ×0.91로 계산한다. 네이버 예상 같은 사진 판매자 수는 11번가 ×1.8(표시용).",
        "- 수수료 반영 마진: " + ("설정된 수수료율 적용." if fee_set else "수수료율 미확인이라 모름. 표의 마진은 수수료 차감 전이다.")
        + (" 선별은 수수료 차감 후 마진을 쓴다." if settings()["selection"]["margin_basis"] == "net"
           else " 선별은 수수료 차감 전 마진을 쓴다(수수료 후 판정은 미결정)."),
        "- 포화도·상품 수·경쟁가: 11번가 상품검색 기준(수집일 표기). 같은 유형 판매자 수는 도매 상품명 검색 상위 100개 중 상품명이 비슷한 판매자 수(사진이 달라도 포함), 같은 사진은 도매 이미지를 그대로 쓴 판매자 수다. 네이버 표본 4건에서 같은 사진만 세면 경쟁을 크게 놓쳤다. 상위 100개 밖은 세지 않는다.",
        "- 네이버 카탈로그(유형/일치): 커머스API로 도매 상품명 검색어를 조회해, 검색어 단어의 60% 이상을 담은 카탈로그 수와 도매 상품명 전체 단어의 75% 이상을 담은 카탈로그 수. 많을수록 네이버에 같은 유형 가격비교 모델이 많다는 뜻이다. 상품명 일치 카탈로그는 후보의 약 70%에서 나와 후보를 가려내지 못한다(위탁 상품 다수가 이미 네이버 카탈로그에 있다는 신호). 선별 조건에 넣지 않는 참고 지표다.",
        "- 진입 장벽(상위 판매자의 리뷰 규모)은 모름: 네이버 표본에서는 결정적이었지만 11번가 리뷰는 거의 0이라 대신할 수 없다.",
        "- 대표 키워드가 상품과 맞는지는 7단계 검토 때 Claude가 11번가 키워드 검색 상위 상품명을 보고 판단한다(자동 적합도 값은 변별력이 낮아 CSV에만 남긴다).",
        "- 같은 상품 리뷰 수: 11번가에서 같은 사진을 쓴 상품들의 리뷰 합계. 판매 흔적이며 판매량이 아니다.",
        "- 검색 추세: 네이버 검색어 트렌드 기준 최근 3개월 ÷ 그 전 3개월(증감), 직전 달 ÷ 12개월 평균(계절). 상대값 비율이며 검색량이 아니다. 블로그 글 수·작성 속도는 참고용이고 점수에 넣지 않는다.",
        "",
        "| 선별 통과 | 상품 | 키워드 | 월 검색수 | 검색 추세(증감/계절) | 11번가 상품 수 | 경쟁 밀도 | 같은 유형 판매자(같은 사진) | 네이버 카탈로그(유형/일치) | 경쟁가 기준 | 관측 비교가 최저/중앙 | 보정 최저가 / 마진 | 보정 중앙가 / 마진 | 준수가 적용 최저/중앙 / 선별 마진 | 도매가+배송 | 모름·주의 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        notes = [f"지표 없음: {', '.join(r['missing'])}"] if r["missing"] else []
        if r["image_usable"] is False:
            notes.append("이미지 사용 불허")
        if r["price_floored"]:
            notes.append(f"준수가 {r['resale_min']:,}원으로 시나리오 상향 — 보정 경쟁가와 차이, 가격 수용성 미확인")
        if r["ship_cost"] is None:
            notes.append(f"배송비 모름({r['ship_fee_type']})")
        if r["price_excluded"] is None:
            notes.append("경쟁가 비교 조건 미확인(재수집 필요)")
        elif any(r["price_excluded"].values()):
            notes.append("경쟁가 제외 " + ", ".join(f"{k} {v}" for k, v in r["price_excluded"].items() if v))
        if r["price_dispersion"] and r["price_dispersion"] > cfg_pricing["dispersion_warn"]:
            notes.append(f"경쟁가 분산 {r['price_dispersion']}배 — 다른 상품 혼입 의심")
        if r["sat_title_total"] and r["sat_title_total"] > r["sat_checked"]:
            notes.append(f"상품명 검색 {r['sat_title_total']:,}건 중 {r['sat_checked']}건만 비교")
        if r["margin_lowest_max_option"]:
            notes.append(f"옵션 추가금 있음: 최고 옵션 공급가 {r['option_supply_max']:,} 기준 최저가 마진 "
                         f"{_fmt(r['margin_lowest_max_option']['gross_rate'], True)}")
        rb = r["return_burden"]
        if rb["cost"] is None:
            notes.append("반품비 모름")
        elif rb["sales_to_cover"] is not None:
            notes.append(f"반품 1건 {rb['cost']:,}원 = 최저가 기준 판매 {rb['sales_to_cover']}건 마진")
        if r["sensitive_to"]:
            notes.append("가정 바꾸면 목록 탈락: " + ", ".join(r["sensitive_to"]))
        if r["selected"] and not r["review_current"]:
            notes.append("7단계 검토 전(판매 조건 확인 불가)")
        if r["judgment"]:
            j = r["judgment"]
            notes.append(f"판정 {j['verdict']}({j['judged_at'][:10]}, {j['source']}): {j['reason']}")
        v = r["volatility"]
        notes.append(f"변동 {v['changes']}회/{v['days']}일")
        ml, mm = r["margin_lowest"], r["margin_median"]
        lines.append(" | ".join([
            "| ✓" if r["selected"] else "| ", f"[{r['title']}]({r['url']})",
            r["keyword"], r["search_volume_text"],
            f"{_fmt(r['trend_growth'])} / {_fmt(r['season_index'])}", _fmt(r["shop_total"]),
            _fmt(r["competition_density"]), f"{_fmt(r['saturation'])} ({_fmt(r['same_photo'])}, 네이버 예상 {_fmt(r['naver_same_photo_est'])})",
            f"{_fmt(r['catalog_similar'])} / {_fmt(r['catalog_exact'])}",
            r["price_basis"] + ("" if r["price_basis"] == "동일 상품" else " (참고)"),
            f"{_fmt(r['observed_price_lowest'])} / {_fmt(r['observed_price_median'])}",
            f"{_fmt(r['price_lowest'])} / {_fmt(ml['gross_rate'], True)}",
            f"{_fmt(r['price_median'])} / {_fmt(mm['gross_rate'], True)}",
            f"{_fmt(r['proposed_price_lowest'])} / {_fmt(r['proposed_price_median'])} · "
            f"{_fmt(r['proposed_margin_lowest'][settings()['selection']['margin_basis'] + '_rate'], True)} / "
            f"{_fmt(r['proposed_margin_median'][settings()['selection']['margin_basis'] + '_rate'], True)}",
            f"{_fmt(r['supply_price'])}+{_fmt(r['ship_cost'])}", "; ".join(notes) + " |",
        ]))
    short = [r for r in rows if r["price_shortage"] and not (r["judgment"] and r["judgment"]["verdict"] == "제외")]
    if short:
        lines += ["", "## 비교 가격 부족 — 확인 대상", "",
                  f"같은 사진·같은 유형의 무료배송 가격이 {settings()['pricing']['min_matched_for_same_product_price']}개 미만이라 "
                  "마진을 계산할 수 없어 선별을 통과시키지 않은 후보다. 경쟁이 적어서일 수도, 수집 범위 밖일 수도 있다. "
                  "같은 사진 가격(배송 조건 무관)과 판매자 수를 참고해 네이버 표본·공급 조건으로 확인한다. 판매 가능성 판정이 아니다.", "",
                  "| 상품 | 키워드 | 월 검색수 | 같은 사진 판매자 / 가격 | 같은 유형 판매자 / 무료배송 가격 수 | 도매가+배송 |",
                  "| --- | --- | --- | --- | --- | --- |"]
        for r in short:
            ps = r["price_shortage"]
            lines.append(f"| [{r['title']}]({r['url']}) | {r['keyword']} | {r['search_volume_text']} | "
                         f"{_fmt(ps['same_photo_sellers'])} / {', '.join(f'{p:,}' for p in ps['same_photo_prices']) or '없음'} | "
                         f"{_fmt(ps['type_sellers'])} / {ps['same_type_free']} | {_fmt(r['supply_price'])}+{_fmt(r['ship_cost'])} |")
    reviewed = [r for r in rows if r["review"]]
    if reviewed:
        lines += ["", "## 7단계 검토", ""]
        for r in reviewed:
            rv = r["review"]
            state = "" if r["review_current"] else " — 이전 근거의 검토(검토 입력 변경 후 재검토 필요)"
            lines += [f"### {r['title']}", "", f"- 판정: {rv.get('verdict') or '없음'}{state}",
                      f"- 근거: {rv.get('rationale', '')}",
                      f"- 리스크: {rv.get('risks', '')}", f"- 모름: {rv.get('unknowns', '')}", ""]
    md_path = f"{stem}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    csv_path = f"{stem}.csv"
    flat_keys = ["no", "selected", "title", "keyword", "search_volume_text", "comp_idx", "shop_total", "competition_density",
                 "saturation", "same_photo", "naver_same_photo_est", "catalog_similar", "catalog_exact", "same_reviews", "keyword_fit", "sat_checked", "sat_title_total", "title_query", "checked_at", "price_basis", "price_dispersion", "price_low_bound", "price_lowest", "price_median",
                 "observed_price_lowest", "observed_price_median", "proposed_price_lowest", "proposed_price_median", "price_floored", "resale_min", "supply_price", "option_count", "option_supply_max", "ship_cost", "return_fee", "image_usable", "kc_cert",
                 "merge_enable", "sensitive_to", "trend_growth", "season_index", "shop_growth", "shop_months", "blog_total", "blog_rate",
                 "cafe_total", "price_compare_min", "price_compare_max", "sole", "popular", "url"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(flat_keys + ["gross_rate_lowest", "gross_rate_median", "net_rate_lowest", "net_rate_median", "proposed_gross_rate_lowest", "proposed_gross_rate_median", "proposed_net_rate_lowest", "proposed_net_rate_median"])
        for r in rows:
            w.writerow([r[k] for k in flat_keys] + [r["margin_lowest"]["gross_rate"], r["margin_median"]["gross_rate"],
                                                    r["margin_lowest"]["net_rate"], r["margin_median"]["net_rate"],
                                                    r["proposed_margin_lowest"]["gross_rate"], r["proposed_margin_median"]["gross_rate"],
                                                    r["proposed_margin_lowest"]["net_rate"], r["proposed_margin_median"]["net_rate"]])
    return md_path, csv_path, len(rows)


# 7. 선별 통과 후보 검토 — Claude가 근거·리스크·모름 작성 --------------------------------------

REVIEW_FIELDS = ("verdict", "rationale", "risks", "unknowns")


def _latest_raw(conn, no: int) -> dict:
    row = conn.execute("SELECT raw FROM supply_snapshots WHERE no=? ORDER BY fetched_at DESC, rowid DESC LIMIT 1", (no,)).fetchone()
    return json.loads(row["raw"]) if row else {}


def _option_costs(conn, no: int, supply_price: int | None) -> dict:
    """도매매에서 팔 수 있는 옵션(숨김·도매매 불가 제외, 재고 0 제외)의 공급가 범위. 옵션 해석은 verify.parse_options의 추정을 따른다."""
    opts = [o for o in verify.parse_options(_latest_raw(conn, no), supply_price)
            if o["sellable"] and (o["qty"] is None or o["qty"] > 0)]
    prices = [o["price"] for o in opts if o["price"] is not None]
    return {"option_count": len(opts), "option_supply_max": max(prices) if prices else None}


def _info_duty(conn, no: int) -> dict:
    """최신 도매 상세의 상품정보고시 항목(품명·소재·크기·구성 등). 상품명과 실제 규격·소재의 충돌을 검토하는 데 쓴다."""
    raw = _latest_raw(conn, no)
    items = domeggook.as_list(((raw.get("detail") or {}).get("infoDuty") or {}).get("item"))
    return {i.get("name"): i.get("desc") for i in items if i.get("type") == "item" and (i.get("desc") or "").strip()}


def export_review(conn: sqlite3.Connection, top: int | None = None) -> tuple[str, int]:
    """현재 근거로 검토되지 않은 선별 통과 후보를 내보낸다. 비교에 쓴 경쟁 상품명·가격과 상품정보고시를 함께 넣는다."""
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    path = LLM_DIR / "review_pending.jsonl"
    rows = [r for r in build_rows(conn) if r["selected"] and not r["review_current"]][:top]
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            comp = db.latest_competition(conn, r["no"])
            items = json.loads(comp["items"] or "[]")
            key = {"동일 상품": "photo", "같은 유형": "type"}.get(r["price_basis"])
            compared = [{k: i.get(k) for k in ("name", "price", "delivery")} for i in items if key and i.get(key)]
            f.write(json.dumps({k: v for k, v in r.items() if k != "review"}
                               | {"info_duty": _info_duty(conn, r["no"]), "compared_items": compared[:40]},
                               ensure_ascii=False) + "\n")
    return str(path), len(rows)


def import_review(conn: sqlite3.Connection, path) -> int:
    """내보낸 근거 식별값과 현재 입력이 일치하는 검토만 원자적으로 저장한다."""
    current = {r["no"]: r for r in build_rows(conn)}
    with open(path, encoding="utf-8") as f:
        entries = [json.loads(line) for line in f if line.strip()]
    seen = set()
    for r in entries:
        no = r["no"]
        if no in seen:
            raise ValueError(f"{no}: 검토 중복")
        seen.add(no)
        if r.get("verdict") not in db.VERDICTS:
            raise ValueError(f"{no}: verdict는 {', '.join(db.VERDICTS)} 중 하나")
        if no not in current:
            raise ValueError(f"{no}: 비교표에 없는 후보")
        if r.get("evidence_at") != current[no]["evidence_at"]:
            raise ValueError(f"{no}: 검토 근거 누락·변경. review-export 후 다시 검토한다")
        if r.get("decision_revision") != current[no]["decision_revision"]:
            raise ValueError(f"{no}: 검토 이후 판정 변경·식별값 누락. 현재 판정을 확인하고 다시 검토한다")
        if not (r.get("rationale") or "").strip():
            raise ValueError(f"{no}: 판정 근거가 필요")
    with conn:
        for r in entries:
            db.add_judgment(conn, r["no"], r["verdict"], r["rationale"], "7단계 검토")
            review = {k: r.get(k) for k in REVIEW_FIELDS} | {
                "evidence_at": r["evidence_at"], "reviewed_at": db.now(),
                "decision_revision": db.latest_judgment(conn, r["no"])["revision"]}
            conn.execute("UPDATE candidates SET review=? WHERE no=?", (json.dumps(review, ensure_ascii=False), r["no"]))
    return len(entries)


# 8. 판매 가능 조건 확인 — 선별 통과 후보를 등록 가능한지 확인하고, 안 되면 선정 단계로 돌려보낸다 -------------

def _check_handoff(rows: dict, nos: list[int], evidence: dict | None = None) -> None:
    blocked = []
    for no in nos:
        row = rows.get(no)
        if row is None or not row["selected"]:
            blocked.append(f"{no}(현재 선별 미통과)")
        elif not row["review_current"]:
            blocked.append(f"{no}(검토 없음·이전 근거)")
        elif evidence is not None and evidence.get(str(no)) != row["evidence_at"]:
            blocked.append(f"{no}(확인 화면 이후 근거 변경)")
    if blocked:
        raise ValueError("인계 중단: " + ", ".join(blocked) + ". report·review-export로 현재 근거를 확인한다")


def _refresh_handoff_supply(conn, nos: list[int]) -> dict:
    # 일부 조회 실패 시 화면/조건서는 만들지 않는다. 성공한 전체 조회만 함께 저장한다.
    views = {no: domeggook.item_view(no) for no in nos}
    with conn:
        for no, view in views.items():
            summary = domeggook.summarize(view)
            if summary["no"] != no:
                raise ValueError(f"{no}: 공급처 응답 상품번호 불일치")
            conn.execute("INSERT INTO supply_snapshots VALUES (?,?,?,?)", (
                no, db.now(), json.dumps(summary, ensure_ascii=False), json.dumps(view, ensure_ascii=False)))
    return views


def export_verify(conn: sqlite3.Connection, top: int | None = None, nos: list[int] | None = None) -> tuple[str, int]:
    rules = settings()["verification"]
    rows = {r["no"]: r for r in build_rows(conn)}
    if nos is None:
        nos = [no for no, r in rows.items() if r["stage"] == "checked" and r["selected"] and r["review_current"]
               ][:rules["top"] if top is None else top]
    nos = list(dict.fromkeys(nos))
    if not nos:
        return "", 0
    _check_handoff(rows, nos)
    views = _refresh_handoff_supply(conn, nos)
    rows = {r["no"]: r for r in build_rows(conn)}
    _check_handoff(rows, nos)
    items = [verify.collect(views[no]) for no in nos]
    urls = {no: rows[no]["url"] for no in nos}
    batch_id = uuid.uuid4().hex
    pending = {"batch_id": batch_id, "conditions": items,
               "evidence": {str(no): rows[no]["evidence_at"] for no in nos}}
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    (VERIFY_DIR / f"pending-{batch_id}.json").write_text(json.dumps(pending, ensure_ascii=False), encoding="utf-8")
    path = VERIFY_DIR / f"verify-{batch_id}.html"
    path.write_text(verify.render(items, urls, rules, batch_id), encoding="utf-8")
    return str(path), len(items)


def import_verify(conn: sqlite3.Connection, path) -> dict:
    rules = settings()["verification"]
    entered = verify.read_csv(path)
    batch_ids = {r.get("batch_id") for r in entered.values()}
    if len(batch_ids) != 1:
        raise ValueError("확인 화면 식별값 누락·혼합. verify-export로 화면을 다시 만든다")
    batch_id = next(iter(batch_ids))
    if not isinstance(batch_id, str) or len(batch_id) != 32 or any(c not in "0123456789abcdef" for c in batch_id):
        raise ValueError("확인 화면 식별값 누락·오류. verify-export로 화면을 다시 만든다")
    pending = json.loads((VERIFY_DIR / f"pending-{batch_id}.json").read_text(encoding="utf-8"))
    if pending.get("batch_id") != batch_id:
        raise ValueError("확인 화면 식별값 불일치")
    conditions = {c["no"]: c for c in pending["conditions"]}
    if set(conditions) != set(entered):
        raise ValueError("확인 화면과 CSV 상품 목록 불일치")
    nos = list(conditions)
    _check_handoff({r["no"]: r for r in build_rows(conn)}, nos, pending["evidence"])
    views = _refresh_handoff_supply(conn, nos)
    _check_handoff({r["no"]: r for r in build_rows(conn)}, nos, pending["evidence"])
    # 날짜에 따라 달라지는 판매 종료일 등은 현재 기준으로 다시 평가한다.
    conditions = {no: verify.collect(views[no]) for no in nos}
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
    out = REPORT_DIR / f"{date.today().isoformat()}-{batch_id}-sell-conditions.md"
    out.write_text("\n".join([
        f"# 판매 조건서 — {date.today().isoformat()}", "",
        "발행 시점의 선별·검토 근거와 판매 가능 조건을 확인한 상품. 게시 승인과 별개이며 공급 조건 변경 시 재확인이 필요하다.", "",
        f"- 확인 실행: `{batch_id}` · 확인 시각: {db.now()}", "",
        *sheets,
        "## 선정 단계로 돌려보낸 상품", "", *(returned or ["- 없음"]), "",
    ]), encoding="utf-8")
    counts["sheet"] = str(out)
    return counts

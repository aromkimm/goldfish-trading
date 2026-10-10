"""처리 흐름 단계. 단계 정의는 docs/product-selection-agent.md의 처리 흐름을 따른다."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import date

from . import db, filters, manual, scoring, verify
from .config import DATA_DIR, settings
from .sources import domeggook, naver

LLM_DIR = DATA_DIR / "llm"
MANUAL_DIR = DATA_DIR / "manual"
VERIFY_DIR = DATA_DIR / "verify"
REPORT_DIR = DATA_DIR / "reports"


# 1. 후보 생성 ---------------------------------------------------------------

def search_supply(conn: sqlite3.Connection, *, kw=None, ca=None, pages=1, sort=None) -> int:
    added = 0
    query = json.dumps({"kw": kw, "ca": ca, "sort": sort}, ensure_ascii=False)
    for page in range(1, pages + 1):
        header, items = domeggook.item_list(kw=kw, ca=ca, page=page, sort=sort)
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


# 5. 네이버쇼핑 수동 확인 ------------------------------------------------------------------

def export_manual(conn: sqlite3.Connection, shortlist: int | None = None) -> tuple[str, int]:
    """검색량 순으로 상위 후보를 골라 확인 화면을 만든다〔선별 기준은 제안값〕."""
    shortlist = shortlist or settings()["manual_check"]["shortlist"]
    items = []
    for c in conn.execute("SELECT * FROM candidates WHERE stage='measured'"):
        keyword = json.loads(c["keywords"])[0]
        volume, _ = _search_volume(db.latest_keyword_stats(conn, keyword))
        s = db.latest_snapshot(conn, c["no"])
        items.append({"no": c["no"], "title": s["title"], "thumb": s.get("thumb"), "url": c["url"],
                      "keyword": keyword, "supply_price": s.get("supply_price"), "_volume": volume})
    items.sort(key=lambda i: (i["_volume"] is None, -(i["_volume"] or 0)))
    items = items[:shortlist]
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
        conn.execute("UPDATE candidates SET stage='checked' WHERE no=? AND stage='measured'", (r["no"],))
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
        mc = db.latest_manual_check(conn, c["no"])
        prices, basis = scoring.competitor_prices(
            json.loads(mc["same_prices"]), json.loads(mc["similar_prices"]),
            cfg["pricing"]["min_matched_for_same_product_price"])
        sc = scoring.price_scenarios(prices, s.get("resale_min"))
        m_low = scoring.margin(sc["lowest"], s["supply_price"], s["ship_cost"], fee)
        m_mid = scoring.margin(sc["median"], s["supply_price"], s["ship_cost"], fee)
        volume, volume_text = _search_volume(ks)
        total = mc["total_results"]
        density = round(total / volume, 2) if total is not None and volume else None
        rows.append({
            "no": c["no"], "stage": c["stage"], "title": s["title"], "keyword": keyword,
            "keywords": json.loads(c["keywords"]),
            "url": c["url"],
            "search_volume": volume, "search_volume_text": volume_text, "comp_idx": ks["comp_idx"] if ks else None,
            "shop_total": total, "competition_density": density,
            "saturation": mc["same_sellers"], "manual_note": mc["note"], "checked_at": mc["checked_at"][:10],
            "price_basis": basis, "price_floored": sc["floored"],
            "price_lowest": sc["lowest"], "price_median": sc["median"],
            "supply_price": s["supply_price"], "ship_cost": s["ship_cost"], "ship_fee_type": s["ship_fee_type"],
            "resale_min": s.get("resale_min"), "return_fee": s.get("return_fee"),
            "margin_lowest": m_low, "margin_median": m_mid,
            "gross_margin_rate": m_low["gross_rate"],  # 점수는 보수적으로 최저가 시나리오 기준
            "image_usable": s.get("image_usable"), "kc_cert": s.get("kc_cert"), "merge_enable": s.get("merge_enable"),
            "price_compare_min": s.get("price_compare_min"), "price_compare_max": s.get("price_compare_max"),
            "sole": s.get("sole"), "popular": s.get("popular"),
            "volatility": volatility(conn, c["no"]),
            "review": json.loads(c["review"]) if c["review"] else None,
        })
    scores = scoring.score({r["no"]: r for r in rows}, cfg["scoring"]["weights"])
    for r in rows:
        r.update(scores[r["no"]])
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0)))
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
        "- 점수·마진은 추정치다. 점수는 이번 배치 안의 상대 순위이며 판매량 예측이 아니다(가중치 미확정 제안값).",
        "- 마진 가정: 무료배송으로 판매해 도매 배송비를 판매가에서 부담한다. 마진율 분모는 판매가다.",
        "- 수수료 반영 마진: " + ("설정된 수수료율 적용." if fee_set else "수수료율 미확인이라 모름. 표의 마진은 수수료 차감 전이다."),
        "- 포화도·전체 상품 수·경쟁가: 네이버쇼핑 수동 확인값(확인일 표기). 같은 상품 판매자 수는 사람이 눈으로 센 값이다.",
        "- 도매꾹 신호(타 사이트 가격·단독판매·인기상품)는 자동 대체 가능성 검증용으로 CSV에만 남긴다.",
        "",
        "| 순위 | 상품 | 키워드 | 월 검색수 | 상품 수 | 경쟁 밀도 | 같은 상품 판매자 | 경쟁가 기준 | 최저가 / 마진 | 중앙가 / 마진 | 도매가+배송 | 점수 | 모름·주의 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(rows, 1):
        notes = [f"지표 없음: {', '.join(r['missing'])}"] if r["missing"] else []
        if r["image_usable"] is False:
            notes.append("이미지 사용 불허")
        if r["price_floored"]:
            notes.append(f"최저판매준수가 {r['resale_min']:,} 적용")
        if r["ship_cost"] is None:
            notes.append(f"배송비 모름({r['ship_fee_type']})")
        if r["manual_note"]:
            notes.append(f"메모: {r['manual_note']}")
        v = r["volatility"]
        notes.append(f"변동 {v['changes']}회/{v['days']}일")
        ml, mm = r["margin_lowest"], r["margin_median"]
        lines.append(" | ".join([
            f"| {i}", f"[{r['title']}]({r['url']})", r["keyword"], r["search_volume_text"], _fmt(r["shop_total"]),
            _fmt(r["competition_density"]), f"{_fmt(r['saturation'])} ({r['checked_at']})",
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
    flat_keys = ["no", "title", "keyword", "search_volume_text", "comp_idx", "shop_total", "competition_density",
                 "saturation", "checked_at", "price_basis", "price_lowest", "price_median",
                 "resale_min", "supply_price", "ship_cost", "return_fee", "image_usable", "kc_cert",
                 "merge_enable", "price_compare_min", "price_compare_max", "sole", "popular", "score", "url"]
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
    rows = build_rows(conn)[:top]
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
        nos = [r["no"] for r in build_rows(conn) if r["stage"] == "checked"][:top or rules["top"]]
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

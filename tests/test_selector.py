"""외부 API 없이 도는 테스트. 실행: .venv/bin/python -m unittest discover tests"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from selector import db, filters, manual, pipeline, saturation, scoring, trend, verify
from selector.config import settings
from selector.sources import domeggook, elevenst, naver, naver_hub


def png(seed: int, shift: int = 0) -> bytes:
    """seed마다 다른 무늬, shift는 같은 무늬의 약한 변형."""
    img = Image.new("RGB", (120, 120), "white")
    draw = ImageDraw.Draw(img)
    for i in range(6):
        x = (seed * 37 + i * 53) % 100
        y = (seed * 91 + i * 29) % 100
        draw.rectangle([x, y, x + 20 + shift, y + 15], fill=(seed * 40 % 255, i * 40, 120))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


ELEVENST_XML = """<?xml version="1.0" encoding="EUC-KR"?><ProductSearchResponse><Products><TotalCount>1,234</TotalCount>
<Product><ProductCode>1</ProductCode><ProductName><![CDATA[걸이 A]]></ProductName><ProductImage200><![CDATA[u1]]></ProductImage200>
<Seller>a</Seller><ProductPrice>10000</ProductPrice><SalePrice>9000</SalePrice><Delivery><![CDATA[무료]]></Delivery><ReviewCount>12</ReviewCount></Product>
<Product><ProductCode>2</ProductCode><ProductName><![CDATA[걸이 B]]></ProductName><ProductImage200><![CDATA[u2]]></ProductImage200>
<Seller>b</Seller><ProductPrice>9900</ProductPrice><SalePrice></SalePrice><ReviewCount>0</ReviewCount></Product>
</Products></ProductSearchResponse>""".encode("euc-kr")


VIEW = {"domeggook": {
    "basis": {"no": 101, "status": "판매중", "title": "스테인리스 다용도 걸이 5개입", "adult": "false"},
    "price": {"supply": "1+3000|10+2800", "resale": {"minumum": 7000, "Recommand": 9900}},
    "qty": {"inventory": 500},
    "deli": {"pay": "선결제", "dome": {"type": "고정배송비", "fee": 3000}, "wating": "즉시배송가능",
             "periodDeli": "0", "sendAvg": "0.4", "feeExtra": {"jeju": "3000", "islands": "5000"},
             "supply": {"pay": "선결제", "type": "고정배송비", "fee": 2500},
             "merge": {"enable": "y"}, "fromOversea": "false"},
    "desc": {"license": {"usable": "true"}},
    "detail": {"safetyCert": {"cert": "N"}},
    "category": {"parents": {"elem": [{"name": "생활용품"}, {"name": "욕실용품"}]}, "current": {"name": "수납걸이"}},
    "return": {"deliAmt": 3000, "deliAmtDouble": "true",
               "addr": {"zipcode": "14322", "address1": "경기 광명시", "address2": "548호"}},
    "priceCompare": {"sole": "false", "min": 8900, "max": 12000},
    "thumb": {"large": "https://img/supplier.png"},
    "seller": {"id": "s1"},
    "etc": {"denyMarket": "false"},
    "selectOpt": json.dumps({"data": {
        "00": {"name": "흰색", "sup": "1", "supPrice": "0", "qty": "10", "hid": "0"},
        "01": {"name": "검정", "sup": "1", "supPrice": "500", "qty": "0", "hid": "0"},
        "02": {"name": "숨김", "sup": "1", "supPrice": "0", "qty": "5", "hid": "1"}}}),
}}


class SourceParsing(unittest.TestCase):
    def test_tiered_price(self):
        self.assertEqual(domeggook.tiered_price("1+3800|20+3500|50+3300"), 3800)
        self.assertEqual(domeggook.tiered_price("1+3800|20+3500|50+3300", qty=20), 3500)
        self.assertEqual(domeggook.tiered_price(4200), 4200)
        self.assertIsNone(domeggook.tiered_price(None))

    def test_summarize(self):
        s = domeggook.summarize(domeggook.unwrap(VIEW))
        self.assertEqual(s["supply_price"], 3000)
        self.assertEqual(s["ship_cost"], 2500)  # 도매매 배송비가 도매꾹 배송비보다 우선
        self.assertEqual(s["resale_min"], 7000)
        self.assertIs(s["adult"], False)        # 문자열 "false"를 참으로 읽지 않는다
        self.assertIs(s["image_usable"], True)
        self.assertEqual(s["category_path"], ["생활용품", "욕실용품", "수납걸이"])

    def test_ship_cost_rules(self):
        self.assertEqual(domeggook.ship_cost("선결제", "수량별비례", None, "10+3000|10+3000"), 3000)
        self.assertEqual(domeggook.ship_cost("선결제", "수량별비례", None, "50+2500|100+2000", qty=151), 2500 + 2 * 2000)
        self.assertEqual(domeggook.ship_cost("선결제", "수량별차등", None, "1+2500|20+2350"), 2500)
        self.assertEqual(domeggook.ship_cost("무료배송", None, None, None), 0)
        self.assertIsNone(domeggook.ship_cost("선결제", "금액비노출", None, None))
        self.assertIsNone(domeggook.ship_cost("착불", "고정배송비", "3000", None))

    def test_real_response_shape(self):
        """2026-10-10 실호출 응답 형태: 문자열 숫자, 수량별비례 배송비, 도매매 배송 pay 없음."""
        view = json.loads(json.dumps(VIEW))["domeggook"]
        view["deli"] = {"pay": "선결제", "dome": {"type": "수량별비례", "tbl": "10+3000|10+3000"},
                        "supply": {"type": "수량별비례", "tbl": "10+3000|10+3000"}, "merge": {"enable": "y"}}
        view["qty"]["inventory"] = "1000"
        s = domeggook.summarize(view)
        self.assertEqual((s["ship_cost"], s["inventory"], s["ship_pay"]), (3000, 1000, "선결제"))

    def test_parse_count(self):
        self.assertEqual(naver.parse_count("<10"), naver.LESS_THAN_10)
        self.assertEqual(naver.parse_count(1234), 1234)
        self.assertIsNone(naver.parse_count(None))

    def test_signature_matches_official_sample_format(self):
        import base64, hashlib, hmac
        expected = base64.b64encode(hmac.new(b"sk", b"1.GET./keywordstool", hashlib.sha256).digest()).decode()
        self.assertEqual(naver._signature("1", "GET", "/keywordstool", "sk"), expected)


class Filters(unittest.TestCase):
    cfg = settings()["exclusion"]

    def summary(self, **kw):
        base = domeggook.summarize(domeggook.unwrap(VIEW))
        base.update(kw)
        return base

    def test_pass(self):
        self.assertIsNone(filters.rule_exclusion(self.summary(), self.cfg))

    def test_category_and_title_rules(self):
        self.assertIn("반품", filters.rule_exclusion(self.summary(category_path=["패션의류", "여성의류"]), self.cfg))
        self.assertIn("라이선스", filters.rule_exclusion(self.summary(title="산리오 쿠로미 파우치"), self.cfg))
        self.assertIn("일회용", filters.rule_exclusion(self.summary(title="일회용 종이컵 100개"), self.cfg))

    def test_status_and_flags(self):
        self.assertIn("판매상태", filters.rule_exclusion(self.summary(status="판매종료"), self.cfg))
        self.assertEqual(filters.rule_exclusion(self.summary(from_oversea=True), self.cfg), "해외직배송")


class Elevenst(unittest.TestCase):
    def test_parse(self):
        total, items = elevenst.parse(ELEVENST_XML)
        self.assertEqual(total, 1234)
        self.assertEqual([(i["name"], i["price"], i["seller"], i["reviews"]) for i in items],
                         [("걸이 A", 9000, "a", 12), ("걸이 B", 9900, "b", 0)])

    def test_error_response(self):
        err = '<?xml version="1.0" encoding="EUC-KR"?><ErrorResponse><ErrorCode>003</ErrorCode><ErrorMessage>x</ErrorMessage></ErrorResponse>'
        with self.assertRaises(RuntimeError):
            elevenst.parse(err.encode("euc-kr"))

    def test_query_from_title(self):
        self.assertEqual(elevenst.query_from_title("[도매라인] 세련된디자인 두꺼운 겨울 극세사담요 100*80 겨울이불담요 겨울담요"),
                         "세련된디자인 두꺼운 겨울 극세사담요 겨울이불담요")


class Saturation(unittest.TestCase):
    def test_counts_same_image_sellers_prices_reviews(self):
        images = {"same1": png(1), "same2": png(1, shift=1), "other": png(5), "broken": b"not an image"}
        items = [
            {"image": "same1", "seller": "A", "price": 9000, "reviews": 3},
            {"image": "same2", "seller": "B", "price": 9500, "reviews": 0},
            {"image": "same1", "seller": "A", "price": 9100, "reviews": 1},
            {"image": "other", "seller": "C", "price": 5000, "reviews": 50},
            {"image": "broken", "seller": "D", "price": 1, "reviews": 0},
        ]
        r = saturation.match(png(1), items, max_distance=10, fetch=images.__getitem__)
        self.assertEqual((r["matched"], r["sellers"], r["image_failed"], r["reviews"]), (3, 2, 1, 4))
        self.assertEqual(r["prices"], [9000, 9100, 9500])


class SameType(unittest.TestCase):
    def test_word_overlap_ignores_spacing(self):
        self.assertEqual(saturation.word_overlap("차량용 트렁크 정리함", "자동차 트렁크정리함 접이식"), 2 / 3)
        self.assertEqual(saturation.word_overlap("", "x"), 0.0)

    def test_same_type_counts_different_photos(self):
        items = [{"name": "차량용 트렁크 정리함 접이식", "seller": "a", "price": 20000},
                 {"name": "차량용트렁크정리함", "seller": "b", "price": 18000},
                 {"name": "캠핑 의자", "seller": "c", "price": 30000}]
        r = saturation.same_type("차량용 트렁크 정리함", items, 0.8)
        self.assertEqual((r["sellers"], r["prices"]), (2, [18000, 20000]))

    def test_price_basis_prefers_same_type_over_keyword(self):
        prices, basis = scoring.competitor_prices([], [100000, 120000], 3, [17000, 22000, 28000])
        self.assertEqual((prices, basis), ([17000, 22000, 28000], "같은 유형"))


class ManualCheck(unittest.TestCase):
    def test_parse_prices_mixed_input(self):
        self.assertEqual(manual.parse_prices("12,900 13500원 / 9,900"), [12900, 13500, 9900])
        self.assertEqual(manual.parse_prices(""), [])
        self.assertEqual(manual.parse_int("1,234개"), 1234)

    def test_render_escapes_and_links(self):
        page = manual.render([{"no": 1, "title": "<b>걸이</b>", "thumb": "t", "url": "u",
                               "keyword": "욕실 걸이", "supply_price": 3000}], "2026-10-10")
        self.assertIn("&lt;b&gt;걸이", page)
        self.assertIn("query=%EC%9A%95%EC%8B%A4+%EA%B1%B8%EC%9D%B4", page)

    def test_read_csv_skips_unfilled(self):
        path = Path(tempfile.mkdtemp()) / "m.csv"
        path.write_text("\ufeffno,total_results,same_sellers,same_prices,similar_prices,note\n"
                        '1,"12,345",4,"9900 10500",,\n2,,,,,\n', encoding="utf-8")
        rows = manual.read_csv(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["total_results"], rows[0]["same_sellers"], rows[0]["same_prices"]),
                         (12345, 4, [9900, 10500]))


class Scoring(unittest.TestCase):
    def test_price_floor(self):
        sc = scoring.price_scenarios([5000, 8000, 9000], resale_min=7000)
        self.assertEqual(sc, {"lowest": 7000, "median": 8000, "floored": True})

    def test_naver_calibration(self):
        sc = scoring.price_scenarios([10000, 12000, 14000], None, 0.76, 0.91)
        self.assertEqual((sc["lowest"], sc["median"]), (7600, 10920))
        sc = scoring.price_scenarios([10000, 12000, 14000], 9000, 0.76, 0.91)
        self.assertEqual((sc["lowest"], sc["floored"]), (9000, True))  # 보정 후에도 최저판매준수가 하한

    def test_basis_falls_back_to_keyword_results(self):
        prices, basis = scoring.competitor_prices([9000], [8000, 0, 12000], min_matched=3)
        self.assertEqual((prices, basis), ([8000, 12000], "키워드 상위 결과"))
        prices, _ = scoring.competitor_prices([], [100, 9000, 10000, 11000, 900], min_matched=3)
        self.assertEqual(prices, [9000, 10000, 11000])  # 중앙값 절반 미만(부속품·옵션 최저가) 제외

    def test_margin_unknown_fee(self):
        m = scoring.margin(10000, 3000, 2500, None)
        self.assertEqual((m["gross"], m["gross_rate"], m["net"]), (4500, 0.45, None))
        self.assertEqual(scoring.margin(10000, 3000, 2500, 0.05)["net"], 4000)
        self.assertIsNone(scoring.margin(10000, 3000, None, 0.05)["gross"])

    def test_score_direction_and_missing(self):
        metrics = {
            1: {"saturation": 0, "gross_margin_rate": 0.4, "competition_density": 1, "search_volume": 1000},
            2: {"saturation": 9, "gross_margin_rate": 0.1, "competition_density": 50, "search_volume": 100},
            3: {"saturation": 3, "gross_margin_rate": None, "competition_density": 5, "search_volume": 500},
        }
        weights = {"saturation": 0.35, "gross_margin_rate": 0.25, "competition_density": 0.2, "search_volume": 0.2}
        r = scoring.score(metrics, weights)
        self.assertEqual(r[1]["score"], 100.0)
        self.assertEqual(r[2]["score"], 0.0)
        self.assertEqual(r[3]["missing"], ["gross_margin_rate"])
        r = scoring.score(metrics, weights, required=["gross_margin_rate"])
        self.assertIsNone(r[3]["score"])  # 필수 지표가 없으면 점수 없음
        self.assertEqual(r[1]["score"], 100.0)


class Trend(unittest.TestCase):
    def test_window_is_last_12_full_months(self):
        from datetime import date
        self.assertEqual(trend.window(date(2026, 10, 14)), ("2025-10-01", "2026-09-30"))
        self.assertEqual(trend.window(date(2027, 1, 3)), ("2026-01-01", "2026-12-31"))

    def test_growth_and_season(self):
        series = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 20, 30]
        self.assertEqual(trend.growth(series), 2.0)        # (10+20+30)/3 ÷ (10+10+10)/3
        self.assertEqual(trend.season_index(series), 2.4)  # 30 ÷ 평균 12.5
        self.assertIsNone(trend.growth([0, 0, 0, 5, 5, 5]))
        self.assertEqual(trend.months_with_data([0, 1, 0, 2]), 2)

    def test_blog_rate(self):
        from datetime import date
        self.assertEqual(trend.blog_rate(["20261010", "20261012", "20261004"], date(2026, 10, 14)), 0.3)
        self.assertIsNone(trend.blog_rate([]))

    def test_monthly_fills_missing_months(self):
        pts = [{"period": "2026-07-01", "ratio": 5}, {"period": "2026-09-01", "ratio": 9}]
        self.assertEqual(naver_hub._monthly(pts, "2026-07-01", "2026-09-30"), [5, 0.0, 9])

    def test_shop_category_order(self):
        self.assertEqual(pipeline._shop_categories(["가구/인테리어", "침구단품"])[0], "50000004")
        self.assertEqual(pipeline._shop_categories(["스포츠/레저", "캠핑"])[0], "50000007")
        self.assertEqual(pipeline._shop_categories(["생활용품", "욕실용품"])[0], "50000008")


class Verification(unittest.TestCase):
    rules = settings()["verification"]
    ok = {"options": "1", "cutoff": "평일 14시", "return_method": "도매매 반품 신청",
          "info_confirmed": "y", "restriction_confirmed": "Y"}

    def cond(self, **kw):
        view = json.loads(json.dumps(VIEW))["domeggook"]
        c = verify.collect(view, today=__import__("datetime").date(2026, 10, 10))
        c.update(kw)
        return c

    def test_options_parsed_with_surcharge(self):
        opts = self.cond()["options"]
        self.assertEqual([(o["index"], o["price"], o["qty"], o["sellable"]) for o in opts],
                         [(1, 3000, 10, True), (2, 3500, 0, True), (3, 3000, 5, False)])

    def test_pass_with_warnings(self):
        result, fails, warns = verify.evaluate(self.cond(), self.ok, self.rules)
        self.assertEqual((result, fails), ("verified", []))
        self.assertIn("무료배송 판매 시 반품비 2배(6,000원)", warns)

    def test_returns_when_info_missing_or_conditions_fail(self):
        cases = [
            (self.cond(), None, "수동 확인 미입력"),
            (self.cond(), {**self.ok, "cutoff": ""}, "주문 마감 시간 미확보"),
            (self.cond(), {**self.ok, "options": "2"}, "옵션 2 품절"),
            (self.cond(), {**self.ok, "options": "3"}, "옵션 3 도매매 판매 불가·숨김"),
            (self.cond(), {**self.ok, "info_confirmed": "N"}, "상품정보고시·인증 확인 미완료"),
            (self.cond(image_usable=None), self.ok, "이미지 사용 범위 정보 없음"),
            (self.cond(fee_jeju=None), self.ok, "제주·도서산간 추가배송비 정보 없음"),
            (self.cond(deny_market=True), self.ok, "denyMarket=true — 판매 제한 내용 미확보(의미 미확인)"),
            (self.cond(ship_cost=None), self.ok, "배송비 확정 불가(선결제/고정배송비)"),
            (self.cond(return_address=None), self.ok, "반품 주소 없음"),
            (self.cond(inventory=0), self.ok, "품절"),
        ]
        for c, m, reason in cases:
            result, fails, _ = verify.evaluate(c, m, self.rules)
            self.assertEqual(result, "returned", reason)
            self.assertIn(reason, fails)

    def test_slow_shipping_and_image_restriction_are_warnings(self):
        result, _, warns = verify.evaluate(self.cond(prep_days=3, image_usable=False), self.ok, self.rules)
        self.assertEqual(result, "verified")
        self.assertIn("상세페이지 이미지 사용 불허 — 자체 이미지 필요", warns)
        self.assertTrue(any(w.startswith("출고 소요 2일 초과") for w in warns))

    def test_sheet_contains_selected_option(self):
        text = verify.sheet(self.cond(), self.ok, [])
        self.assertIn("흰색 3,000원", text)
        self.assertIn("평일 14시", text)


class EndToEnd(unittest.TestCase):
    """소스를 대체해 search → detail → triage → measure → manual → report 흐름을 확인한다."""

    def test_pipeline(self):
        tmp = Path(tempfile.mkdtemp())
        conn = db.connect(tmp / "t.db")
        listing = [{"no": "101", "title": "걸이", "url": "https://domeme/101"},
                   {"no": "102", "title": "쿠로미", "url": "https://domeme/102"}]
        view102 = json.loads(json.dumps(VIEW))
        view102["domeggook"]["basis"].update(no=102, title="산리오 쿠로미 걸이")
        views = {101: VIEW, 102: view102}
        with mock.patch.object(pipeline, "LLM_DIR", tmp / "llm"), \
             mock.patch.object(pipeline, "MANUAL_DIR", tmp / "manual"), \
             mock.patch.object(pipeline, "REPORT_DIR", tmp / "reports"), \
             mock.patch.object(domeggook, "item_list", return_value=({"numberOfPages": 1}, listing)), \
             mock.patch.object(domeggook, "item_view", side_effect=lambda no: domeggook.unwrap(views[no])), \
             mock.patch.object(naver, "keyword_stats", return_value=[
                 {"relKeyword": "스테인리스걸이", "monthlyPcQcCnt": "300", "monthlyMobileQcCnt": "2700", "compIdx": "중간"}]), \
             mock.patch.object(elevenst, "search", side_effect=lambda q, size=100, sort=None: (
                 (120, [{"name": "스테인리스 다용도 걸이 5개입", "image": "u1", "seller": "a", "price": 9000, "reviews": 5},
                        {"name": "다용도 스테인리스 걸이 5개입 욕실", "image": "u2", "seller": "b", "price": 9900, "reviews": 0},
                        {"name": "스테인리스다용도걸이5개입", "image": "u3", "seller": "c", "price": 8500, "reviews": 2},
                        {"name": "주방 수납함", "image": "u4", "seller": "d", "price": 4000, "reviews": 90}])
                 if sort is None else (3000, [{"price": 7000}, {"price": 12000}]))), \
             mock.patch.object(saturation, "fetch_image", side_effect={
                 "https://img/supplier.png": png(1), "u1": png(1), "u2": png(1), "u3": png(1, 1), "u4": png(7)}.__getitem__):
            self.assertEqual(pipeline.search_supply(conn, kw="걸이"), 2)
            self.assertEqual(pipeline.fetch_details(conn), {"fetched": 2, "excluded": 1, "failed": 0})
            _, n = pipeline.export_triage(conn)
            self.assertEqual(n, 1)
            done = tmp / "triage_done.jsonl"
            done.write_text(json.dumps({"no": 101, "exclude": None, "keywords": ["스테인리스 걸이", "욕실 걸이"]}),
                            encoding="utf-8")
            self.assertEqual(pipeline.import_triage(conn, done), {"triaged": 1, "excluded": 0})
            self.assertEqual(pipeline.measure(conn), {"measured": 1})
            self.assertEqual(pipeline.compete(conn), {"checked": 1, "failed": 0})
            series = [10.0] * 9 + [20.0, 30.0, 40.0]
            with mock.patch.object(naver_hub, "search_trend", side_effect=lambda ks, a, b: {k: series for k in ks}), \
                 mock.patch.object(naver_hub, "shopping_keywords",
                                   side_effect=lambda cat, ks, a, b: {k: (series if cat == "50000008" else [0.0] * 12) for k in ks}), \
                 mock.patch.object(naver_hub, "search_total", return_value=1000), \
                 mock.patch.object(naver_hub, "blog_recent", return_value=["20261001"] * 10):
                self.assertEqual(pipeline.collect_trends(conn), {"keywords": 1, "failed": 0})
                self.assertEqual(pipeline.collect_trends(conn), {"keywords": 0, "failed": 0})  # 같은 날 재수집 안 함
            page, n = pipeline.export_manual(conn)  # 검증 표본 화면도 경쟁 수집 후 만들 수 있다
            self.assertEqual(n, 1)
            self.assertIn("스테인리스 다용도 걸이", Path(page).read_text(encoding="utf-8"))
            row = pipeline.build_rows(conn)[0]
            self.assertEqual(row["saturation"], 3)
            self.assertEqual(row["same_reviews"], 7)
            self.assertEqual(row["shop_total"], 3000)
            self.assertEqual((row["trend_growth"], row["shop_growth"], row["blog_total"]), (3.0, 3.0, 1000))
            self.assertEqual(row["price_basis"], "동일 상품")
            self.assertEqual(row["price_lowest"], 7000)  # 8,500×0.76=6,460 → 최저판매준수가 7,000 하한
            self.assertEqual(row["price_median"], 8190)  # 9,000×0.91
            self.assertEqual(row["search_volume"], 3000)
            self.assertEqual(row["competition_density"], 1.0)
            self.assertEqual(row["margin_lowest"]["gross"], 7000 - 3000 - 2500)
            self.assertEqual(row["price_compare_min"], 8900)
            md, _, count = pipeline.write_report(conn)
            self.assertEqual(count, 1)
            self.assertIn("수수료율 미확인", Path(md).read_text(encoding="utf-8"))
            with mock.patch.object(pipeline, "VERIFY_DIR", tmp / "verify"):
                page, n = pipeline.export_verify(conn, top=5)
                self.assertEqual(n, 1)
                self.assertIn("판매 가능 조건 확인", Path(page).read_text(encoding="utf-8"))
                filled = tmp / "verify_done.csv"
                filled.write_text("no,options,cutoff,return_method,info_confirmed,restriction_confirmed,note\n"
                                  "101,1,평일 14시,도매매 반품 신청,Y,Y,\n", encoding="utf-8")
                counts = pipeline.import_verify(conn, filled)
            self.assertEqual((counts["verified"], counts["returned"]), (1, 0))
            self.assertIn("흰색", Path(counts["sheet"]).read_text(encoding="utf-8"))
            self.assertEqual(pipeline.build_rows(conn)[0]["stage"], "verified")


if __name__ == "__main__":
    unittest.main()

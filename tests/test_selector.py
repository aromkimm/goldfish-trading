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
from selector.sources import commerce, domeggook, elevenst, naver, naver_hub


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


def candidate_db(cands: dict, supply_price: int = 6900, ship_cost: int = 3000, raw: dict | None = None) -> "sqlite3.Connection":
    """경쟁 수집까지 마친(checked) 후보를 합성한다. cands: {상품번호: (상품명, 11번가 상품 단위 기록)}."""
    conn = db.connect(Path(tempfile.mkdtemp()) / "t.db")
    for no, (title, items) in cands.items():
        conn.execute("INSERT INTO candidates(no, title, stage, keywords, added_at) VALUES (?, ?, 'checked', ?, ?)",
                     (no, title, json.dumps([title]), "2026-10-15"))
        conn.execute("INSERT INTO supply_snapshots VALUES (?, '2026-10-15T00:00:00+00:00', ?, ?)", (no, json.dumps(
            {"title": title, "supply_price": supply_price, "ship_cost": ship_cost, "ship_fee_type": "고정배송비"}),
            json.dumps(raw or {})))
        photo = [i for i in items if i["photo"]]
        conn.execute("INSERT INTO competition (no, fetched_at, title_query, checked, image_failed, same_sellers, same_prices,"
                     " same_reviews, keyword, similar_prices, type_sellers, type_prices, items, keyword_items)"
                     " VALUES (?, '2026-10-15T00:00:00+00:00', ?, ?, 0, ?, '[]', 0, ?, '[]', ?, '[]', ?, '[]')",
                     (no, title, len(items), len({i["seller"] for i in photo}), title,
                      len({i["seller"] for i in items if i["type"]}), json.dumps(items)))
    return conn


class SearchVolume(unittest.TestCase):
    def test_less_than_10_kept_as_range_not_zero(self):
        lt = naver.LESS_THAN_10
        self.assertEqual(pipeline._search_volume({"pc": lt, "mobile": 1000}), (1000, "1,000~1,009"))
        self.assertEqual(pipeline._search_volume({"pc": lt, "mobile": lt}), (0, "<20"))
        self.assertEqual(pipeline._search_volume({"pc": 30, "mobile": 270}), (300, "300"))
        self.assertEqual(pipeline._search_volume({"pc": None, "mobile": 10}), (None, "모름"))


class OptionCosts(unittest.TestCase):
    def test_max_sellable_option_margin_shown(self):
        """사례 60860244: 30~90L 옵션 추가금 0~5,000원이 기본 옵션 마진에 빠져 있었다."""
        title = "접이식 폴딩 리빙박스"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        raw = {"selectOpt": json.dumps({"data": {
            "00": {"name": "30L", "sup": "1", "supPrice": "0", "qty": "10", "hid": "0"},
            "01": {"name": "90L", "sup": "1", "supPrice": "5000", "qty": "3", "hid": "0"},
            "02": {"name": "120L", "sup": "1", "supPrice": "9000", "qty": "0", "hid": "0"}}})}  # 품절 옵션은 제외
        conn = candidate_db({1: (title, [free(20000)] * 3)}, supply_price=5300, ship_cost=3000, raw=raw)
        row = pipeline.build_rows(conn)[0]
        self.assertEqual((row["option_count"], row["option_supply_max"]), (2, 10300))
        lowest = row["price_lowest"]
        self.assertEqual(row["margin_lowest_max_option"]["gross"], lowest - 10300 - 3000)
        self.assertEqual(row["margin_lowest"]["gross"], lowest - 5300 - 3000)  # 판정은 기본 옵션(결정 전 현행)


class Sensitivity(unittest.TestCase):
    def test_recommendation_dependent_on_low_price_removal_is_flagged(self):
        """사례: 저가 제거를 끄면 추천 9개 중 7개가 빠졌다. 그런 추천에는 의존한 가정을 표시한다."""
        title = "메쉬 스틸 부착식 선반"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        conn = candidate_db({1: (title, [free(2000), free(10000), free(10000), free(10000)])}, supply_price=3000, ship_cost=2000)
        row = pipeline.build_rows(conn)[0]
        self.assertTrue(row["recommended"])
        self.assertEqual(row["sensitive_to"], ["저가 제거 안 함"])
        self.assertEqual(pipeline.build_rows(conn, sensitivity=False)[0]["sensitive_to"], [])


class ReturnBurden(unittest.TestCase):
    def test_return_cost_in_sales_units(self):
        self.assertEqual(scoring.return_burden(3000, True, 1500), {"cost": 6000, "sales_to_cover": 4.0})
        self.assertEqual(scoring.return_burden(3000, False, -100), {"cost": 3000, "sales_to_cover": None})
        self.assertEqual(scoring.return_burden(None, True, 1500), {"cost": None, "sales_to_cover": None})


class FeeBasis(unittest.TestCase):
    def test_net_basis_uses_fee_and_unknown_fee_blocks(self):
        """사례: 수수료율을 넣어도 추천이 그대로였다. net 기준이면 수수료가 판정에 반영되고, 수수료 모름이면 추천하지 않는다."""
        title = "극세사 담요"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        conn = candidate_db({1: (title, [free(10000), free(10000), free(10000)])}, supply_price=5000, ship_cost=2600)
        cfg = json.loads(json.dumps(settings()))
        cfg["naver_calibration"].update(lowest_price=1.0, median_price=1.0)  # 마진 24%: 수수료 10%면 14%
        recommended = lambda: pipeline.build_rows(conn)[0]["recommended"]
        with mock.patch.object(pipeline, "settings", return_value=cfg):
            self.assertTrue(recommended())
            cfg["pricing"]["platform_fee_rate"] = 0.10
            self.assertTrue(recommended())  # gross 기준은 수수료와 무관(현행)
            cfg["scoring"]["margin_basis"] = "net"
            self.assertFalse(recommended())
            cfg["pricing"]["platform_fee_rate"] = None
            self.assertFalse(recommended())


class Judgments(unittest.TestCase):
    def test_excluded_judgment_blocks_recommendation(self):
        """회귀: 네이버 표본에서 부적합으로 본 56868432가 보정 변경 뒤 다시 추천됐다. 제외 판정은 재계산으로 뒤집히지 않는다."""
        title = "무타공 욕실 다용도 수납 드라이기 거치대"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        conn = candidate_db({56868432: (title, [free(20000), free(21000), free(22000)])}, supply_price=3000, ship_cost=2000)
        self.assertTrue(pipeline.build_rows(conn)[0]["recommended"])
        db.add_judgment(conn, 56868432, "제외", "같은 유형 다수·상위 리뷰 수천", "네이버 캡처 표본", "2026-10-14")
        row = pipeline.build_rows(conn)[0]
        self.assertFalse(row["recommended"])
        self.assertEqual(row["judgment"]["verdict"], "제외")
        db.add_judgment(conn, 56868432, "추가 확인", "벽부착형만 재비교", "재검토")  # 새 판정만 제외를 푼다
        self.assertTrue(pipeline.build_rows(conn)[0]["recommended"])

    def test_review_required_and_invalidated_by_new_evidence(self):
        title = "스테인리스 다용도 걸이"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        conn = candidate_db({1: (title, [free(20000), free(21000), free(22000)]),
                             2: (title + " 대형", [free(20000), free(21000), free(22000)])}, supply_price=3000, ship_cost=2000)
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(pipeline, "LLM_DIR", tmp), mock.patch.object(pipeline, "VERIFY_DIR", tmp), \
             mock.patch.object(domeggook, "item_view", side_effect=lambda no: domeggook.unwrap(VIEW)):
            self.assertEqual(pipeline.export_verify(conn)[1], 0)  # 검토 전에는 대상 없음
            done = tmp / "done.jsonl"
            done.write_text("\n".join(json.dumps({"no": no, "verdict": v, "rationale": "r"}, ensure_ascii=False)
                                      for no, v in ((1, "추가 확인"), (2, "제외"))), encoding="utf-8")
            pipeline.import_review(conn, done)
            rows = {r["no"]: r for r in pipeline.build_rows(conn)}
            self.assertTrue(rows[1]["review_current"] and rows[1]["recommended"])
            self.assertFalse(rows[2]["recommended"])  # 검토의 제외 판정은 추천에서 뺀다
            with self.assertRaises(ValueError):
                pipeline.export_verify(conn, nos=[2])
            self.assertEqual(pipeline.export_verify(conn)[1], 1)
            conn.execute("UPDATE competition SET fetched_at='2026-10-16T00:00:00+00:00' WHERE no=1")  # 경쟁 재수집
            self.assertFalse(next(r for r in pipeline.build_rows(conn) if r["no"] == 1)["review_current"])
            self.assertEqual(pipeline.export_verify(conn)[1], 0)

    def test_review_needs_valid_verdict(self):
        conn = candidate_db({1: ("걸이", [])})
        path = Path(tempfile.mkdtemp()) / "d.jsonl"
        path.write_text(json.dumps({"no": 1, "rationale": "판정 없음"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            pipeline.import_review(conn, path)

    def test_invalid_judgment_rejected(self):
        conn = db.connect(":memory:")
        with self.assertRaises(ValueError):
            db.add_judgment(conn, 1, "좋음", "x", "y")
        with self.assertRaises(ValueError):
            db.add_judgment(conn, 1, "제외", "", "y")


class ComparablePrices(unittest.TestCase):
    def test_only_free_shipping_prices_are_compared(self):
        items = [{"price": 9000, "delivery": "무료"}, {"price": 4000, "delivery": "착불/선결제"},
                 {"price": 5000, "delivery": "조건부무료"}, {"price": 8000, "delivery": ""}, {"price": None, "delivery": "무료"}]
        prices, dropped, paid = scoring.comparable_prices(items)
        self.assertEqual((prices, dropped["배송 조건"], paid), ([9000], 3, [4000, 5000, 8000]))

    def test_paid_display_price_is_lowest_scenario_bound(self):
        """착불 표시가는 결제 총액의 하한: 중앙가에는 섞지 않고 최저가가 부풀지 않게 하한으로 쓴다."""
        self.assertEqual(scoring.paid_lower_bound([9000, 9500, 10000], [3000, 6800]), 6800)  # 3,000은 중앙값 절반 미만
        sc = scoring.price_scenarios([9000, 9500, 10000], None, lowest_bound=6800)
        self.assertEqual((sc["lowest"], sc["median"]), (6800, 9500))

    def test_quantity_size_and_kind_mismatch_dropped(self):
        """개발 사례: 업소용 10개 묶음 바구니, 200×230 담요, LP 거치대에 섞인 LP 수납장."""
        free = lambda name, price: {"name": name, "price": price, "delivery": "무료"}
        _, d, _ = scoring.comparable_prices([free("플라스틱 바구니 10개 업소용", 70000)], "다용도 플라스틱 바구니")
        self.assertEqual(d["수량·치수"], 1)
        prices, d, _ = scoring.comparable_prices([free("극세사 담요 200x230", 50000), free("극세사 담요 70x100", 9000)],
                                              "극세사 담요 100*70")
        self.assertEqual((prices, d["수량·치수"]), ([9000], 1))
        title = "아크릴 투명 lp 거치대 보관함 책전시대"
        prices, d, _ = scoring.comparable_prices(
            [free("lp 거치대 투명 스탠드 보관함 책전시대 아크릴거치대", 4490),
             free("레코드 보관함 LP 아크릴 바이닐 스탠드 진열장 수납 거치대 앨범 월넛 투명 박스", 118210)], title, 0.5)
        self.assertEqual((prices, d["다른 종류"]), ([4490], 1))

    def test_same_photo_prices_bound_lowest_when_type_set_used(self):
        """개발 사례 67266790: 같은 사진 무료배송 가격이 2개뿐이라 같은 유형(가구 혼입) 가격을 써도 최저가는 같은 사진 가격을 넘지 않는다."""
        title = "슬림 틈새 신발장 조립식"
        free = lambda price, photo: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": photo, "type": True}
        conn = candidate_db({1: (title, [free(9158, True), free(11621, True), free(35720, False),
                                         free(90000, False), free(112867, False)])})
        row = pipeline.build_rows(conn)[0]
        self.assertEqual(row["price_basis"], "같은 유형")
        self.assertEqual(row["price_low_bound"], 9158)
        self.assertEqual(row["price_lowest"], round(9158 * settings()["naver_calibration"]["lowest_price"]))

    def test_price_shortage_listed_for_review_not_dropped_silently(self):
        """개발 사례 68051669: 같은 사진 가격 2건뿐이라 키워드 결과로 넘어가 추천에서 빠졌다. 확인 대상으로 비교표에 남긴다."""
        title = "벽면 소켓선반 콘센트선반"
        free = lambda price: {"name": title, "seller": str(price), "price": price, "delivery": "무료", "photo": True, "type": True}
        conn = candidate_db({68051669: (title, [free(9460), free(10320)])}, supply_price=3000, ship_cost=2000)
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(pipeline, "REPORT_DIR", tmp):
            md, _, _ = pipeline.write_report(conn)
        row = pipeline.build_rows(conn)[0]
        self.assertFalse(row["recommended"])
        self.assertEqual(row["price_shortage"]["same_photo_prices"], [9460, 10320])
        text = Path(md).read_text(encoding="utf-8")
        self.assertIn("## 비교 가격 부족 — 확인 대상", text)
        self.assertIn("9,460, 10,320", text)

    def test_dispersion(self):
        self.assertIsNone(scoring.dispersion([1, 2, 3]))
        self.assertGreater(scoring.dispersion([5000, 6000, 7000, 90000, 100000]), 2.0)

    def test_legacy_rows_without_items_mark_conditions_unknown(self):
        comp = {"items": None, "same_prices": "[1,2,3]", "type_prices": "[4]", "similar_prices": "[5]"}
        self.assertEqual(pipeline._price_sets(comp, "x", 0.5)["동일 상품"], ([1, 2, 3], None, []))


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
                 (120, [{"name": "스테인리스 다용도 걸이 5개입", "image": "u1", "seller": "a", "price": 9000, "reviews": 5, "delivery": "무료"},
                        {"name": "다용도 스테인리스 걸이 5개입 욕실", "image": "u2", "seller": "b", "price": 9900, "reviews": 0, "delivery": "무료"},
                        {"name": "스테인리스다용도걸이5개입", "image": "u3", "seller": "c", "price": 8500, "reviews": 2, "delivery": "무료"},
                        {"name": "스테인리스 다용도 걸이 5개입", "image": "u5", "seller": "e", "price": 5000, "reviews": 0, "delivery": "착불/선결제"},
                        {"name": "주방 수납함", "image": "u4", "seller": "d", "price": 4000, "reviews": 90, "delivery": "무료"}])
                 if sort is None else (3000, [{"price": 7000, "delivery": "무료"}, {"price": 12000, "delivery": "무료"}]))), \
             mock.patch.object(saturation, "fetch_image", side_effect={
                 "https://img/supplier.png": png(1), "u1": png(1), "u2": png(1), "u3": png(1, 1), "u4": png(7),
                 "u5": png(1)}.__getitem__):
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
            with mock.patch.object(commerce, "catalogs", return_value=(40, [
                    {"name": "스테인리스 다용도 걸이 5개입"}, {"name": "스테인리스 다용도 걸이"}, {"name": "주방 수납함"}])), \
                 mock.patch("time.sleep"):
                self.assertEqual(pipeline.collect_catalogs(conn)["checked"], 1)
                self.assertEqual(pipeline.collect_catalogs(conn)["skipped"], 1)  # 같은 날 재조회 안 함
            row = pipeline.build_rows(conn)[0]
            self.assertEqual((row["catalog_similar"], row["catalog_exact"]), (2, 2))  # 전체 상품명 4단어 중 3단어(75%) 이상 담은 이름 2개
            self.assertEqual(row["saturation"], 4)  # 판매자 수는 배송 조건과 관계없이 센다
            self.assertEqual(row["price_excluded"]["배송 조건"], 1)  # 착불 5,000원은 가격 비교에서 뺀다
            self.assertEqual(row["same_reviews"], 7)
            self.assertEqual(row["shop_total"], 3000)
            self.assertEqual((row["trend_growth"], row["shop_growth"], row["blog_total"]), (3.0, 3.0, 1000))
            self.assertEqual(row["price_basis"], "동일 상품")
            self.assertEqual(row["price_low_bound"], 5000)  # 착불 5,000원은 최저가 시나리오의 하한
            self.assertEqual(row["price_lowest"], 7000)  # 5,000×0.76=3,800 → 최저판매준수가 7,000 하한
            self.assertEqual(row["price_median"], 8190)  # 9,000×0.91
            self.assertEqual(row["search_volume"], 3000)
            self.assertEqual(row["competition_density"], 1.0)
            self.assertEqual(row["margin_lowest"]["gross"], 7000 - 3000 - 2500)
            self.assertEqual(row["price_compare_min"], 8900)
            md, _, count = pipeline.write_report(conn)
            self.assertEqual(count, 1)
            self.assertIn("수수료율 미확인", Path(md).read_text(encoding="utf-8"))
            with mock.patch.object(pipeline, "VERIFY_DIR", tmp / "verify"):
                with self.assertRaises(ValueError):  # 상위 후보 검토 없이 판매 조건 확인으로 넘기지 않는다
                    pipeline.export_verify(conn, nos=[101])
                path, n = pipeline.export_review(conn, 5)
                pending = json.loads(Path(path).read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(pending["info_duty"], {})  # 합성 응답에는 고시 항목이 없다
                self.assertEqual(len(pending["compared_items"]), 4)  # 같은 사진 상품(착불 포함)을 검토자가 대조
                done = tmp / "review_done.jsonl"
                done.write_text(json.dumps({"no": 101, "verdict": "추가 확인", "rationale": "같은 사진 3곳 무료배송",
                                            "risks": "", "unknowns": "네이버 경쟁"}, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(pipeline.import_review(conn, done), 1)
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


class DataDirSeparation(unittest.TestCase):
    """--data-dir는 DB·작업 파일을 지정 폴더에만 만들고, --skip-db는 다른 DB의 후보를 넣지 않는다."""

    def test_data_dir_and_skip_db(self):
        from selector import cli
        tmp = Path(tempfile.mkdtemp())
        old = db.connect(tmp / "old.db")
        old.execute("INSERT INTO candidates(no, title, url, source_query, added_at) VALUES (101,'걸이','u','{}','t')")
        old.commit()
        old.close()
        listing = [{"no": "101", "title": "걸이", "url": "u1"}, {"no": "102", "title": "선반", "url": "u2"}]
        saved = (pipeline.LLM_DIR, pipeline.MANUAL_DIR, pipeline.VERIFY_DIR, pipeline.REPORT_DIR)
        try:
            with mock.patch.object(domeggook, "item_list", return_value=({"numberOfPages": 1}, listing)), \
                 mock.patch("sys.stdout", new=io.StringIO()):
                cli.main(["--data-dir", str(tmp / "eval"), "search", "--kw", "걸이", "--skip-db", str(tmp / "old.db")])
                cli.main(["--data-dir", str(tmp / "eval"), "triage-export"])
            self.assertEqual(pipeline.VERIFY_DIR, tmp / "eval" / "verify")
        finally:
            pipeline.LLM_DIR, pipeline.MANUAL_DIR, pipeline.VERIFY_DIR, pipeline.REPORT_DIR = saved
        new = db.connect(tmp / "eval" / "selector.db")
        self.assertEqual([r["no"] for r in new.execute("SELECT no FROM candidates")], [102])
        self.assertTrue((tmp / "eval" / "llm" / "triage_pending.jsonl").exists())
        old = db.connect(tmp / "old.db")
        self.assertEqual(old.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)

    def test_skip_db_missing_path(self):
        from selector import cli
        with self.assertRaises(FileNotFoundError):
            cli.known_nos(Path(tempfile.mkdtemp()) / "none.db")


class InfoDutyDeferred(unittest.TestCase):
    """상품정보고시를 상세페이지로 미룬 값은 표기 변형과 관계없이 수동 확인 대상이다 (2026-10-15 새 표본에서 '상세정보별도표시' 누락)."""

    def test_variants(self):
        for desc in ("", None, "상세정보 별도표기", "[상세정보 별도표기]", "상세정보 별도표시", "상세정보별도표시",
                     "상품 상세정보에 별도 표기"):
            self.assertTrue(verify.info_deferred(desc), desc)
        for desc in ("중국", "해당사항 없음", "별도 구매", "상세페이지 참조 아크릴 A4"):
            self.assertFalse(verify.info_deferred(desc), desc)

import datetime as dt
import os
import random
import sys
import tempfile
import unittest

os.environ["TWSE_GAP_SEC"] = "0"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scanner"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import strategy as S  # noqa
import twse_daily as T  # noqa
import scan as SC  # noqa
from demo_data import _series  # noqa

TODAY = dt.date(2026, 10, 28)
CODES = [str(1101 + i * 37) for i in range(60)] + ["0050", "00878"]
HOLIDAYS = {"2026-10-09", "2026-10-10", "2026-02-16", "2026-02-17", "2026-06-19"}
SER = {c: {d.isoformat(): (o, h, l, cl, v) for d, o, h, l, cl, v in _series(c if c.isdigit() else "50", end=TODAY)}
       for c in CODES}


def make_payload(ymd, old=False):
    iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    if iso in HOLIDAYS or dt.date.fromisoformat(iso).weekday() >= 5 or iso > TODAY.isoformat():
        return {"stat": "很抱歉，沒有符合條件的資料!"}
    fields = ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價",
              "漲跌(+/-)", "漲跌價差", "最後揭示買價", "最後揭示買量", "最後揭示賣價", "最後揭示賣量", "本益比"]
    data = []
    for i, c in enumerate(CODES):
        if c == "1138" and iso >= "2026-09-01":   # 模擬停牌：無成交
            data.append([c, "停牌股", "0", "0", "0", "--", "--", "--", "--", "<p> </p>", "0.00", "--", "0", "--", "0", "0.00"])
            continue
        o, h, l, cl, v = SER[c][iso]
        data.append([c, f"測試{c}", f"{v:,}", "1,234", f"{int(v*cl):,}", f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{cl:.2f}",
                     "<p style= color:red>+</p>", "0.10", "", "", "", "", "12.3"])
    idx_table = {"title": "價格指數(臺灣證券交易所)", "fields": ["指數", "收盤指數", "漲跌(+/-)"], "data": [["發行量加權股價指數", "23,000", "+"]]}
    if old:
        return {"stat": "OK", "fields1": idx_table["fields"], "data1": idx_table["data"], "fields9": fields, "data9": data}
    return {"stat": "OK", "date": ymd, "tables": [idx_table, {"title": f"{ymd} 每日收盤行情(全部(不含權證、牛熊證))",
                                                      "fields": fields, "data": data}]}


class Fetcher:
    def __init__(self, fail_once=(), old_dates=()):
        self.calls, self.fail_once, self.old = [], set(fail_once), set(old_dates)

    def __call__(self, url):
        self.calls.append(url)
        if "openapi" in url:
            return []
        ymd = url.split("date=")[1][:8]
        iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
        if iso in self.fail_once:
            raise RuntimeError("simulated network error")
        return make_payload(ymd, old=iso in self.old)


class TestScanner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.mkdtemp()
        cls.store = T.Store(os.path.join(cls.td, "store"))
        cls.f = Fetcher(fail_once={"2026-08-12"}, old_dates={"2026-07-01", "2026-07-02"})
        T.sync(cls.store, TODAY, min_open_days=230, fetcher=cls.f, log=lambda *a: None)

    def test_1_sync_and_gap(self):
        cal = self.store.cal
        self.assertEqual(cal["2026-10-09"], "closed")
        self.assertEqual(cal["2026-08-12"], "error")          # 第一次失敗
        self.assertEqual(cal["2026-07-01"], "open")           # 舊格式 fields9 解析成功
        self.assertGreaterEqual(len(self.store.open_days()), 230)
        res = SC.scan(self.store)
        self.assertEqual(res["status"], "INCOMPLETE")         # 有缺口 → 不發布訊號
        self.assertIn("2026-08-12", res["gaps"])
        # 下一次執行：失敗日被重試補齊
        self.f.fail_once.clear()
        n_before = len(self.f.calls)
        T.sync(self.store, TODAY, min_open_days=230, fetcher=self.f, log=lambda *a: None)
        self.assertEqual(self.store.cal["2026-08-12"], "open")
        self.assertLess(len(self.f.calls) - n_before, 5)     # 只補缺的，不重抓整段

    def test_2_scan_matches_single_stock_analyzer(self):
        self.f.fail_once.clear()
        T.sync(self.store, TODAY, min_open_days=230, fetcher=self.f, log=lambda *a: None)
        res = SC.scan(self.store)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(res["date"], "2026-10-28")
        got = {e["code"]: e["signal"] for e in res["buy"] + res["watch"]}
        # 以 APP 的 analyze() 對每檔重新計算（同一窗口），訊號必須一致
        window = self.store.open_days()[-SC.WINDOW:]
        P = S.params_with_defaults()
        now = dt.datetime(2026, 10, 28, 18, 0, tzinfo=T.TZ)
        expected, scanned = {}, 0
        for c in CODES:
            rows = []
            for d in window:
                day = self.store.load_day(d)
                if c in day:
                    n, o, h, l, cl, v = day[c]
                    rows.append(dict(date=d, open=o, high=h, low=l, close=cl, volume=v, valid=True, issue=None))
            if not rows or rows[-1]["date"] != "2026-10-28":
                continue
            scanned += 1
            r = S.analyze(dict(stock=c, name="", rows=rows, notes=[]), "2026-10-28", P, now)
            if r.get("signal") in ("BUY", "WATCH"):
                expected[c] = r["signal"]
            # 指標一致性
            full = S.compute_indicators(rows, P)[-1]
            fast = SC.indicators_at(rows, P)
            for k in full:
                if full[k] is None:
                    self.assertIsNone(fast[k])
                else:
                    self.assertAlmostEqual(full[k], fast[k], places=9)
        self.assertEqual(got, expected)
        self.assertEqual(res["counts"]["scanned"], scanned)
        self.assertNotIn("1138", {e["code"] for e in res["buy"] + res["watch"]})  # 停牌股不列入
        print(f"\n scan counts {res['counts']}  BUY={[e['code'] for e in res['buy']]}  WATCH={[e['code'] for e in res['watch']]}")

    def test_3_find_a_buy_day_and_outputs(self):
        # 找出歷史上有 BUY 的日期，確認輸出欄位完整
        found = None
        for d in reversed(self.store.open_days()[-120:]):
            r = SC.scan(self.store, d)
            if r["status"] == "OK" and r["buy"]:
                found = r
                break
        self.assertIsNotNone(found)
        b = found["buy"][0]
        for k in ("code", "name", "close", "rvol", "prev_high", "initial_stop", "risk_pct", "conditions"):
            self.assertIn(k, b)
        self.assertTrue(all(c["ok"] for c in b["conditions"]))
        site = os.path.join(self.td, "site")
        SC.write_outputs(found, site)
        self.assertTrue(os.path.exists(os.path.join(site, "data", "latest.json")))
        self.assertTrue(os.path.exists(os.path.join(site, "data", "index.json")))

    def test_4_parsers(self):
        st, s = T.parse_mi_index({"stat": "很抱歉，沒有符合條件的資料!"})
        self.assertEqual(st, "closed")
        d, s2 = T.parse_openapi_all([{"Date": "1151028", "Code": "2409", "Name": "友達", "TradeVolume": "123456",
                                       "OpeningPrice": "34.00", "HighestPrice": "34.50", "LowestPrice": "33.80",
                                       "ClosingPrice": "34.05"}])
        self.assertEqual(d, "2026-10-28")
        self.assertEqual(s2["2409"][4], 34.05)


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""DEMO 模式：產生「TWSE STOCK_DAY 格式」的模擬資料，僅供離線試用與測試。
畫面會明確標示 DEMO，數值並非真實行情。"""
import datetime as dt
import math
import random


def _series(stock, start=dt.date(2023, 1, 2), end=None):
    end = end or dt.date.today()
    rnd = random.Random(int(stock) if stock.isdigit() else 7)
    price, base_vol = 15.0, 30_000_000
    d, out = start, []
    regime = 0
    while d <= end:
        if d.weekday() < 5:
            if rnd.random() < 0.02:
                regime = rnd.choice([-1, 0, 1, 1])
            drift = 0.0012 * regime
            ret = drift + rnd.gauss(0, 0.018)
            vol_mult = 1 + abs(ret) * 25 + (rnd.random() < 0.05) * rnd.uniform(0.5, 1.5)
            o = price * (1 + rnd.gauss(0, 0.006))
            c = max(1.0, price * (1 + ret))
            h = max(o, c) * (1 + abs(rnd.gauss(0, 0.008)))
            l = min(o, c) * (1 - abs(rnd.gauss(0, 0.008)))
            v = int(base_vol * vol_mult * rnd.uniform(0.7, 1.3))
            out.append((d, round(o, 2), round(h, 2), round(l, 2), round(c, 2), v))
            price = c
        d += dt.timedelta(days=1)
    return out


_CACHE = {}


def demo_fetcher(stock, ym):
    if stock not in _CACHE:
        _CACHE[stock] = _series(stock)
    y, m = int(ym[:4]), int(ym[4:])
    rows = [r for r in _CACHE[stock] if r[0].year == y and r[0].month == m]
    if not rows:
        return {"stat": "很抱歉，沒有符合條件的資料!"}
    data = []
    prev = None
    for d, o, h, l, c, v in rows:
        chg = "0.00" if prev is None else f"{c - prev:+.2f}"
        data.append([f"{d.year-1911}/{d.month:02d}/{d.day:02d}", f"{v:,}", f"{int(v*c):,}",
                     f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}", chg, f"{v//2000:,}"])
        prev = c
    return {"stat": "OK", "date": f"{ym}01",
            "title": f"{y-1911}年{m:02d}月 {stock} DEMO模擬 各日成交資訊",
            "fields": ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "成交筆數"],
            "data": data}

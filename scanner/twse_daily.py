"""TWSE 每日收盤行情（全部上市股票）收集器。

主要來源：https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=YYYYMMDD&type=ALLBUT0999&response=json
  （每日收盤行情－全部，不含權證、牛熊證）。一次請求取得當日所有上市證券的開高低收量。
備援來源（只有最新一日）：https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL

儲存：store/daily/YYYY-MM-DD.json  {"date":..., "stocks": {代號: [名稱, 開, 高, 低, 收, 成交股數] }}
      無成交（價格 "--"）的股票不寫入該日，等同該股票當日不是有效交易日。
      store/calendar.json  記錄每個日期的狀態：open（已存）/ closed（休市）/ error（抓取失敗，待重試）。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import time
import urllib.request

TZ = dt.timezone(dt.timedelta(hours=8))
MI_INDEX = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
MI_INDEX_OLD = "https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={d}&type=ALLBUT0999"
OPENAPI_ALL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
GAP_SEC = float(os.environ.get("TWSE_GAP_SEC", "3.0"))  # TWSE 對頻繁請求會暫時封鎖，保守間隔
NO_DATA_HINTS = ("沒有符合", "查無資料", "很抱歉")

_last = 0.0


def now_tw():
    return dt.datetime.now(TZ)


def _ctx():
    ctx = ssl.create_default_context()
    if hasattr(ssl, "VERIFY_X509_STRICT"):
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def http_json(url, fetcher=None):
    if fetcher:
        return fetcher(url)
    global _last
    wait = GAP_SEC - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (VolumeBreakoutScanner; personal research)",
        "Accept": "application/json,text/plain,*/*"})
    last_err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_ctx()) as r:
                text = r.read().decode("utf-8", "replace").strip()
            _last = time.time()
            if not text.startswith(("{", "[")):
                raise ValueError("非 JSON 回應（可能被暫時封鎖）")
            return json.loads(text)
        except Exception as e:  # noqa
            last_err = e
            _last = time.time()
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"{url} 失敗：{last_err}")


def _num(s):
    s = re.sub(r"<[^>]+>", "", str(s)).replace(",", "").strip()
    if s in ("", "--", "---", "X0.00"):
        return None
    s = s.lstrip("+X")
    try:
        v = float(s)
    except ValueError:
        return None
    return v


def parse_mi_index(payload):
    """回傳 (status, {code: [name,o,h,l,c,v]})；status: open / closed / bad。"""
    stat = str(payload.get("stat", ""))
    if stat != "OK":
        return ("closed" if any(h in stat for h in NO_DATA_HINTS) else "bad"), {}
    tables = list(payload.get("tables") or [])
    # 舊版格式：fields1..fields9 / data1..data9
    for k in list(payload.keys()):
        m = re.match(r"fields(\d+)$", k)
        if m:
            tables.append({"fields": payload[k], "data": payload.get(f"data{m.group(1)}", [])})
    target = None
    for t in tables:
        f = [str(x) for x in (t.get("fields") or [])]
        if any("證券代號" in x for x in f) and any("收盤價" in x for x in f) and any("開盤價" in x for x in f):
            if target is None or len(t.get("data") or []) > len(target.get("data") or []):
                target = t
    if not target:
        return "bad", {}
    f = [str(x) for x in target["fields"]]

    def idx(label):
        return next(i for i, x in enumerate(f) if label in x)

    iC, iN, iV = idx("證券代號"), idx("證券名稱"), idx("成交股數")
    iO, iH, iL, iZ = idx("開盤價"), idx("最高價"), idx("最低價"), idx("收盤價")
    out = {}
    for r in target.get("data") or []:
        code = re.sub(r"<[^>]+>", "", str(r[iC])).strip().strip('="')
        o, h, l, c, v = _num(r[iO]), _num(r[iH]), _num(r[iL]), _num(r[iZ]), _num(r[iV])
        if None in (o, h, l, c, v) or v <= 0:
            continue
        if h < max(o, c) - 1e-9 or l > min(o, c) + 1e-9:
            continue
        out[code] = [str(r[iN]).strip(), o, h, l, c, int(v)]
    return ("open" if out else "bad"), out


def parse_openapi_all(rows):
    """STOCK_DAY_ALL：回傳 (date_iso or None, {code: [...]})。"""
    out, date = {}, None
    for r in rows or []:
        d = str(r.get("Date", ""))
        if re.fullmatch(r"\d{7}", d):
            date = f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:7]}"
        o, h, l, c = (_num(r.get(k)) for k in ("OpeningPrice", "HighestPrice", "LowestPrice", "ClosingPrice"))
        v = _num(r.get("TradeVolume"))
        if None in (o, h, l, c, v) or v <= 0 or h < max(o, c) or l > min(o, c):
            continue
        out[str(r.get("Code", "")).strip()] = [str(r.get("Name", "")).strip(), o, h, l, c, int(v)]
    return date, out


class Store:
    def __init__(self, root):
        self.root = root
        self.daily = os.path.join(root, "daily")
        os.makedirs(self.daily, exist_ok=True)
        self.cal_path = os.path.join(root, "calendar.json")
        self.cal = {}
        if os.path.exists(self.cal_path):
            with open(self.cal_path, encoding="utf-8") as f:
                self.cal = json.load(f)

    def save_cal(self):
        with open(self.cal_path, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(self.cal.items())), f, ensure_ascii=False, indent=0)

    def put_day(self, date, stocks, source):
        with open(os.path.join(self.daily, f"{date}.json"), "w", encoding="utf-8") as f:
            json.dump({"date": date, "source": source, "stocks": stocks}, f, ensure_ascii=False, separators=(",", ":"))
        self.cal[date] = "open"

    def load_day(self, date):
        with open(os.path.join(self.daily, f"{date}.json"), encoding="utf-8") as f:
            return json.load(f)["stocks"]

    def open_days(self):
        return sorted(d for d, s in self.cal.items() if s == "open"
                      and os.path.exists(os.path.join(self.daily, f"{d}.json")))


def collect_day(store, date: dt.date, today: dt.date, fetcher=None, log=print):
    """抓取單日並記錄狀態。回傳狀態字串。"""
    iso = date.isoformat()
    if date.weekday() >= 5:
        store.cal.setdefault(iso, "closed")
        return "closed"
    ymd = date.strftime("%Y%m%d")
    status, stocks = "bad", {}
    for url in (MI_INDEX, MI_INDEX_OLD):
        try:
            status, stocks = parse_mi_index(http_json(url.format(d=ymd), fetcher))
            if status in ("open", "closed"):
                break
        except Exception as e:  # noqa
            log(f"  {iso} {url.split('/')[-1][:20]}… 失敗：{e}")
    if status == "open":
        store.put_day(iso, stocks, "MI_INDEX")
        log(f"  {iso} 已存 {len(stocks)} 檔")
        return "open"
    if date == today:
        # 當日查無資料：可能是休市，也可能 TWSE 尚未公布 → 嘗試 OpenAPI 備援
        try:
            d2, s2 = parse_openapi_all(http_json(OPENAPI_ALL, fetcher))
            if d2 == iso and s2:
                store.put_day(iso, s2, "STOCK_DAY_ALL")
                log(f"  {iso} 由 OpenAPI 備援取得 {len(s2)} 檔")
                return "open"
        except Exception as e:  # noqa
            log(f"  OpenAPI 備援失敗：{e}")
        log(f"  {iso} 今日尚無收盤資料（休市或尚未公布），本次不記錄")
        return "pending"
    store.cal[iso] = "closed" if status == "closed" else "error"
    log(f"  {iso} {'休市' if status == 'closed' else '抓取失敗（下次重試）'}")
    return store.cal[iso]


def sync(store, today: dt.date, min_open_days=230, max_requests=450, fetcher=None, log=print):
    """補齊資料：今天、以及往回到「近 min_open_days 個交易日」窗口內所有未知或失敗（error）的日期。"""
    requests = 0
    if store.cal.get(today.isoformat()) != "open":
        collect_day(store, today, today, fetcher, log)
        requests += 1
    d = today - dt.timedelta(days=1)
    while requests < max_requests and (today - d).days <= 800:
        iso = d.isoformat()
        if store.cal.get(iso) not in ("open", "closed", "pruned"):
            collect_day(store, d, today, fetcher, log)
            requests += d.weekday() < 5
        if sum(1 for k in store.open_days() if k >= iso) >= min_open_days:
            break
        d -= dt.timedelta(days=1)
    store.save_cal()
    return requests

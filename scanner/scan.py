#!/usr/bin/env python3
"""每日全市場掃描：收集 TWSE 收盤行情 → 依 Volume Breakout V1 規則找出 BUY / WATCH。

用法：
  python scanner/scan.py                 # 補齊資料並掃描最新交易日
  python scanner/scan.py --no-fetch      # 只用已存資料掃描
  python scanner/scan.py --date 2026-10-28   # 掃描指定日期（需已有資料）
輸出：site/data/latest.json、site/data/scans/<日期>.json、site/data/index.json
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import strategy as S  # noqa: E402  與 APP 相同的 V1 規則模組
import twse_daily as T  # noqa: E402

WINDOW = 260          # 每檔最多使用最近 260 個交易日
SCAN_KEEP = 180       # 保留最近 180 份掃描結果
KEEP_DAYS = 300       # 保留最近 300 個交易日的原始行情


def fin(*xs):
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


def indicators_at(rows, p):
    """只計算最後一日 T 的指標；公式與 strategy.compute_indicators 完全相同。"""
    n = len(rows)
    i = n - 1
    C = [r["close"] for r in rows]
    H = [r["high"] for r in rows]
    L = [r["low"] for r in rows]
    V = [r["volume"] for r in rows]

    def sma(arr, k):
        return sum(arr[i - k + 1:i + 1]) / k if i - k + 1 >= 0 else None

    lb, ap, tm = p["breakout_lookback"], p["atr_period"], p["trend_ma"]
    ma20, ma50, ma200, mt = sma(C, 20), sma(C, 50), sma(C, 200), sma(C, tm)
    prev_high = max(H[i - lb:i]) if i >= lb else None
    vol_ma20 = sum(V[i - 20:i]) / 20 if i >= 20 else None
    atr = None
    if i >= ap:
        trs = [max(H[k] - L[k], abs(H[k] - C[k - 1]), abs(L[k] - C[k - 1])) for k in range(i - ap + 1, i + 1)]
        atr = sum(trs) / ap
    rvol = V[i] / vol_ma20 if fin(vol_ma20) and vol_ma20 > 0 else None
    ma20_dist = (C[i] - ma20) / ma20 if fin(ma20) and ma20 > 0 else None
    return dict(ma20=ma20, ma50=ma50, ma200=ma200, ma_trend=mt, prev_high=prev_high, vol_ma20=vol_ma20,
                rvol=rvol, atr=atr, ma20_dist=ma20_dist)


def kind(code):
    if code.startswith("00"):
        return "ETF"
    if len(code) == 4 and code.isdigit():
        return "股票"
    return "其他"


def scan(store, date=None, p=None, log=print):
    p = p or S.params_with_defaults()
    days = store.open_days()
    if date:
        days = [d for d in days if d <= date]
    if not days:
        return dict(status="NO_DATA", message="尚無任何收盤資料。")
    latest = days[-1]
    window = days[-WINDOW:]
    # 缺口檢查：窗口內每個平日都必須是 open 或 closed
    d0 = dt.date.fromisoformat(window[0])
    d1 = dt.date.fromisoformat(latest)
    gaps = []
    d = d0
    while d <= d1:
        if d.weekday() < 5 and store.cal.get(d.isoformat()) not in ("open", "closed"):
            gaps.append(d.isoformat())
        d += dt.timedelta(days=1)
    base = dict(date=latest, params=p, version=S.version_label(p)[0],
                generated_at=T.now_tw().strftime("%Y-%m-%d %H:%M:%S (UTC+8)"),
                source="TWSE 每日收盤行情（全部，不含權證、牛熊證）MI_INDEX",
                window_days=len(window), window_start=window[0], disclaimer=S.DISCLAIMER)
    if gaps:
        base.update(status="INCOMPLETE", gaps=gaps,
                    message=f"資料窗口內有 {len(gaps)} 個交易日抓取失敗（{', '.join(gaps[:5])}…），"
                            "依規則 No Reliable Data → No Reliable Signal，本次不發布訊號。下次執行會自動重試。")
        return base

    series, names = {}, {}
    for d in window:
        for code, (name, o, h, l, c, v) in store.load_day(d).items():
            series.setdefault(code, []).append(dict(date=d, open=o, high=h, low=l, close=c, volume=v))
            names[code] = name
    last_idx = {d: i for i, d in enumerate(window)}
    buys, watches = [], []
    counts = dict(scanned=0, insufficient=0, BUY=0, WATCH=0, WAIT=0)
    for code, rows in series.items():
        if rows[-1]["date"] != latest:
            continue  # 當日無成交
        counts["scanned"] += 1
        ind = indicators_at(rows, p)
        if S.missing_required(ind):
            counts["insufficient"] += 1
            continue
        row = rows[-1]
        sig, buy, watch, dist = S.entry_eval(row, ind, p)
        counts[sig] += 1
        if sig == "WAIT":
            continue
        # 近 25 個市場交易日中，此股缺席（停牌/無成交）的天數
        present = {r["date"] for r in rows[-25:]}
        absent = sum(1 for d in window[-25:] if d not in present)
        risk, flags = S.risk_level(sig, row, ind, p, dict(recent_invalid=absent))
        prev_close = rows[-2]["close"] if len(rows) > 1 else None
        m = p["stop_atr_mult"]
        e = dict(code=code, name=names[code], kind=kind(code), signal=sig, risk=risk, flags=flags,
                 close=row["close"], open=row["open"], high=row["high"], low=row["low"],
                 chg_pct=(row["close"] / prev_close - 1) if prev_close else None,
                 volume_lots=round(row["volume"] / 1000), vol_ma20_lots=round(ind["vol_ma20"] / 1000),
                 rvol=ind["rvol"], prev_high=ind["prev_high"], dist=dist, ma20=ind["ma20"], ma50=ind["ma50"],
                 ma200=ind["ma200"], ma20_dist=ind["ma20_dist"], atr=ind["atr"], valid_days=len(rows),
                 conditions=[dict(name=c["name"], ok=c["ok"], actual=c["actual"]) for c in (buy if sig == "BUY" else watch)])
        if sig == "BUY":
            e.update(breakout_level=ind["prev_high"], entry_reference=row["close"],
                     initial_stop=row["close"] - m * ind["atr"], risk_pct=m * ind["atr"] / row["close"])
            buys.append(e)
        else:
            e.update(need_close=ind["prev_high"], need_gain=(ind["prev_high"] / row["close"] - 1),
                     need_volume_lots=round(ind["vol_ma20"] * p["buy_rvol"] / 1000))
            watches.append(e)
    buys.sort(key=lambda x: -x["rvol"])
    watches.sort(key=lambda x: x["dist"])
    base.update(status="OK", counts=counts, buy=buys, watch=watches)
    return base


def write_outputs(result, site_dir):
    data_dir = os.path.join(site_dir, "data")
    scans = os.path.join(data_dir, "scans")
    os.makedirs(scans, exist_ok=True)
    js = lambda o: json.dumps(S.safe_json(o), ensure_ascii=False, separators=(",", ":"))  # noqa
    with open(os.path.join(data_dir, "latest.json"), "w", encoding="utf-8") as f:
        f.write(js(result))
    if result.get("status") == "OK":
        with open(os.path.join(scans, f"{result['date']}.json"), "w", encoding="utf-8") as f:
            f.write(js(result))
    files = sorted((x[:-5] for x in os.listdir(scans) if x.endswith(".json")), reverse=True)
    for old in files[SCAN_KEEP:]:
        os.remove(os.path.join(scans, f"{old}.json"))
    summary = []
    for d in files[:SCAN_KEEP]:
        try:
            with open(os.path.join(scans, f"{d}.json"), encoding="utf-8") as fh:
                r = json.load(fh)
            summary.append(dict(date=d, buy=len(r.get("buy", [])), watch=len(r.get("watch", []))))
        except Exception:  # noqa
            pass
    with open(os.path.join(data_dir, "index.json"), "w", encoding="utf-8") as f:
        f.write(js(dict(dates=summary, updated=result.get("generated_at"))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(ROOT, "store"))
    ap.add_argument("--site", default=os.path.join(ROOT, "site"))
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--date")
    ap.add_argument("--min-days", type=int, default=230)
    a = ap.parse_args()
    store = T.Store(a.store)
    today = T.now_tw().date()
    if not a.no_fetch:
        print(f"[收集] 今天 {today}，目標至少 {a.min_days} 個交易日")
        n = T.sync(store, today, min_open_days=a.min_days)
        print(f"[收集] 本次請求 {n} 次，已存 {len(store.open_days())} 個交易日")
    # 只保留最近 KEEP_DAYS 個交易日的原始資料，避免 repo 無限成長
    for d in store.open_days()[:-KEEP_DAYS]:
        try:
            os.remove(os.path.join(store.daily, f"{d}.json"))
        except OSError:
            pass
        store.cal[d] = "pruned"
    store.save_cal()
    res = scan(store, a.date)
    write_outputs(res, a.site)
    if res.get("status") == "OK":
        c = res["counts"]
        print(f"[掃描] {res['date']}：掃描 {c['scanned']} 檔，BUY {c['BUY']}、WATCH {c['WATCH']}、"
              f"WAIT {c['WAIT']}、資料不足 {c['insufficient']}")
    else:
        print(f"[掃描] {res.get('status')}：{res.get('message')}")
        if res.get("status") == "NO_DATA":
            sys.exit(1)


if __name__ == "__main__":
    main()

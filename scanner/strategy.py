"""Volume Breakout Agent V1 — 規則引擎（依使用者 Instructions V1 實作）。

所有移動平均、20D High、Volume MA20 皆以「有效交易日」計算；無效日（無成交、欄位缺漏、
OHLC 不一致）不納入計算、不補值。
"""
from __future__ import annotations

import datetime as dt
import math

V1_PARAMS = {
    "breakout_lookback": 20,     # Previous 20D High
    "buy_rvol": 1.50,
    "watch_rvol": 1.30,
    "watch_distance": 0.03,
    "trend_ma": 50,              # Close > MA50
    "overheat": 0.15,            # MA20 Distance <= 15%
    "atr_period": 14,
    "stop_atr_mult": 2.0,        # Initial Stop / Trailing Stop 倍數
}
PARAM_LABELS = {
    "breakout_lookback": "Price Breakout 回看天數 (Previous N-Day High)",
    "buy_rvol": "BUY RVOL Threshold",
    "watch_rvol": "WATCH RVOL Threshold",
    "watch_distance": "WATCH Distance",
    "trend_ma": "Trend Filter (Close > MA N)",
    "overheat": "Overheated Threshold (MA20 Distance <=)",
    "atr_period": "ATR 期間",
    "stop_atr_mult": "Stop ATR 倍數",
}
DEFAULT_COSTS = {
    "fee_rate": 0.001425,   # 券商手續費（買賣各一次）
    "fee_discount": 1.0,    # 手續費折扣（例：0.28 = 2.8 折）
    "tax_rate": 0.003,      # 證交稅（賣出，一般股票 0.3%）
    "slippage": 0.001,      # 每邊滑價
}
DISCLAIMER = ("本訊號為規則型策略依官方盤後資料計算之結果，僅代表策略條件是否成立，"
              "不代表股價必然上漲或下跌，亦不構成投資建議。請自行評估風險。")


def params_with_defaults(p=None):
    out = dict(V1_PARAMS)
    if p:
        for k, v in p.items():
            if k in out and v is not None and v != "":
                out[k] = type(out[k])(v) if not isinstance(out[k], int) else int(float(v))
    return out


def version_label(p):
    diffs = [k for k in V1_PARAMS if abs(float(p[k]) - float(V1_PARAMS[k])) > 1e-12]
    return ("V1", []) if not diffs else (
        "V1-custom",
        [dict(key=k, label=PARAM_LABELS[k], old=V1_PARAMS[k], new=p[k]) for k in diffs])


def _finite(*xs):
    return all(x is not None and isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


# ---------------------------------------------------------------- indicators
def compute_indicators(rows, p):
    """rows: 只含有效交易日（依日期排序）。回傳與 rows 等長的指標 list。"""
    n = len(rows)
    lb, ap, tm = p["breakout_lookback"], p["atr_period"], p["trend_ma"]
    C = [r["close"] for r in rows]
    H = [r["high"] for r in rows]
    L = [r["low"] for r in rows]
    V = [r["volume"] for r in rows]
    tr = [None] * n
    for i in range(1, n):
        pc = C[i - 1]
        tr[i] = max(H[i] - L[i], abs(H[i] - pc), abs(L[i] - pc))

    def sma(arr, i, k):
        if i - k + 1 < 0:
            return None
        w = arr[i - k + 1:i + 1]
        if any(x is None for x in w):
            return None
        return sum(w) / k

    out = []
    for i in range(n):
        ma20, ma50, ma200 = sma(C, i, 20), sma(C, i, 50), sma(C, i, 200)
        matrend = sma(C, i, tm)
        prev_high = max(H[i - lb:i]) if i >= lb else None           # T-N ~ T-1，不含 T
        vol_ma20 = (sum(V[i - 20:i]) / 20) if i >= 20 else None      # 分析日前 20 個有效交易日
        atr = sma(tr, i, ap) if i >= ap else None
        rvol = (V[i] / vol_ma20) if _finite(vol_ma20) and vol_ma20 > 0 else None
        ma20_dist = ((C[i] - ma20) / ma20) if _finite(ma20) and ma20 > 0 else None
        out.append(dict(ma20=ma20, ma50=ma50, ma200=ma200, ma_trend=matrend,
                        prev_high=prev_high, vol_ma20=vol_ma20, rvol=rvol,
                        atr=atr, ma20_dist=ma20_dist))
    return out


REQUIRED = ["ma20", "ma_trend", "prev_high", "vol_ma20", "rvol", "atr", "ma20_dist"]


def missing_required(ind):
    return [k for k in REQUIRED if not _finite(ind.get(k))]


# ---------------------------------------------------------------- entry rules
def entry_eval(row, ind, p):
    c = row["close"]
    ph, rv, mt, md = ind["prev_high"], ind["rvol"], ind["ma_trend"], ind["ma20_dist"]
    tm = p["trend_ma"]
    dist = (ph - c) / ph
    buy = [
        dict(key="breakout", name="Price Breakout", rule=f"Close > Previous {p['breakout_lookback']}D High",
             ok=c > ph, actual=f"{c:.2f} vs {ph:.2f}"),
        dict(key="rvol_buy", name=f"RVOL >= {p['buy_rvol']:.2f}", rule=f"RVOL >= {p['buy_rvol']:.2f}",
             ok=rv >= p["buy_rvol"], actual=f"{rv:.2f}"),
        dict(key="trend", name=f"Close > MA{tm}", rule=f"Close > MA{tm}", ok=c > mt,
             actual=f"{c:.2f} vs {mt:.2f}"),
        dict(key="overheat", name="Overheated Filter", rule=f"MA20 Distance <= {p['overheat']*100:.0f}%",
             ok=md <= p["overheat"], actual=f"{md*100:.2f}%"),
    ]
    watch = [
        dict(key="below", name="尚未突破", rule=f"Close <= Previous {p['breakout_lookback']}D High",
             ok=c <= ph, actual=f"{c:.2f} vs {ph:.2f}"),
        dict(key="dist", name=f"Distance to Breakout <= {p['watch_distance']*100:.0f}%",
             rule=f"(High20 - Close)/High20 <= {p['watch_distance']*100:.0f}%",
             ok=dist <= p["watch_distance"], actual=f"{dist*100:.2f}%"),
        dict(key="rvol_watch", name=f"RVOL >= {p['watch_rvol']:.2f}", rule=f"RVOL >= {p['watch_rvol']:.2f}",
             ok=rv >= p["watch_rvol"], actual=f"{rv:.2f}"),
        dict(key="trend", name=f"Close > MA{tm}", rule=f"Close > MA{tm}", ok=c > mt,
             actual=f"{c:.2f} vs {mt:.2f}"),
    ]
    if all(x["ok"] for x in buy):
        sig = "BUY"
    elif all(x["ok"] for x in watch):
        sig = "WATCH"
    else:
        sig = "WAIT"
    return sig, buy, watch, dist


# ---------------------------------------------------------------- position rules
def trailing_path(rows, ind, e, t, entry_price, p, prev_trailing_override=None):
    """回傳 T 日的 Previous / Calculated / Final Trailing Stop 與期間是否曾觸發出場。"""
    m = p["stop_atr_mult"]
    init_stop = entry_price - m * ind[e]["atr"]
    stop = init_stop
    highest = -math.inf
    earlier_exit = None
    for k in range(e, t):
        highest = max(highest, rows[k]["close"])
        if not _finite(ind[k]["atr"]):
            return None
        calc = highest - m * ind[k]["atr"]
        stop = max(stop, calc)
    prev = prev_trailing_override if _finite(prev_trailing_override) else stop
    highest_t = max(highest, rows[t]["close"])
    calc_t = highest_t - m * ind[t]["atr"]
    final = max(prev, calc_t)
    return dict(initial_stop=init_stop, previous=prev, calculated=calc_t, final=final,
                highest_close=highest_t, prev_source="使用者提供" if _finite(prev_trailing_override)
                else "由進場日起逐日推算（起點 = Initial Stop）")


def earlier_exit_scan(rows, ind, e, t, entry_price, breakout, p):
    """檢查 e..t-1 期間是否已有收盤觸發 EXIT（提醒用，不改變 T 日判斷）。"""
    m = p["stop_atr_mult"]
    stop = entry_price - m * ind[e]["atr"]
    highest = -math.inf
    for k in range(e, t):
        highest = max(highest, rows[k]["close"])
        stop = max(stop, highest - m * ind[k]["atr"])
        c = rows[k]["close"]
        if c < breakout or c < stop:
            return rows[k]["date"]
    return None


# ---------------------------------------------------------------- risk
def risk_level(signal, row, ind, p, ctx):
    flags = []
    if ctx.get("recent_invalid"):
        flags.append(f"近 20 日內有 {ctx['recent_invalid']} 個無效交易日（資料異常可能影響判斷）")
    ph = ind.get("prev_high")
    if _finite(ph, ind.get("rvol")) and ind["rvol"] >= 2.0 and row["high"] > ph and row["close"] <= ph:
        flags.append("劇烈放量盤中突破但收盤收回（沖高回落）")
    if signal == "EXIT":
        return "HIGH", flags
    if signal == "HOLD":
        cushion = row["close"] - max(ctx["final_stop"], ctx["breakout"])
        atr = ind["atr"]
        if cushion <= 0.5 * atr:
            flags.append(f"距風險邊界僅 {cushion:.2f}（<= 0.5 × ATR14）")
            return "HIGH", flags
        if flags:
            return "HIGH", flags
        return ("LOW" if cushion >= 2 * atr else "MEDIUM"), flags
    if flags:
        return "HIGH", flags
    return "MEDIUM", flags


# ---------------------------------------------------------------- analysis
def _locate(all_rows, date_str, now):
    """回傳 (index in all_rows or None, status, note)。"""
    today = now.date().isoformat()
    if date_str > today:
        return None, "INVALID", f"分析日期 {date_str} 晚於今天，無法分析未來日期。"
    exact = [i for i, r in enumerate(all_rows) if r["date"] == date_str]
    if exact:
        return exact[0], None, None
    if date_str == today and (not all_rows or all_rows[-1]["date"] < today):
        wd = now.weekday()
        if wd < 5:
            hm = now.hour * 60 + now.minute
            when = "尚未收盤" if hm < 13 * 60 + 30 else "TWSE 盤後資料尚未公布"
            return None, "INTRADAY", f"今日（{today}）{when}，PENDING CLOSE。可改分析最近一個已收盤交易日。"
    prior = [i for i, r in enumerate(all_rows) if r["date"] < date_str]
    if not prior:
        return None, "INSUFFICIENT", f"{date_str} 之前查無任何 TWSE 資料。"
    i = prior[-1]
    return i, None, f"{date_str} 無交易資料（非交易日或停止交易），改用最近交易日 {all_rows[i]['date']}。"


def analyze(history, date_str, p, now, position=None):
    all_rows = history["rows"]
    res = dict(stock=history["stock"], name=history.get("name") or "", requested_date=date_str,
               params=p, version=version_label(p)[0], disclaimer=DISCLAIMER, notes=list(history.get("notes", [])))
    if not all_rows:
        res.update(data_status="INSUFFICIENT", signal=None, risk="HIGH",
                   message="找不到有效 OHLCV（請確認為 TWSE 上市股票代號；上櫃股票不在 TWSE 資料範圍）。")
        return res
    idx, status, note = _locate(all_rows, date_str, now)
    if note:
        res["notes"].append(note)
    if status:
        res.update(data_status=status, signal=None, risk="HIGH", message=note)
        if status == "INTRADAY":
            res["last_final_date"] = all_rows[-1]["date"]
        return res
    row = all_rows[idx]
    res["analysis_date"] = row["date"]
    if not row["valid"]:
        res.update(data_status="INVALID", signal=None, risk="HIGH",
                   message=f"{row['date']} 資料無法可靠使用：{row['issue']}。No Reliable Data -> No Reliable Signal。")
        res["bar"] = row
        return res
    valid = [r for r in all_rows if r["valid"]]
    t = next(i for i, r in enumerate(valid) if r["date"] == row["date"])
    ind_all = compute_indicators(valid[:t + 1], p)  # 只用 T 日（含）以前資料
    ind = ind_all[t]
    res["bar"] = row
    res["indicators"] = ind
    res["valid_days_used"] = t + 1
    miss = missing_required(ind)
    calc = {k: _finite(ind[k]) for k in ind}
    res["indicator_availability"] = calc
    if not _finite(ind["ma200"]):
        res["notes"].append("MA200 資料不足（需 200 個有效交易日），僅為參考指標，不阻止 BUY。")
    if miss:
        res.update(data_status="INSUFFICIENT", signal=None, risk="HIGH",
                   message=f"必要指標無法計算：{', '.join(miss)}（目前僅 {t+1} 個有效交易日）。停止正式 Signal。")
        return res
    res["data_status"] = "FINAL"
    recent_invalid = sum(1 for r in all_rows[max(0, idx - 25):idx + 1] if not r["valid"])
    ctx = dict(recent_invalid=recent_invalid)

    # chart series（只到 T 日，避免畫面呈現未來資料）
    start_chart = max(0, t - 180)
    res["series"] = [dict(r, **{k: ind_all[i][k] for k in ("ma20", "ma50", "ma200", "prev_high")})
                     for i, r in enumerate(valid[:t + 1]) if i >= start_chart]

    if position and position.get("open"):
        return _position_analysis(res, valid, ind_all, t, p, position, ctx)

    res["position_status"] = "Assumed NONE" if not position else "NONE"
    sig, buy, watch, dist = entry_eval(row, ind, p)
    res.update(signal=sig, buy_conditions=buy, watch_conditions=watch, distance_to_breakout=dist)
    risk, flags = risk_level(sig, row, ind, p, ctx)
    res.update(risk=risk, risk_flags=flags)
    if ind["ma20_dist"] > p["overheat"]:
        res["overheated"] = True
    if sig == "BUY":
        m = p["stop_atr_mult"]
        res["levels"] = dict(breakout_level=ind["prev_high"], entry_reference=row["close"],
                             initial_stop=row["close"] - m * ind["atr"], atr14=ind["atr"],
                             risk_per_share=m * ind["atr"],
                             risk_pct=m * ind["atr"] / row["close"])
    res["reasons"], res["next_watch"], res["conclusion"] = _explain_entry(sig, row, ind, p, buy, watch, dist)
    return res


def _position_analysis(res, rows, ind, t, p, pos, ctx):
    res["position_status"] = "OPEN"
    need = []
    ep, bl, ed = pos.get("entry_price"), pos.get("breakout_level"), pos.get("entry_date")
    if not _finite(ep):
        need.append("Entry Price")
    if not _finite(bl):
        need.append("Breakout Level")
    if not ed:
        need.append("Entry Date")
    e = next((i for i, r in enumerate(rows) if r["date"] == ed), None) if ed else None
    if ed and e is None:
        need.append(f"Entry Date {ed} 不是有效交易日（或不在資料範圍內）")
    elif e is not None and e > t:
        need.append("Entry Date 晚於分析日")
    elif e is not None and not _finite(ind[e]["atr"]):
        need.append("進場日 ATR14 無法計算")
    if need:
        res.update(signal="N/A", risk="HIGH",
                   message="持倉資訊不足，Position Signal = N/A（不猜測）：" + "、".join(need))
        return res
    prev_override = pos.get("prev_trailing")
    tp = trailing_path(rows, ind, e, t, ep, p, prev_override)
    if tp is None:
        res.update(signal="N/A", risk="HIGH", message="持有期間 ATR14 有缺值，無法計算 Trailing Stop。")
        return res
    row, i = rows[t], ind[t]
    c = row["close"]
    reasons = []
    if c < bl:
        reasons.append("Failed Breakout")
    if c < tp["final"]:
        reasons.append("ATR Trailing Stop")
    sig = "EXIT" if reasons else "HOLD"
    ctx.update(final_stop=tp["final"], breakout=bl)
    risk, flags = risk_level(sig, row, i, p, ctx)
    earlier = earlier_exit_scan(rows, ind, e, t, ep, bl, p) if prev_override in (None, "") else None
    if earlier:
        res["notes"].append(f"注意：持有期間 {earlier} 收盤已曾觸發 EXIT 條件。")
    res.update(signal=sig, risk=risk, risk_flags=flags, exit_reasons=reasons,
               position=dict(entry_date=ed, entry_price=ep, breakout_level=bl, current_close=c,
                             atr14_at_entry=ind[e]["atr"], atr14=i["atr"],
                             holding_days=t - e, unrealized=(c - ep) / ep, **tp),
               exit_conditions=[
                   dict(name="Failed Breakout 未觸發", rule="Close >= Breakout Level", ok=c >= bl,
                        actual=f"{c:.2f} vs {bl:.2f}"),
                   dict(name="Trailing Stop 未觸發", rule="Close >= Final Trailing Stop", ok=c >= tp["final"],
                        actual=f"{c:.2f} vs {tp['final']:.2f}"),
               ])
    res["reasons"], res["next_watch"], res["conclusion"] = _explain_position(sig, c, bl, tp, i, reasons, ep)
    return res


def _explain_entry(sig, row, ind, p, buy, watch, dist):
    c, ph, rv = row["close"], ind["prev_high"], ind["rvol"]
    tm = p["trend_ma"]
    gap_up = (ph - c) / ph
    r = []
    r.append(f"價格：收盤 {c:.2f}，Previous {p['breakout_lookback']}D High {ph:.2f}，"
             + (f"已突破 {(c/ph-1)*100:.2f}%。" if c > ph else f"距突破尚差 {gap_up*100:.2f}%。"))
    r.append(f"成交量：RVOL {rv:.2f}（BUY 門檻 {p['buy_rvol']:.2f}／WATCH 門檻 {p['watch_rvol']:.2f}），"
             f"當日量 {row['volume']/1000:,.0f} 張 vs 前 20 日均量 {ind['vol_ma20']/1000:,.0f} 張。")
    r.append(f"趨勢：Close {'>' if c > ind['ma_trend'] else '<='} MA{tm}（{ind['ma_trend']:.2f}）"
             + (f"；MA200 {ind['ma200']:.2f}（參考）。" if _finite(ind['ma200']) else "；MA200 不足（參考指標）。"))
    r.append(f"過熱：MA20 Distance {ind['ma20_dist']*100:.2f}%（上限 {p['overheat']*100:.0f}%）"
             + ("，OVERHEATED，不得產生 BUY。" if ind["ma20_dist"] > p["overheat"] else "，未過熱。"))
    r.append(f"波動：ATR14 {ind['atr']:.2f}（約收盤 {ind['atr']/c*100:.2f}%），"
             f"{p['stop_atr_mult']:.0f}×ATR 停損距離 {p['stop_atr_mult']*ind['atr']:.2f}。")
    if sig == "BUY":
        nxt = (f"下一交易日觀察是否站穩 Breakout Level {ph:.2f}；收盤跌破即為 Failed Breakout。"
               f"Initial Stop {c - p['stop_atr_mult']*ind['atr']:.2f}。")
        concl = "價格突破、量能確認、趨勢與過熱四項條件全數通過，策略條件成立（BUY）。"
    elif sig == "WATCH":
        nxt = (f"正式 BUY 仍需要：Close > {ph:.2f}（再漲 {gap_up*100:.2f}% 以上）且 RVOL >= {p['buy_rvol']:.2f}"
               f"（以前 20 日均量估算約需 {ind['vol_ma20']*p['buy_rvol']/1000:,.0f} 張），並維持 MA20 Distance <= {p['overheat']*100:.0f}%。")
        concl = "接近突破且量能升溫，但價格尚未突破，屬觀察名單（WATCH），不代表提前進場。"
    else:
        fails = [x["name"] for x in buy if not x["ok"]]
        wfails = [x["name"] for x in watch if not x["ok"]]
        nxt = (f"BUY 未通過：{('、'.join(fails)) or '—'}；WATCH 未通過：{('、'.join(wfails)) or '—'}。"
               f"觀察 RVOL 是否升至 {p['watch_rvol']:.2f}/{p['buy_rvol']:.2f}"
               f"（距 WATCH 門檻 {max(0, p['watch_rvol']-rv):.2f}、距 BUY 門檻 {max(0, p['buy_rvol']-rv):.2f}）"
               + (f"，以及收盤能否突破 {ph:.2f}。" if c <= ph else "。"))
        concl = "BUY 與 WATCH 條件均未完整成立，依規則維持 WAIT。"
    return r[:5], nxt, concl


def _explain_position(sig, c, bl, tp, ind, reasons, ep):
    fs = tp["final"]
    above_bl = f"高於 {((c - bl) / bl) * 100:.2f}%"
    above_fs = f"高於 {c - fs:.2f}"
    r = [
        f"Entry Price {ep:.2f}，Current Close {c:.2f}，未實現 {((c-ep)/ep)*100:+.2f}%（未扣成本）。",
        f"Breakout Level {bl:.2f}：收盤{'跌破 → Failed Breakout' if c < bl else above_bl}。",
        f"Highest Close Since Entry {tp['highest_close']:.2f}，Current ATR14 {ind['atr']:.2f}，"
        f"Calculated Trailing Stop {tp['calculated']:.2f}。",
        f"Final Trailing Stop = max(Previous {tp['previous']:.2f}, Calculated {tp['calculated']:.2f}) = {tp['final']:.2f}"
        f"；收盤{'跌破 → ATR Trailing Stop' if c < fs else above_fs}。",
        "Trailing Stop 只能維持或提高；EXIT 風險控制優先於 RVOL、均線或反彈預期。",
    ]
    if sig == "EXIT":
        nxt = "出場條件已成立。若欲重新進場，需重新等待完整 BUY 條件。"
        concl = f"觸發 {' + '.join(reasons)}，依規則 EXIT。"
    else:
        lvl = max(bl, tp["final"])
        nxt = (f"下一交易日關注收盤是否守住 {lvl:.2f}（max(Breakout Level, Final Trailing Stop)）；"
               f"Trailing Stop 將隨新高收盤上移。")
        concl = "未觸發任何出場條件，依規則 HOLD。"
    return r, nxt, concl


# ---------------------------------------------------------------- backtest
def backtest(history, start, end, p, costs):
    all_rows = history["rows"]
    valid = [r for r in all_rows if r["valid"]]
    ind = compute_indicators(valid, p)
    pos_in_period = [i for i, r in enumerate(valid) if start <= r["date"] <= end]
    period_all = [r for r in all_rows if start <= r["date"] <= end]
    skipped = [dict(date=r["date"], issue=r["issue"]) for r in period_all if not r["valid"]]
    fee = costs["fee_rate"] * costs["fee_discount"]
    tax, slip = costs["tax_rate"], costs["slippage"]
    m = p["stop_atr_mult"]

    res = dict(stock=history["stock"], name=history.get("name") or "", start=start, end=end,
               params=p, version=version_label(p)[0], param_diff=version_label(p)[1], costs=costs,
               execution="T 日收盤後確認訊號，下一有效交易日開盤執行",
               disclosure=[
                   f"手續費 {fee*100:.4f}%（每邊，{costs['fee_rate']*100:.4f}% × 折扣 {costs['fee_discount']}；未計最低 20 元）",
                   f"證交稅 {tax*100:.2f}%（賣出）", f"滑價 {slip*100:.2f}%（每邊）",
                   "執行價格：訊號次一有效交易日開盤價（含滑價）",
                   "資料：TWSE 官方未還原（原始）價格；除權息缺口可能影響突破與 ATR 判斷",
                   "缺漏資料：無效交易日不插值、不 forward/backward fill，直接 skip 並揭露",
                   "部位：每筆交易全額投入、不加碼、不放空；期末未平倉以最後收盤價（扣成本）結算",
               ])
    if not pos_in_period:
        res.update(status="INSUFFICIENT", message="回測期間內沒有有效交易日資料。")
        return res
    trades, equity_curve = [], []
    equity, shares_val = 1.0, None
    pending_entry = pending_exit = None
    pos = None
    valid_signal_days = 0
    signal_counts = dict(BUY=0, WATCH=0, WAIT=0)
    for t in pos_in_period:
        r = valid[t]
        # 1) 開盤執行前一日訊號
        if pending_exit and pos:
            px = r["open"] * (1 - slip)
            proceeds = px * (1 - fee - tax)
            ret = proceeds / pos["cost"] - 1
            highs = [valid[k]["high"] for k in range(pos["idx"], t)] + [r["open"]]
            lows = [valid[k]["low"] for k in range(pos["idx"], t)] + [r["open"]]
            equity = pos["equity_in"] * (1 + ret)
            trades.append(dict(entry_date=pos["date"], entry_price=pos["price"], breakout_level=pos["bl"],
                               initial_stop=pos["init_stop"], signal_date=pos["signal_date"],
                               exit_signal_date=pending_exit["date"], exit_date=r["date"], exit_price=px,
                               holding_days=t - pos["idx"], return_pct=ret,
                               mfe=max(highs) / pos["price"] - 1, mae=min(lows) / pos["price"] - 1,
                               exit_reason=" + ".join(pending_exit["reasons"])))
            pos, pending_exit = None, None
        if pending_entry and pos is None:
            px = r["open"] * (1 + slip)
            cost = px * (1 + fee)
            pos = dict(idx=t, date=r["date"], price=px, cost=cost, bl=pending_entry["bl"],
                       init_stop=px - m * pending_entry["atr"], stop=px - m * pending_entry["atr"],
                       highest=-math.inf, equity_in=equity, signal_date=pending_entry["date"],
                       sig_idx=pending_entry["idx"])
            pending_entry = None
        # 2) 收盤評估
        it = ind[t]
        ok = not missing_required(it)
        if ok:
            valid_signal_days += 1
        if pos:
            pos["highest"] = max(pos["highest"], r["close"])
            if _finite(it["atr"]):
                pos["stop"] = max(pos["stop"], pos["highest"] - m * it["atr"])
            reasons = []
            if r["close"] < pos["bl"]:
                reasons.append("Failed Breakout")
            if r["close"] < pos["stop"]:
                reasons.append("ATR Trailing Stop")
            if reasons:
                pending_exit = dict(date=r["date"], reasons=reasons)
            mark = pos["equity_in"] * (r["close"] / pos["cost"])
            equity_curve.append(dict(date=r["date"], equity=mark, in_pos=True))
        else:
            if ok:
                sig, *_ = entry_eval(r, it, p)
                signal_counts[sig] += 1
                if sig == "BUY":
                    pending_entry = dict(date=r["date"], idx=t, bl=it["prev_high"], atr=it["atr"])
            equity_curve.append(dict(date=r["date"], equity=equity, in_pos=False))
    open_note = None
    if pos:
        last = valid[pos_in_period[-1]]
        px = last["close"] * (1 - slip)
        ret = px * (1 - fee - tax) / pos["cost"] - 1
        highs = [valid[k]["high"] for k in range(pos["idx"], pos_in_period[-1] + 1)]
        lows = [valid[k]["low"] for k in range(pos["idx"], pos_in_period[-1] + 1)]
        equity = pos["equity_in"] * (1 + ret)
        equity_curve[-1]["equity"] = equity
        trades.append(dict(entry_date=pos["date"], entry_price=pos["price"], breakout_level=pos["bl"],
                           initial_stop=pos["init_stop"], signal_date=pos["signal_date"],
                           exit_signal_date=None, exit_date=last["date"], exit_price=px,
                           holding_days=pos_in_period[-1] - pos["idx"], return_pct=ret,
                           mfe=max(highs) / pos["price"] - 1, mae=min(lows) / pos["price"] - 1,
                           exit_reason="End of Period（期末結算，未觸發出場）"))
    if pending_entry:
        open_note = f"{pending_entry['date']} 產生 BUY，但期末前無下一交易日可執行。"

    # Look-Ahead Bias 自我檢查：以「只截到訊號日」的資料重算，訊號與數值必須一致
    lookahead_ok = True
    for tr in trades:
        si = next(i for i, r in enumerate(valid) if r["date"] == tr["signal_date"])
        trunc = compute_indicators(valid[:si + 1], p)[si]
        sig, *_ = entry_eval(valid[si], trunc, p)
        if sig != "BUY" or abs(trunc["prev_high"] - tr["breakout_level"]) > 1e-9:
            lookahead_ok = False
        if tr["entry_date"] <= tr["signal_date"]:
            lookahead_ok = False
    res["lookahead_check"] = "PASS" if lookahead_ok else "FAIL"
    if not lookahead_ok:
        res.update(status="INVALID", message="偵測到 Look-Ahead Bias，Backtest Status = INVALID，不發布績效。")
        return res

    # 統計
    rets = [x["return_pct"] for x in trades]
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    peak, mdd = -math.inf, 0.0
    for pt in equity_curve:
        peak = max(peak, pt["equity"])
        mdd = min(mdd, pt["equity"] / peak - 1)
    daily = [equity_curve[i]["equity"] / equity_curve[i - 1]["equity"] - 1 for i in range(1, len(equity_curve))]
    sharpe = None
    if len(daily) > 2:
        mu = sum(daily) / len(daily)
        sd = math.sqrt(sum((x - mu) ** 2 for x in daily) / (len(daily) - 1))
        sharpe = (mu / sd * math.sqrt(252)) if sd > 0 else None
    gp, gl = sum(wins), -sum(losses)
    first, last = valid[pos_in_period[0]], valid[pos_in_period[-1]]
    res.update(
        status="VALID",
        stats=dict(
            backtest_period=f"{first['date']} ~ {last['date']}",
            total_trading_days=len(period_all), valid_signal_days=valid_signal_days,
            skipped_trading_days=len(skipped), total_trades=len(trades),
            winning_trades=len(wins), losing_trades=len(losses),
            win_rate=(len(wins) / len(trades)) if trades else None,
            avg_return=(sum(rets) / len(rets)) if rets else None,
            cumulative_return=equity - 1, max_drawdown=mdd,
            profit_factor=(gp / gl) if gl > 0 else (None if not wins else math.inf),
            sharpe=sharpe,
            buy_hold=last["close"] / first["open"] - 1,
            exposure=sum(1 for x in equity_curve if x["in_pos"]) / len(equity_curve),
        ),
        signal_counts=signal_counts, trades=trades, skipped=skipped, equity_curve=equity_curve,
        open_note=open_note,
        sample_warning=("交易次數少於 10 筆，統計結果樣本數不足，請謹慎解讀。" if len(trades) < 10 else None),
        series=[dict(r, **{k: ind[i][k] for k in ("ma20", "ma50", "ma200", "prev_high")})
                for i, r in enumerate(valid) if start <= r["date"] <= end],
    )
    return res


def safe_json(o):
    """將 inf/NaN 轉為 None，避免 JSON 序列化錯誤（顯示端另行標示）。"""
    if isinstance(o, float):
        if math.isinf(o):
            return "inf" if o > 0 else "-inf"
        return None if math.isnan(o) else o
    if isinstance(o, dict):
        return {k: safe_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [safe_json(v) for v in o]
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    return o

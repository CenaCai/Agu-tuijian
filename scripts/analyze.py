#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析层：题材词频 / 行业轮动 / 龙虎榜聚合 / 候选股打分 → report_data.json"""
import json, os, math, time, datetime
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

D = "data"
# 交易日从数据文件读取，避免硬编码（支持任意交易日复用）
TRADE_DATE = json.load(open(f"{D}/stage1.json")).get("trade_date", "")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

def clamp(v, lo, hi): return max(lo, min(hi, v))

# ── 交易日历工具（用于推导建议买卖日期）──
def _next_trading_day(d):
    while d.weekday() >= 5:          # 跳过周末
        d += datetime.timedelta(days=1)
    return d

def _add_trading_days(d, n):
    """在 d 之后推进 n 个交易日（跳过周末）"""
    cnt = 0
    while cnt < n:
        d += datetime.timedelta(days=1)
        if d.weekday() < 5:
            cnt += 1
    return d

# 四周期 → 建议持仓交易日（作为"建议持仓时间"的锚）
HOLD_TD = {"超短期": 3, "短期": 10, "中期": 40, "长期": 120}

# ══════════════ 0. 载入原始数据 ══════════════
s1 = json.load(open(f"{D}/stage1.json"))
tech = json.load(open(f"{D}/tech.json"))
lhb = s1["lhb"]; ths = s1["ths_hot"]
board_hist = s1.get("board_hist", {}) or {}
board_flow = s1.get("board_flow", {}) or {}
board_names = {b["code"]: b["name"] for b in s1["board_list"]}

ind_map = {}
if os.path.exists(f"{D}/allstocks_industry.json"):
    for it in json.load(open(f"{D}/allstocks_industry.json")):
        if it.get("f12"):
            ind_map[it["f12"]] = it.get("f100") or ""

board_stats = {}
if os.path.exists(f"{D}/board_stats.json"):
    board_stats = json.load(open(f"{D}/board_stats.json"))

# ══════════════ 1. 同花顺题材词频 ══════════════
tag_stocks = defaultdict(list)
for r in ths:
    for t in str(r.get("reason") or "").split("+"):
        t = t.strip()
        if t:
            tag_stocks[t].append({"code": r["code"], "name": r["name"],
                                  "zhangfu": float(r.get("zhangfu") or 0)})
theme_rank = sorted(tag_stocks.items(), key=lambda kv: (-len(kv[1]), kv[0]))
themes = [{"tag": k, "count": len(v),
           "stocks": sorted(v, key=lambda x: -x["zhangfu"])} for k, v in theme_rank]
theme_freq = {t["tag"]: t["count"] for t in themes}
total_tags = sum(t["count"] for t in themes)

# ══════════════ 2. 龙虎榜聚合 ══════════════
# 同一只股票可能因多条上榜原因出现多次 → 记录级全列 + 股票级汇总
by_stock = defaultdict(lambda: {"records": [], "net_buy": 0.0, "buy": 0.0, "sell": 0.0})
for r in lhb:
    s = by_stock[r["code"]]
    s["records"].append(r)
    s["net_buy"] += r["net_buy"]; s["buy"] += r["buy"]; s["sell"] += r["sell"]
    s.update({k: r[k] for k in ("name", "close", "change_pct", "turnover_pct",
                                "accum_amount", "free_mcap")})
stock_agg = []
for code, v in by_stock.items():
    stock_agg.append({
        "code": code, "name": v["name"], "close": v["close"],
        "change_pct": v["change_pct"], "turnover_pct": v["turnover_pct"],
        "net_buy": v["net_buy"], "buy": v["buy"], "sell": v["sell"],
        "accum_amount": v["accum_amount"], "free_mcap": v["free_mcap"],
        "reasons": [x["reason"] for x in v["records"]],
        "n_rec": len(v["records"]),
    })
stock_agg.sort(key=lambda x: -x["net_buy"])

lhb_total_net = sum(r["net_buy"] for r in lhb)
lhb_total_buy = sum(r["buy"] for r in lhb)
lhb_total_sell = sum(r["sell"] for r in lhb)

# ══════════════ 3. 行业轮动 ══════════════
industries = []
for c, b in board_hist.items():
    st = board_stats.get(c) or {}
    fl = board_flow.get(c) or {}
    industries.append({
        "code": c, "name": b["name"], "change_pct": b["change_pct"],
        "amount": None, "turnover": None, "amplitude": None,
        "up": st.get("up"), "down": st.get("down"), "flat": st.get("flat"),
        "total": st.get("total"), "leader": st.get("leader"),
        "main_net": None, "super_net": None,
    })
industries.sort(key=lambda x: -x["change_pct"])
ind_up = [i for i in industries if i["change_pct"] > 0]
ind_dn = [i for i in industries if i["change_pct"] < 0]
ind_rank_pct = {i["name"]: 1 - n / max(1, len(industries) - 1)
                for n, i in enumerate(industries)}   # 1=最强 0=最弱

# ══════════════ 4. 候选股打分 ══════════════
ths_by_code = {r["code"]: r for r in ths}
max_theme_raw = 1
cand_raw = {}
for s in stock_agg:
    code = s["code"]
    t = ths_by_code.get(code)
    tags = [x.strip() for x in str(t.get("reason") or "").split("+") if x.strip()] if t else []
    raw = sum(theme_freq.get(x, 0) for x in tags)
    cand_raw[code] = (tags, raw)
    max_theme_raw = max(max_theme_raw, raw)
for r in ths:
    if r["code"] not in cand_raw:
        tags = [x.strip() for x in str(r.get("reason") or "").split("+") if x.strip()]
        raw = sum(theme_freq.get(x, 0) for x in tags)
        cand_raw[r["code"]] = (tags, raw)
        max_theme_raw = max(max_theme_raw, raw)

def grade(score):
    if score >= 78: return ("强", "s-a")
    if score >= 64: return ("较强", "s-b")
    if score >= 50: return ("中性", "s-c")
    if score >= 36: return ("偏弱", "s-d")
    return ("回避", "s-e")

candidates = []
pool = {s["code"]: s for s in stock_agg}
for r in ths:
    pool.setdefault(r["code"], {
        "code": r["code"], "name": r["name"], "close": float(r.get("close") or 0),
        "change_pct": float(r.get("zhangfu") or 0),
        "turnover_pct": float(r.get("huanshou") or 0),
        "net_buy": 0.0, "buy": 0.0, "sell": 0.0,
        "accum_amount": float(r.get("chengjiaoe") or 0),
        "free_mcap": 0, "reasons": [], "n_rec": 0})

for code, s in pool.items():
    tk = tech.get(code)
    if not tk:                      # 北交所/次新/可转债：历史不足，不进入推荐池
        continue
    tags, theme_raw = cand_raw.get(code, ([], 0))
    close = tk["last_close"]; atr = tk["atr14"] or max(close * 0.03, 0.01)
    ma5, ma10, ma20, ma60 = tk["ma5"], tk["ma10"], tk["ma20"], tk["ma60"] or tk["ma20"]

    # ── 资金分 0-30：龙虎榜净买入占当日成交额比重 ──
    ratio = (s["net_buy"] / s["accum_amount"]) if s["accum_amount"] else 0
    fund_score = clamp(ratio * 250, -15, 30)

    # ── 题材分 0-25 ──
    theme_score = 25 * (theme_raw / max_theme_raw) if max_theme_raw else 0

    # ── 技术分 0-25 ──
    ts = 0
    if close > ma5: ts += 6
    if close > ma10: ts += 5
    if close > ma20: ts += 5
    if ma60 and close > ma60: ts += 5
    if ma5 and ma10 and ma20 and ma5 > ma10 > ma20: ts += 4
    tech_score = ts

    # ── 换手健康度 0-10 ──
    tr = s["turnover_pct"] or 0
    if 3 <= tr <= 15: turn_score = 10
    elif 15 < tr <= 25: turn_score = 6
    elif tr > 25: turn_score = 2
    elif tr > 0: turn_score = 5
    else: turn_score = 4

    # ── 行业分 0-10 ──
    ind_name = ind_map.get(code, "")
    ipct = ind_rank_pct.get(ind_name)
    ind_score = 10 * ipct if ipct is not None else 5

    total = clamp(fund_score + theme_score + tech_score + turn_score + ind_score, 0, 100)

    # ── 价格建议 ──
    support = max([x for x in [ma5, close - 1.2 * atr] if x], default=close * 0.95)
    buy = round(min(support, close * 0.99), 2)
    stop_raw = min(buy - 1.5 * atr, ma20 if (ma20 and ma20 < buy) else buy * 0.92)
    stop = round(max(stop_raw, buy * 0.85), 2)
    tgt_raw = max(close + 2.5 * atr, (tk["high20"] or close) * 1.02)
    if close >= (tk["high_all"] or close) * 0.999:
        tgt_raw = max(tgt_raw, close * 1.18)
    sell = round(tgt_raw, 2)
    rr = round((sell - buy) / (buy - stop), 2) if buy > stop else None

    # ── 四周期评级 ──
    ultra = clamp(fund_score * 1.5 + theme_score * 0.8 + min(s["change_pct"], 12) * 1.2
                  + (tk["vol_ratio5"] or 1) * 3, 0, 100)
    if tr > 25 and s["change_pct"] > 9: ultra -= 18      # 高位高换手，获利盘重
    if s["net_buy"] < 0: ultra -= 15
    ultra = clamp(ultra, 0, 100)

    short = clamp(35 + (12 if close > ma10 else -10) + (12 if close > ma20 else -10)
                  + clamp((tk["ret5"] or 0) * 0.6, -12, 14)
                  + ind_score * 1.3 + theme_score * 0.5, 0, 100)

    mid = clamp(34 + (16 if (ma60 and close > ma60) else -12)
                + clamp((tk["ret60"] or 0) * 0.28, -15, 20)
                + ind_score * 1.6 + theme_score * 0.45, 0, 100)

    pos_in_range = ((close - (tk["low_all"] or close)) /
                    max(1e-9, (tk["high_all"] or close) - (tk["low_all"] or close)))
    lng = clamp(38 + (14 if (ma60 and ma60 > 0 and close > ma60) else -10)
                + clamp((tk["ret60"] or 0) * 0.18, -12, 16)
                + (8 if pos_in_range < 0.85 else -6) + ind_score * 1.2, 0, 100)

    # ── 建议买卖日期 / 持仓天数 ──
    # 主周期 = 四周期中评级分最高者（置信度最高的持有窗口）
    period_scores = {"超短期": ultra, "短期": short, "中期": mid, "长期": lng}
    primary_period = max(period_scores, key=period_scores.get)
    hold_td = HOLD_TD[primary_period]                  # 建议交易日
    _td = datetime.date.fromisoformat(TRADE_DATE)
    buy_date = _next_trading_day(_td + datetime.timedelta(days=1))   # 下一交易日方可买入
    sell_date = _add_trading_days(buy_date, hold_td)                # 卖出日 = 买入后推进 hold_td 个交易日
    hold_cal = (sell_date - buy_date).days            # 对应自然日跨度

    candidates.append({
        "code": code, "name": s["name"], "close": close,
        "change_pct": s["change_pct"], "turnover_pct": tr,
        "net_buy": s["net_buy"], "accum_amount": s["accum_amount"],
        "net_ratio": round(ratio * 100, 2),
        "industry": ind_name, "tags": tags, "theme_raw": theme_raw,
        "reasons": s.get("reasons", []),
        "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "atr": round(atr, 3),
        "high20": tk["high20"], "high_all": tk["high_all"],
        "ret5": tk["ret5"], "ret20": tk["ret20"], "ret60": tk["ret60"],
        "vol_ratio5": tk["vol_ratio5"],
        "score": round(total, 1),
        "sub": {"fund": round(fund_score, 1), "theme": round(theme_score, 1),
                "tech": tech_score, "turn": turn_score, "ind": round(ind_score, 1)},
        "buy": buy, "sell": sell, "stop": stop, "rr": rr,
        "buy_date": buy_date.isoformat(), "sell_date": sell_date.isoformat(),
        "hold_td": hold_td, "hold_cal": hold_cal, "primary_period": primary_period,
        "r_ultra": grade(ultra), "r_short": grade(short),
        "r_mid": grade(mid), "r_long": grade(lng),
        "v_ultra": round(ultra), "v_short": round(short),
        "v_mid": round(mid), "v_long": round(lng),
    })

candidates.sort(key=lambda x: -x["score"])
shortlist = [c for c in candidates if c["net_buy"] > 0 or c["theme_raw"] >= 2][:12]

# ══════════════ 5. 同花顺强势股数量趋势（情绪温度） ══════════════
def ths_count(dt):
    try:
        u = (f"http://zx.10jqka.com.cn/event/api/getharden/date/{dt}"
             f"/orderby/date/orderway/desc/charset/GBK/")
        d = requests.get(u, headers={"User-Agent": UA}, timeout=15).json()
        return dt, len(d.get("data") or [])
    except Exception:
        return dt, None

trend = {}
cache = f"{D}/ths_trend.json"
if os.path.exists(cache):
    try:
        trend = json.load(open(cache))
    except Exception:
        trend = {}
# 仅保留交易日区间为最近 12 个交易日内的数据，避免混入历史缓存
if trend:
    dts = sorted(trend.keys())
    keep = dts[-12:]
    trend = {d_: trend[d_] for d_ in keep if d_ in trend}
trend_list = [{"date": d_, "n": trend[d_]} for d_ in sorted(trend.keys())]

# ══════════════ 6. 基本面（新浪，用于长期评级佐证） ══════════════
def sina_fund(code):
    p = "sh" if code.startswith(("6", "9")) else ("bj" if code.startswith(("4", "8")) else "sz")
    try:
        r = requests.get("https://quotes.sina.cn/cn/api/openapi.php/"
                         "CompanyFinanceService.getFinanceReport2022",
                         params={"paperCode": f"{p}{code}", "source": "lrb",
                                 "type": "0", "page": "1", "num": "4"},
                         headers={"User-Agent": UA}, timeout=20)
        rl = (r.json().get("result") or {}).get("data", {}).get("report_list", {}) or {}
        per = sorted([k for k in rl.keys() if k <= "20260630"], reverse=True)
        if not per: return code, None
        p0 = per[0]
        out = {"period": f"{p0[:4]}-{p0[4:6]}-{p0[6:8]}"}
        for it in (rl[p0].get("data") or []):
            t = it.get("item_title")
            if t in ("营业收入", "净利润", "归属于母公司所有者的净利润"):
                out[t] = it.get("item_value")
                out[t + "_同比"] = it.get("item_tongbi")
        return code, out
    except Exception:
        return code, None

fcache = f"{D}/fundamentals.json"
funds = json.load(open(fcache)) if os.path.exists(fcache) else {}
need = [c["code"] for c in shortlist if c["code"] not in funds]
if need:
    with ThreadPoolExecutor(max_workers=5) as ex:
        for f in as_completed([ex.submit(sina_fund, c) for c in need]):
            code, o = f.result()
            if o: funds[code] = o
    json.dump(funds, open(fcache, "w"), ensure_ascii=False)
for c in shortlist:
    c["fund"] = funds.get(c["code"])

out = {
    "trade_date": TRADE_DATE,
    "fetched_at": s1.get("fetched_at"),
    "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    "breadth": s1.get("breadth") or {},
    "source_note": s1.get("source_note", ""),
    "lhb_records": lhb,
    "lhb_stocks": stock_agg,
    "lhb_summary": {
        "n_records": len(lhb), "n_stocks": len(stock_agg),
        "total_net": lhb_total_net, "total_buy": lhb_total_buy,
        "total_sell": lhb_total_sell,
        "n_net_pos": len([s for s in stock_agg if s["net_buy"] > 0]),
        "n_net_neg": len([s for s in stock_agg if s["net_buy"] < 0]),
        "n_up": len([s for s in stock_agg if s["change_pct"] > 0]),
        "n_down": len([s for s in stock_agg if s["change_pct"] < 0]),
    },
    "themes": themes, "total_tags": total_tags, "n_ths": len(ths),
    "ths_hot": ths,
    "industries": industries,
    "ind_summary": {"n": len(industries), "n_up": len(ind_up), "n_down": len(ind_dn),
                    "coverage": f"{len(industries)}/{len(board_names)}"},
    "candidates": candidates, "shortlist": shortlist,
    "trend": trend_list,
    "has_board_stats": bool(board_stats),
    "has_ind_map": bool(ind_map),
}
json.dump(out, open(f"{D}/report_data.json", "w"), ensure_ascii=False)

print(f"龙虎榜 {len(lhb)} 条 / {len(stock_agg)} 只 | 净买合计 {lhb_total_net/1e8:.2f}亿")
print(f"题材 {len(themes)} 个 / 标签 {total_tags} 次 | 强势股 {len(ths)} 只")
print(f"行业 {len(industries)}/{len(board_names)} 个 | 上涨 {len(ind_up)} 下跌 {len(ind_dn)}")
print(f"候选 {len(candidates)} 只 → 推荐 {len(shortlist)} 只")
print("TOP题材:", [(t['tag'], t['count']) for t in themes[:8]])
print("领涨行业:", [(i['name'], i['change_pct']) for i in industries[:5]])
print("领跌行业:", [(i['name'], i['change_pct']) for i in industries[-5:]])
print("推荐:", [(c['name'], c['score'], c['buy'], c['sell']) for c in shortlist])

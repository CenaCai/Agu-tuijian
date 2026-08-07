#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股市场情绪日报 · 统一采集层 (V2, 抗限流版)
数据源（全部实测可用，东财仅 1 次请求）：
  龙虎榜   : 东财 datacenter-web        (1 次请求)
  题材归因 : 同花顺 zx.10jqka.com.cn    (不封IP)
  行业分类 : 新浪 newSinaHy.php          (不封IP, 一次拿全)
  行业成分 : 新浪 Market_Center          (不封IP)
  全市场   : 新浪 hs_a                   (不封IP)
  个股行情 : 腾讯 web.ifzq.gtimg.cn      (不封IP, 限频→降并发+退避+续跑)
  基本面   : 新浪 CompanyFinanceService  (不封IP)
用法: python fetch_all.py [YYYY-MM-DD]
"""
import json, os, sys, time, random, threading, datetime
import urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor

def _latest_trading_day():
    d = datetime.date.today()
    while d.weekday() >= 5:           # 周末回退到上周五
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

TRADE_DATE = sys.argv[1] if len(sys.argv) > 1 else _latest_trading_day()
D = "data"
os.makedirs(D, exist_ok=True)
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def http_get(url, enc='utf-8', ref=None, timeout=20, retry=6, backoff=2.0):
    last = None
    for i in range(retry):
        try:
            h = {'User-Agent': UA, 'Accept': '*/*'}
            if ref:
                h['Referer'] = ref
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(enc, 'ignore')
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 501, 503):
                time.sleep(backoff * (2 ** i) + random.uniform(0.5, 1.8))
                continue
            time.sleep(1.0 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1) + random.random())
    raise last


# ════════════ 1. 龙虎榜（东财 datacenter-web，唯一东财请求） ════════════
def fetch_lhb():
    p = {"reportName": "RPT_DAILYBILLBOARD_DETAILSNEW", "columns": "ALL",
         "filter": f"(TRADE_DATE>='{TRADE_DATE}')(TRADE_DATE<='{TRADE_DATE}')",
         "pageNumber": "1", "pageSize": "500",
         "sortColumns": "BILLBOARD_NET_AMT", "sortTypes": "-1",
         "source": "WEB", "client": "WEB"}
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get?" + urllib.parse.urlencode(p)
    d = json.loads(http_get(url, ref="https://data.eastmoney.com/", retry=5))
    res = d.get("result") or {}
    rows = res.get("data") or []
    out = []
    for r in rows:
        out.append({
            "code": r.get("SECURITY_CODE", ""),
            "name": (r.get("SECURITY_NAME_ABBR") or "").replace(" ", ""),
            "reason": r.get("EXPLANATION", ""),
            "close": r.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(r.get("CHANGE_RATE") or 0), 2),
            "net_buy": float(r.get("BILLBOARD_NET_AMT") or 0),
            "buy": float(r.get("BILLBOARD_BUY_AMT") or 0),
            "sell": float(r.get("BILLBOARD_SELL_AMT") or 0),
            "turnover_pct": round(float(r.get("TURNOVERRATE") or 0), 2),
            "accum_amount": float(r.get("ACCUM_AMOUNT") or 0),
            "deal_net_ratio": r.get("DEAL_NET_RATIO"),
            "free_mcap": r.get("FREE_MARKET_CAP") or 0,
        })
    log(f"[1/8] 龙虎榜 {TRADE_DATE}: {len(out)} 条 (server count={res.get('count')})")
    return out


# ════════════ 2. 同花顺题材归因 ════════════
def fetch_ths(dt=None):
    dt = dt or TRADE_DATE
    url = (f"http://zx.10jqka.com.cn/event/api/getharden/date/{dt}"
           f"/orderby/date/orderway/desc/charset/GBK/")
    d = json.loads(http_get(url, enc='gbk', ref="http://zx.10jqka.com.cn/"))
    rows = d.get("data") or []
    out = []
    for r in rows:
        out.append({"code": r.get("code", ""), "name": r.get("name", ""),
                    "reason": r.get("reason", ""), "close": r.get("close"),
                    "zhangfu": r.get("zhangfu"), "huanshou": r.get("huanshou"),
                    "chengjiaoe": r.get("chengjiaoe"), "ddejingliang": r.get("ddejingliang"),
                    "market": r.get("market", "")})
    if dt == TRADE_DATE:
        log(f"[2/8] 同花顺强势股 {dt}: {len(out)} 只")
    return out


# ════════════ 3. 新浪行业分类 ════════════
SINA_HY = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
SINA_NODE = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
             "Market_Center.getHQNodeData?page=1&num=1000&sort=symbol&asc=1&node={}")
SINA_ALL = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "Market_Center.getHQNodeData?page={}&num=1000&sort=symbol&asc=1&node=hs_a")


def fetch_industries():
    t = http_get(SINA_HY, enc='gbk', ref="https://finance.sina.com.cn/")
    body = t[t.find('{'):t.rfind('}') + 1]
    d = json.loads(body)
    out = []
    for k, v in d.items():
        p = v.split(',')
        if len(p) < 13:
            continue
        out.append({"code": p[0], "name": p[1], "n_stock": int(float(p[2] or 0)),
                    "avg_price": float(p[3] or 0), "today_chg": float(p[5] or 0),
                    "amount": float(p[7] or 0),
                    "leader_symbol": p[8], "leader_name": p[12]})
    log(f"[3/8] 新浪行业分类: {len(out)} 个行业")
    return out


def fetch_members(board_code):
    t = http_get(SINA_NODE.format(board_code), ref="https://vip.stock.finance.sina.com.cn/")
    try:
        rows = json.loads(t)
    except Exception:
        return []
    return [{"symbol": r.get("symbol", ""), "code": r.get("code", ""),
             "name": r.get("name", "")} for r in rows if r.get("symbol")]


def fetch_all_members(boards):
    members, lock = {}, threading.Lock()
    done = [0]

    def work(b):
        try:
            m = fetch_members(b["code"])
        except Exception:
            m = []
        with lock:
            members[b["code"]] = m
            done[0] += 1
            if done[0] % 25 == 0:
                log(f"      成分股 {done[0]}/{len(boards)}")
        return len(m)

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, boards))
    tot = sum(len(v) for v in members.values())
    log(f"[4/8] 行业成分股: {len(members)} 个行业 / {tot} 条映射")
    return members



# ════════════ 5. 腾讯 K 线：当日涨跌幅（降并发+退避+续跑） ════════════
TX = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,{beg},{end},{n},qfq"


def _prev_days(dt, n):
    return (datetime.date.fromisoformat(dt) - datetime.timedelta(days=n)).isoformat()


def tx_day_change(symbol):
    url = TX.format(sym=symbol, beg=_prev_days(TRADE_DATE, 14), end=TRADE_DATE, n=12)
    try:
        j = json.loads(http_get(url, retry=4, timeout=12, backoff=3.0))
    except Exception:
        return None
    node = (j.get("data") or {}).get(symbol) or {}
    kl = node.get("qfqday") or node.get("day") or []
    if len(kl) < 2:
        return None
    idx = None
    for i, r in enumerate(kl):
        if r[0] == TRADE_DATE:
            idx = i
            break
    if idx is None or idx == 0:
        return None
    try:
        cur = float(kl[idx][2])
        prev = float(kl[idx - 1][2])
        if prev <= 0:
            return None
        return (cur, round((cur - prev) / prev * 100, 2))
    except Exception:
        return None


def batch_changes(symbols, workers=6, cache_file=f"{D}/stock_changes.json"):
    res = {}
    if os.path.exists(cache_file):
        try:
            res = json.load(open(cache_file))
        except Exception:
            res = {}
    pending = [s for s in symbols if s not in res]
    total = len(symbols)
    log(f"[5/8] 全市场行情: 已完成 {len(res)} / 待采 {len(pending)}")
    if pending:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for s, r in zip(pending, ex.map(tx_day_change, pending)):
                if r:
                    res[s] = {"close": r[0], "chg": r[1]}
                if len(res) % 300 == 0:
                    json.dump(res, open(cache_file, "w"), ensure_ascii=False)
                    log(f"      K线续跑命中 {len(res)}/{total}")
    json.dump(res, open(cache_file, "w"), ensure_ascii=False)
    log(f"[5/8] 全市场当日行情: {len(res)}/{total} 只命中")
    return res


def market_breadth(allstocks, changes):
    up = dn = flat = lu = ld = 0
    vals = []
    for s in allstocks:
        ch = changes.get(s["symbol"])
        if not ch:
            continue
        c = ch["chg"]
        vals.append((s["code"], s["name"], c))
        if c > 0:
            up += 1
        elif c < 0:
            dn += 1
        else:
            flat += 1
        lim = 19.5 if s["code"][:2] in ('30', '68') else 9.5
        if c >= lim:
            lu += 1
        elif c <= -lim:
            ld += 1
    vals.sort(key=lambda x: -x[2])
    log(f"      市场宽度: {up}涨 / {dn}跌 / {flat}平  涨停{lu} 跌停{ld}  (样本{len(vals)})")
    return {"up": up, "down": dn, "flat": flat, "limit_up": lu, "limit_down": ld,
            "sample": len(vals),
            "top10": [{"code": v[0], "name": v[1], "chg": v[2]} for v in vals[:10]],
            "bottom10": [{"code": v[0], "name": v[1], "chg": v[2]} for v in vals[-10:]]}


# ════════════ 6. 本地聚合行业 ════════════
def aggregate_boards(boards, members, changes):
    board_hist, board_stats = {}, {}
    for b in boards:
        c = b["code"]
        ms = members.get(c) or []
        vals = []
        for m in ms:
            ch = changes.get(m["symbol"])
            if ch:
                vals.append((m["code"], m["name"], ch["chg"], ch["close"]))
        if not vals:
            continue
        chgs = [v[2] for v in vals]
        avg = round(sum(chgs) / len(chgs), 2)
        up = sum(1 for x in chgs if x > 0)
        dn = sum(1 for x in chgs if x < 0)
        flat = len(chgs) - up - dn
        top = max(vals, key=lambda v: v[2])
        board_hist[c] = {"code": c, "name": b["name"], "date": TRADE_DATE,
                         "change_pct": avg, "close": None}
        board_stats[c] = {"name": b["name"], "up": up, "down": dn, "flat": flat,
                          "total": len(chgs),
                          "leader": {"code": top[0], "name": top[1],
                                     "chg": top[2], "close": top[3]}}
    log(f"[6/8] 行业聚合完成: {len(board_hist)} 个行业（含涨跌家数+领涨股）")
    return board_hist, board_stats


# ════════════ 7. 候选股技术面（120日K，续跑） ════════════
def prefix(code):
    c = str(code)
    if c.startswith(('60', '68', '58', '51', '11')):
        return 'sh' + c
    if c.startswith(('4', '8', '92')):
        return 'bj' + c
    return 'sz' + c


def kline_120(code):
    sym = prefix(code)
    url = TX.format(sym=sym, beg=_prev_days(TRADE_DATE, 260), end=TRADE_DATE, n=180)
    try:
        j = json.loads(http_get(url, retry=4, timeout=15, backoff=3.0))
    except Exception:
        return None
    node = (j.get("data") or {}).get(sym) or {}
    kl = node.get("qfqday") or node.get("day") or []
    rows = []
    for r in kl:
        if r[0] > TRADE_DATE:
            continue
        try:
            rows.append({"date": r[0], "open": float(r[1]), "close": float(r[2]),
                         "high": float(r[3]), "low": float(r[4]), "vol": float(r[5])})
        except Exception:
            pass
    return rows or None


def indicators(rows):
    if not rows or len(rows) < 25:
        return None
    c = [r["close"] for r in rows]
    h = [r["high"] for r in rows]
    lo = [r["low"] for r in rows]
    v = [r["vol"] for r in rows]

    def ma(n):
        return round(sum(c[-n:]) / n, 3) if len(c) >= n else None
    trs = []
    for i in range(1, len(rows)):
        trs.append(max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
    atr14 = round(sum(trs[-14:]) / min(14, len(trs)), 3) if trs else None

    def ret(n):
        return round((c[-1] / c[-1 - n] - 1) * 100, 2) if len(c) > n and c[-1 - n] else None
    vr = round(v[-1] / (sum(v[-6:-1]) / 5), 2) if len(v) >= 6 and sum(v[-6:-1]) > 0 else None
    return {"last_close": c[-1], "last_date": rows[-1]["date"], "ma5": ma(5), "ma10": ma(10),
            "ma20": ma(20), "ma60": ma(60), "atr14": atr14,
            "high20": max(h[-20:]), "low20": min(lo[-20:]),
            "high60": max(h[-60:]) if len(h) >= 60 else max(h),
            "low60": min(lo[-60:]) if len(lo) >= 60 else min(lo),
            "high_all": max(h), "low_all": min(lo), "vol_ratio5": vr,
            "ret5": ret(5), "ret20": ret(20), "ret60": ret(60),
            "bars": len(rows), "kline_tail": rows[-60:]}


def fetch_tech(codes, workers=6, cache_file=f"{D}/tech.json"):
    out = {}
    if os.path.exists(cache_file):
        try:
            out = json.load(open(cache_file))
        except Exception:
            out = {}
    pending = [c for c in codes if c not in out]
    total = len(codes)
    log(f"[7/8] 技术面: 已完成 {len(out)} / 待采 {len(pending)}")

    def work(code):
        rows = kline_120(code)
        ind = indicators(rows) if rows else None
        return code, ind

    if pending:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for code, ind in ex.map(work, pending):
                if ind:
                    out[code] = ind
                if len(out) % 200 == 0:
                    json.dump(out, open(cache_file, "w"), ensure_ascii=False)
                    log(f"      技术面续跑 {len(out)}/{total}")
    json.dump(out, open(cache_file, "w"), ensure_ascii=False)
    log(f"[7/8] 候选股技术面: {len(out)}/{total} 只")
    return out


# ════════════ 8. 情绪趋势 + 基本面 ════════════
def fetch_ths_trend():
    base = datetime.date.fromisoformat(TRADE_DATE)
    days = []
    d = base
    while len(days) < 10:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    days.reverse()
    trend, lock = {}, threading.Lock()

    def work(dt):
        try:
            n = len(fetch_ths(dt))
        except Exception:
            n = None
        with lock:
            if n is not None:
                trend[dt] = n

    with ThreadPoolExecutor(max_workers=5) as ex:
        list(ex.map(work, days))
    log(f"[8/8] 情绪趋势: {len(trend)} 个交易日")
    return dict(sorted(trend.items()))


def fetch_fundamentals(codes):
    url = ("https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService."
           "getFinanceReport2022?paperCode={}&source=lrb&type=0&page=1&num=2")
    out, lock = {}, threading.Lock()

    def work(code):
        try:
            sym = prefix(code)
            j = json.loads(http_get(url.format(sym), retry=1, timeout=12))
            data = ((j.get("result") or {}).get("data") or {})
            rep = (data.get("report_list") or {})
            if rep:
                k = sorted(rep.keys(), reverse=True)[0]
                item = rep[k]
                with lock:
                    out[code] = {"period": k, "revenue": item.get("YYZSR") or item.get("v1"),
                                 "profit": item.get("JLR") or item.get("v2")}
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, codes))
    log(f"      基本面: {len(out)} 只")
    return out


# ════════════ MAIN ════════════
def main():
    t0 = time.time()
    log(f"══════ 开始采集 {TRADE_DATE} ══════")
    lhb = fetch_lhb()
    if not lhb:
        log("!! 龙虎榜为空，终止")
        sys.exit(1)
    ths = fetch_ths()
    boards = fetch_industries()
    members = fetch_all_members(boards)
    allstocks = [{"symbol": m["symbol"], "code": m["code"], "name": m["name"]}
                for v in members.values() for m in v]
    syms = sorted({m["symbol"] for v in members.values() for m in v})
    changes = batch_changes(syms)
    breadth = market_breadth(allstocks, changes)
    json.dump(breadth, open(f"{D}/breadth.json", "w"), ensure_ascii=False)
    board_hist, board_stats = aggregate_boards(boards, members, changes)
    stage1 = {
        "trade_date": TRADE_DATE,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "lhb": lhb, "ths_hot": ths,
        "board_list": [{"code": b["code"], "name": b["name"]} for b in boards],
        "board_hist": board_hist, "board_flow": {},
        "breadth": breadth,
        "source_note": "龙虎榜=东财datacenter；题材=同花顺；行业分类/成分/全市场=新浪；行情=腾讯",
    }
    json.dump(stage1, open(f"{D}/stage1.json", "w"), ensure_ascii=False)
    json.dump(board_stats, open(f"{D}/board_stats.json", "w"), ensure_ascii=False)
    allmap = []
    for b in boards:
        for m in members.get(b["code"]) or []:
            allmap.append({"f12": m["code"], "f14": m["name"], "f100": b["name"]})
    json.dump(allmap, open(f"{D}/allstocks_industry.json", "w"), ensure_ascii=False)
    cands = sorted({r["code"] for r in lhb} | {r["code"] for r in ths})
    tech = fetch_tech(cands)
    trend = fetch_ths_trend()
    json.dump(trend, open(f"{D}/ths_trend.json", "w"), ensure_ascii=False)
    funds = fetch_fundamentals(cands[:60])
    json.dump(funds, open(f"{D}/fundamentals.json", "w"), ensure_ascii=False)
    log(f"══════ 主干完成 用时 {time.time()-t0:.0f}s ══════")
    log(f"龙虎榜 {len(lhb)} / 题材 {len(ths)} / 行业 {len(board_hist)} / 技术面 {len(tech)} / 市场宽度样本 {breadth.get('sample')}")


if __name__ == "__main__":
    main()

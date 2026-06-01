#!/usr/bin/env python3
"""
A 股每日选股脚本 — 集成 Sequoia 策略引擎
基于 Sequoia（https://github.com/sngyai/Sequoia）的开源策略逻辑重写
数据源：akshare（免费）
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import date, timedelta

import akshare as ak
import numpy as np
import pandas as pd

# ── 配置 ──
ENABLED_STRATEGIES = [
    "海龟交易法则",
    "放量上涨",
    "均线多头",
]
MIN_MARKET_CAP = 20e9
MIN_AMOUNT = 2e8
TOP_N = 20
MAX_RETRIES = 3
RETRY_DELAY = 2
BALANCE = 200000


def ma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def atr(high, low, close, period=20):
    h, l, c = high.values, low.values, close.values
    tr = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(c))]
    tr = pd.Series(tr, index=high.index[1:])
    return tr.rolling(window=period, min_periods=period).mean()


def retry(func, *args, **kwargs):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                raise


def get_all_stocks():
    try:
        df = ak.stock_zh_a_spot_em()
        stocks = []
        for _, row in df.iterrows():
            code = str(row["代码"]).zfill(6)
            name = str(row["名称"])
            nmc = float(row["流通市值"]) * 1e4 if pd.notna(row["流通市值"]) else 0
            if nmc >= MIN_MARKET_CAP:
                stocks.append({"code": code, "name": name, "nmc": nmc})
        print(f"  [*] 获取到 {len(stocks)} 只股票（流通市值 >= {MIN_MARKET_CAP/1e9:.0f}亿）")
        return stocks
    except Exception as e:
        print(f"  [!] 获取股票列表失败: {e}")
        return []


def get_stock_hist(code, days=300):
    try:
        start = (date.today() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")
        end = date.today().strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq")
        if df is None or df.empty:
            return pd.DataFrame()
        df.columns = ["date","open","close","high","low","volume","amount","amplitude","p_change","change_pct","turnover"]
        return df
    except Exception:
        return pd.DataFrame()


def strategy_turtle_trade(code, name, df):
    if len(df) < 60: return None
    window = df.tail(20)
    if len(window) < 20: return None
    max_price = window["high"].max()
    last_close = float(window.iloc[-1]["close"])
    last_amount = float(window.iloc[-1]["amount"])
    if last_amount < MIN_AMOUNT or last_close < max_price: return None
    atr_val = atr(df["high"], df["low"], df["close"], 20).dropna()
    if atr_val.empty: return None
    current_atr = float(atr_val.iloc[-1])
    if current_atr <= 0: return None
    position_size = math.floor(BALANCE / 100 / current_atr)
    buy_price = round(last_close, 2)
    stop_price = round(last_close - 2 * current_atr, 2)
    sell_price = round(last_close + 2 * current_atr, 2)
    hold_days = max(1, min(int(round(2 * current_atr / (current_atr * 1.5))), 15))
    return {"code": code, "name": name, "strategy": "海龟交易法则",
            "buy_price": buy_price, "sell_price": sell_price, "stop_price": stop_price,
            "hold_days": hold_days, "atr": round(current_atr, 2),
            "position_size": position_size,
            "detail": f"ATR={current_atr:.2f}, 头寸={position_size}手, 止损={stop_price}"}


def strategy_volume_breakout(code, name, df):
    if len(df) < 65: return None
    df = df.copy()
    df["vol_ma5"] = ma(df["volume"], 5)
    tail = df.tail(61)
    if len(tail) < 61: return None
    last = tail.iloc[-1]
    p_change = float(last["p_change"]) if pd.notna(last["p_change"]) else float(last.get("change_pct", 0))
    last_close = float(last["close"])
    last_open = float(last["open"])
    last_vol = float(last["volume"])
    last_amount = float(last["amount"])
    if p_change < 2 or last_close < last_open or last_amount < MIN_AMOUNT: return None
    front = tail.head(60)
    mean_vol = float(front["vol_ma5"].iloc[-1]) if pd.notna(front["vol_ma5"].iloc[-1]) else 0
    if mean_vol <= 0: return None
    vol_ratio = last_vol / mean_vol
    if vol_ratio < 2: return None
    atr_val = atr(df["high"], df["low"], df["close"], 20).dropna()
    current_atr = float(atr_val.iloc[-1]) if not atr_val.empty else last_close * 0.02
    buy_price = round(last_close * 1.01, 2)
    sell_price = round(last_close + current_atr * 2, 2)
    hold_days = max(1, min(int(round(current_atr * 2 / (current_atr * 1.2))), 10))
    return {"code": code, "name": name, "strategy": "放量上涨",
            "buy_price": buy_price, "sell_price": sell_price, "hold_days": hold_days,
            "vol_ratio": round(vol_ratio, 2), "p_change": round(p_change, 2),
            "detail": f"量比={vol_ratio:.2f}, 涨幅={p_change:.2f}%"}


def strategy_ma_alignment(code, name, df):
    if len(df) < 30: return None
    df = df.copy()
    df["ma30"] = ma(df["close"], 30)
    tail = df.tail(30).dropna(subset=["ma30"])
    if len(tail) < 30: return None
    s1, s2, s3, s_end = tail.iloc[0]["ma30"], tail.iloc[9]["ma30"], tail.iloc[19]["ma30"], tail.iloc[-1]["ma30"]
    if not (s1 < s2 < s3 < s_end and s_end > 1.2 * s1): return None
    last_close = float(tail.iloc[-1]["close"])
    atr_val = atr(df["high"], df["low"], df["close"], 20).dropna()
    current_atr = float(atr_val.iloc[-1]) if not atr_val.empty else last_close * 0.02
    buy_price = round(last_close * 0.98, 2)
    sell_price = round(last_close + current_atr * 2, 2)
    hold_days = max(3, min(int(round(current_atr * 2 / (current_atr * 1.2))), 15))
    return {"code": code, "name": name, "strategy": "均线多头",
            "buy_price": buy_price, "sell_price": sell_price, "hold_days": hold_days,
            "detail": f"MA30={s_end:.2f}, 趋势={round(s_end/s1, 2)}x"}


def main():
    parser = argparse.ArgumentParser(description="A 股每日选股（集成 Sequoia 策略）")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    args = parser.parse_args()
    target_date = args.date if args.date else date.today().isoformat()
    print(f"[*] 开始运行选股策略，目标日期: {target_date}")
    print(f"[*] 启用策略: {ENABLED_STRATEGIES}")
    try:
        print("\n[1/3] 获取 A 股列表...")
        all_stocks = get_all_stocks()
        if not all_stocks:
            print("[-] 无法获取股票列表，退出")
            sys.exit(1)
        print(f"\n[2/3] 运行策略扫描（共 {len(all_stocks)} 只股票）...")
        strategy_map = {"海龟交易法则": strategy_turtle_trade, "放量上涨": strategy_volume_breakout, "均线多头": strategy_ma_alignment}
        all_results = []
        errors = 0
        checked = 0
        for i, stock in enumerate(all_stocks):
            checked += 1
            if checked % 500 == 0:
                print(f"  ... 已扫描 {checked}/{len(all_stocks)}")
            code, name = stock["code"], stock["name"]
            df = pd.DataFrame()
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    df = get_stock_hist(code)
                    break
                except Exception:
                    if attempt < MAX_RETRIES: time.sleep(RETRY_DELAY)
            if df.empty or len(df) < 30: continue
            for sname in ENABLED_STRATEGIES:
                if sname not in strategy_map: continue
                try:
                    result = strategy_map[sname](code, name, df)
                    if result: all_results.append(result)
                except Exception: errors += 1
            time.sleep(0.1)
        print(f"\n[3/3] 整理结果...")
        final_stocks = []
        for sname in ENABLED_STRATEGIES:
            matched = [r for r in all_results if r["strategy"] == sname][:TOP_N]
            final_stocks.extend(matched)
        seen, unique = set(), []
        for s in final_stocks:
            if s["code"] not in seen:
                seen.add(s["code"])
                unique.append(s)
        results = {"date": target_date, "strategies": ENABLED_STRATEGIES, "stock_count": len(unique), "stocks": unique}
        os.makedirs("results", exist_ok=True)
        output_path = f"results/{target_date}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[+] 结果已保存到 {output_path}")
        print(f"[+] 扫描 {checked} 只，错误 {errors} 次，选中 {len(unique)} 只（{len(all_results)} 次命中）")
        for s in unique:
            print(f"  {s['code']} {s['name']} [{s['strategy']}] 买入:{s.get('buy_price','N/A')} 卖出:{s.get('sell_price','N/A')} 持有:{s.get('hold_days','N/A')}天  {s.get('detail','')}")
        sys.exit(0)
    except Exception as e:
        print(f"[-] 运行失败: {e}")
        import traceback; traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
A 股每日选股脚本 — 5日5%策略模型
专为挂单操作模式设计：
  - 买入价 = 收盘价 - 0.5%（低吸挂单）
  - 卖出价 = 买入价 + 5%（目标止盈）
  - 止损价 = 买入价 - 2%（止损线）
  - 持有期 = 5个交易日
  - 盈亏比 = 2.5（每次盈利5%，每次止损亏2%）
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

# ═══════════════════════════════════════════════════════════
# 配置参数
# ═══════════════════════════════════════════════════════════

# 基础筛选
MIN_MARKET_CAP = 5e9          # 最低流通市值 50亿（流动性保证）
MIN_AMOUNT = 5000e4           # 最低日成交额 5000万
MAX_PRICE = 100               # 排除高价股（>100元操作风险大）
MIN_PRICE = 3                 # 排除低价垃圾股

# 策略参数
TARGET_RETURN = 0.05          # 目标收益 5%
STOP_LOSS_PCT = 0.02          # 止损幅度 2%
BUY_OFFSET_PCT = 0.005       # 买入价偏移（比收盘价低0.5%）
HOLD_DAYS = 5                 # 持有周期（交易日）

# 动量条件
MIN_5D_RETURN = 0.0           # 5日涨幅 > 0%（至少不跌）
MIN_20D_RETURN = 0.03         # 20日涨幅 > 3%（中期趋势向上）
VOLUME_RATIO_MIN = 0.8        # 量比下限（不低于平均）
MAX_DAILY_CHANGE = 0.05       # 排除当日涨幅>5%（追高风险）

# 波动率适配
ATR_PCT_MIN = 0.01            # 5日ATR/价格 > 1%（太低则5%难到）
ATR_PCT_MAX = 0.03            # 5日ATR/价格 < 3%（太高则下跌风险大）

# 趋势条件
MAX_DIST_MA20 = 0.03          # 距MA20 < 3%（有支撑）
MA30_SLOPE_MIN = 0.0           # MA30斜率 > 0（中期向上）

# 排除条件
MAX_CONSECUTIVE_DROP = 3      # 连续跌>3天排除
MIN_HIGH_LOW_SPREAD = 0.08     # 单日振幅>8%排除
DOWNTICK_IN_5D = True         # 近5日有跌停排除

# 输出限制
MAX_RESULTS = 10              # 最多推荐10只

# 网络
MAX_RETRIES = 3
RETRY_DELAY = 2


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════
def ma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def compute_atr(high, low, close, period=5):
    """短期ATR（用于衡量5日内预期波动）"""
    h = high.values
    l = low.values
    c = close.values
    if len(c) < period + 1:
        return pd.Series(dtype=float)
    tr = []
    for i in range(1, len(c)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])))
    tr = pd.Series(tr, index=high.index[1:])
    return tr.rolling(window=period, min_periods=period).mean()


def pct_change_from_period(df, col="close", period=5):
    """计算N日涨幅"""
    if len(df) < period + 1:
        return 0.0
    return (float(df[col].iloc[-1]) / float(df[col].iloc[-(period+1)])) - 1


# ═══════════════════════════════════════════════════════════
# 数据获取（保持原有的双接口+重试机制）
# ═══════════════════════════════════════════════════════════
def get_all_stocks():
    fetchers = [_fetch_from_spot_em, _fetch_from_push2]
    last_err = None
    for fetcher in fetchers:
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                stocks = fetcher()
                if stocks:
                    return stocks
            except Exception as e:
                last_err = e
                wait = RETRY_DELAY * attempt
                print(f"  [!] {fetcher.__name__} 失败 (第{attempt}次): {e}")
                if attempt < MAX_RETRIES + 1:
                    time.sleep(wait)
    print(f"  [!] 所有接口均失败: {last_err}")
    return []


def _fetch_from_spot_em():
    df = ak.stock_zh_a_spot_em()
    stocks = []
    for _, row in df.iterrows():
        code = str(row["代码"]).zfill(6)
        name = str(row["名称"])
        nmc = float(row["流通市值"]) * 1e4 if pd.notna(row["流通市值"]) else 0
        close_price = float(row["最新价"]) if pd.notna(row["最新价"]) else 0
        amount = float(row["成交额"]) if pd.notna(row["成交额"]) else 0
        p_change = float(row["涨跌幅"]) if pd.notna(row["涨跌幅"]) else 0
        if nmc >= MIN_MARKET_CAP and close_price >= MIN_PRICE and close_price <= MAX_PRICE:
            stocks.append({
                "code": code, "name": name, "nmc": nmc,
                "close": close_price, "amount": amount, "p_change": p_change,
            })
    print(f"  [*] [spot_em] 获取到 {len(stocks)} 只股票（市值>=50亿，价格3-100元）")
    return stocks


def _fetch_from_push2():
    import requests
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": "5000", "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f2,f3,f6,f7,f12,f14,f15,f16,f17,f20",
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=30)
    data = resp.json()
    stocks = []
    for item in data.get("data", {}).get("diff", []):
        code = str(item.get("f12", "")).zfill(6)
        name = str(item.get("f14", ""))
        if not code or not name:
            continue
        close_price = item.get("f2", 0) or 0
        p_change = item.get("f3", 0) or 0
        high = item.get("f15", 0) or 0
        low = item.get("f16", 0) or 0
        amount = item.get("f6", 0) or 0
        nmc = item.get("f20", 0) or 0
        if nmc > 0:
            nmc = nmc * 1e4
        if nmc >= MIN_MARKET_CAP and close_price >= MIN_PRICE and close_price <= MAX_PRICE:
            stocks.append({
                "code": code, "name": name, "nmc": nmc,
                "close": close_price, "amount": amount, "p_change": p_change / 100,
            })
    print(f"  [*] [push2] 获取到 {len(stocks)} 只股票（轻量接口）")
    return stocks


def get_stock_hist(code, days=300):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            start = (date.today() - timedelta(days=int(days * 1.5))).strftime("%Y%m%d")
            end = date.today().strftime("%Y%m%d")
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start, end_date=end, adjust="qfq",
            )
            if df is None or df.empty:
                return pd.DataFrame()
            df.columns = ["date", "open", "close", "high", "low", "volume", "amount", "amplitude", "p_change", "change_pct", "turnover"]
            return df
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return pd.DataFrame()


# ═══════════════════════════════════════════════════════════
# 核心筛选逻辑 — 5日5%策略
# ═══════════════════════════════════════════════════════════
def screen_stock(code, name, stock_info, df) -> dict | None:
    """
    综合筛选一只股票是否满足5日5%策略条件。
    返回包含评分和价格信息的字典，不满足返回None。
    """
    if len(df) < 40:
        return None

    last = df.iloc[-1]
    close = float(last["close"])
    open_price = float(last["open"])
    high = float(last["high"])
    low = float(last["low"])
    amount = float(last["amount"])

    # ── 第1层：基础检查 ──
    # 成交额
    if amount < MIN_AMOUNT:
        return None

    # 当日涨幅不能太大（追高风险）
    today_change = float(last.get("p_change", 0)) if pd.notna(last.get("p_change", 0)) else 0
    if abs(today_change) > MAX_DAILY_CHANGE * 100:
        return None

    # ── 第2层：排除规则 ──
    tail5 = df.tail(5)

    # 排除连续跌3天以上
    consecutive_drop = 0
    for _, row in tail5.iterrows():
        chg = float(row.get("p_change", 0)) if pd.notna(row.get("p_change", 0)) else 0
        if chg < 0:
            consecutive_drop += 1
        else:
            break
    if consecutive_drop > MAX_CONSECUTIVE_DROP:
        return None

    # 排除近5日有跌停（跌幅>9.5%）
    if DOWNTICK_IN_5D:
        for _, row in tail5.iterrows():
            chg = float(row.get("p_change", 0)) if pd.notna(row.get("p_change", 0)) else 0
            if chg < -9.5:
                return None

    # 排除单日振幅过大
    recent = df.tail(10)
    for _, row in recent.iterrows():
        h = float(row["high"])
        l = float(row["low"])
        if l > 0 and (h - l) / l > MIN_HIGH_LOW_SPREAD:
            return None

    # ── 第3层：动量确认 ──
    ret_5d = pct_change_from_period(df, "close", 5)
    ret_20d = pct_change_from_period(df, "close", 20)

    if ret_5d < MIN_5D_RETURN:
        return None
    if ret_20d < MIN_20D_RETURN:
        return None

    # ── 第4层：波动率适配 ──
    atr_series = compute_atr(df["high"], df["low"], df["close"], 5)
    if atr_series.empty:
        return None
    atr_5d = float(atr_series.iloc[-1])
    if atr_5d <= 0:
        return None
    atr_pct = atr_5d / close  # ATR占价格的比例

    if atr_pct < ATR_PCT_MIN or atr_pct > ATR_PCT_MAX:
        return None

    # ── 第5层：趋势+支撑 ──
    df_ext = df.copy()
    df_ext["ma20"] = ma(df_ext["close"], 20)
    df_ext["ma30"] = ma(df_ext["close"], 30)

    last_ma20 = df_ext["ma20"].dropna()
    if last_ma20.empty:
        return None
    current_ma20 = float(last_ma20.iloc[-1])

    # 站上MA20，且偏离不超过3%
    dist_ma20 = abs(close - current_ma20) / current_ma20
    if dist_ma20 > MAX_DIST_MA20 or close < current_ma20:
        return None

    # MA30斜率向上
    last_ma30 = df_ext["ma30"].dropna()
    if last_ma30.empty:
        return None
    ma30_series = last_ma30.tail(10)
    if len(ma30_series) >= 10:
        ma30_start = float(ma30_series.iloc[0])
        ma30_end = float(ma30_series.iloc[-1])
        ma30_slope = (ma30_end - ma30_start) / ma30_start
        if ma30_slope < MA30_SLOPE_MIN:
            return None

    # ── 第6层：量能确认 ──
    df_ext["vol_ma5"] = ma(df_ext["volume"], 5)
    vol_ma5 = df_ext["vol_ma5"].dropna()
    if vol_ma5.empty:
        return None
    current_vol_ma5 = float(vol_ma5.iloc[-1])
    if current_vol_ma5 <= 0:
        return None

    vol_ratio = float(last["volume"]) / current_vol_ma5
    if vol_ratio < VOLUME_RATIO_MIN:
        return None

    # ═══════════════════════════════════════════════════════
    # 计算价格和评分
    # ═══════════════════════════════════════════════════════
    buy_price = round(close * (1 - BUY_OFFSET_PCT), 2)
    sell_price = round(buy_price * (1 + TARGET_RETURN), 2)
    stop_price = round(buy_price * (1 - STOP_LOSS_PCT), 2)

    # 综合评分（满分100）
    score = 0.0

    # 动量分 (30分)
    score += min(ret_5d * 30 / 0.05, 15)       # 5日涨幅，满分15
    score += min(ret_20d * 15 / 0.10, 15)       # 20日涨幅，满分15

    # 波动率适配分 (20分)
    # ATR在1.5%-2.5%之间最佳
    if 0.015 <= atr_pct <= 0.025:
        score += 20
    elif 0.01 <= atr_pct < 0.015 or 0.025 < atr_pct <= 0.03:
        score += 10

    # 趋势分 (20分)
    score += max(0, (1 - dist_ma20) * 10)       # 越接近MA20越好
    if last_ma30.notna().all() and len(ma30_series) >= 10:
        slope_score = min(ma30_slope * 10 / 0.05, 10)
        score += slope_score

    # 量能分 (15分)
    if vol_ratio > 1.5:
        score += 15
    elif vol_ratio > 1.2:
        score += 10
    elif vol_ratio > 1.0:
        score += 5

    # 稳定性分 (15分)
    # 近5日没有大跌
    down_days = sum(1 for _, r in tail5.iterrows()
                    if float(r.get("p_change", 0)) < -2)
    score += max(0, 15 - down_days * 5)

    # 阳线加分（当天收阳更好）
    if close > open_price:
        score += 3

    score = round(score, 1)

    return {
        "code": code,
        "name": name,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "stop_price": stop_price,
        "hold_days": HOLD_DAYS,
        "score": score,
        "metrics": {
            "ret_5d": round(ret_5d * 100, 2),
            "ret_20d": round(ret_20d * 100, 2),
            "atr_pct": round(atr_pct * 100, 2),
            "vol_ratio": round(vol_ratio, 2),
            "dist_ma20": round(dist_ma20 * 100, 2),
            "today_change": round(today_change, 2),
        },
        "detail": (
            f"5日涨{ret_5d*100:.1f}% | 20日涨{ret_20d*100:.1f}% | "
            f"ATR{atr_pct*100:.1f}% | 量比{vol_ratio:.1f} | "
            f"距MA20 {dist_ma20*100:.1f}%"
        ),
    }


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="A 股每日选股 — 5日5%策略")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD，默认今天")
    args = parser.parse_args()
    target_date = args.date if args.date else date.today().isoformat()

    print(f"╔══════════════════════════════════════════════════════╗")
    print(f"║  A股每日选股 — 5日5%策略                              ║")
    print(f"║  目标日期: {target_date}                                ║")
    print(f"║  买入价=收盘价-0.5% | 卖出价=买入价+5% | 止损=买入价-2% ║")
    print(f"║  持有期=5交易日 | 盈亏比=2.5                         ║")
    print(f"╚══════════════════════════════════════════════════════╝")

    try:
        # 1. 获取股票列表
        print(f"\n[1/3] 获取A股列表...")
        all_stocks = get_all_stocks()
        if not all_stocks:
            print("[-] 无法获取股票列表，退出")
            sys.exit(1)

        # 2. 逐只筛选
        print(f"\n[2/3] 筛选股票（共 {len(all_stocks)} 只）...")
        results = []
        errors = 0
        checked = 0

        for i, stock in enumerate(all_stocks):
            checked += 1
            if checked % 200 == 0:
                print(f"  ... 已扫描 {checked}/{len(all_stocks)}，通过 {len(results)} 只")

            code = stock["code"]
            name = stock["name"]

            df = pd.DataFrame()
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    df = get_stock_hist(code)
                    break
                except Exception:
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY)

            if df.empty or len(df) < 40:
                continue

            try:
                result = screen_stock(code, name, stock, df)
                if result:
                    results.append(result)
            except Exception as e:
                errors += 1

            time.sleep(0.1)

        # 3. 排序输出
        print(f"\n[3/3] 整理结果...")
        results.sort(key=lambda x: x["score"], reverse=True)
        final_stocks = results[:MAX_RESULTS]

        output = {
            "date": target_date,
            "strategy": "5日5%策略",
            "description": (
                f"买入价=收盘价-0.5%，卖出价=买入价+5%，"
                f"止损价=买入价-2%，持有{HOLD_DAYS}个交易日，盈亏比2.5"
            ),
            "stock_count": len(final_stocks),
            "stocks": final_stocks,
        }

        os.makedirs("results", exist_ok=True)
        output_path = f"results/{target_date}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"[+] 结果已保存到 {output_path}")
        print(f"[+] 扫描 {checked} 只，通过 {len(results)} 只，输出 {len(final_stocks)} 只，错误 {errors} 次")
        print(f"{'='*60}")

        if final_stocks:
            print(f"\n{'代码':<8} {'名称':<8} {'评分':>4} {'买入价':>8} {'卖出价':>8} {'止损价':>8} {'详情'}")
            print(f"{'-'*8} {'-'*8} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*40}")
            for s in final_stocks:
                print(
                    f"{s['code']:<8} {s['name']:<8} {s['score']:>4.0f} "
                    f"{s['buy_price']:>8.2f} {s['sell_price']:>8.2f} {s['stop_price']:>8.2f} "
                    f"{s['detail']}"
                )
        else:
            print("\n[!] 今日无符合条件的股票。策略较为严格是正常的，")
            print("    这意味着市场上没有高确定性的5日5%机会。")
            print("    建议空仓等待，不操作就是最好的操作。")

        sys.exit(0)

    except Exception as e:
        print(f"[-] 运行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
A 股每日选股脚本（占位版）
使用 akshare 获取股票基本信息和行情数据
真实策略需要你后续对接 Sequoia-X API
"""
import argparse
import json
import os
import sys
import time
from datetime import date, timedelta

import akshare as ak
import numpy as np


# ── 占位股票池：真实环境请替换成 Sequoia-X 选出的股票代码 ──
PLACEHOLDER_STOCKS = [
    "000151", "000723", "000899", "002350", "002578",
    "002627", "002847", "300120", "300291", "300685",
]

# akshare 请求重试配置
MAX_RETRIES = 3
RETRY_DELAY = 2  # 秒


def retry(func, *args, **kwargs):
    """带重试的函数调用"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"  [!] 请求失败 (第{attempt}次), {RETRY_DELAY}s 后重试...")
                time.sleep(RETRY_DELAY)
            else:
                raise e


def get_stock_name(code: str) -> str:
    """通过 akshare 获取股票中文名称"""
    try:
        market = "sh" if code.startswith("6") else "sz"
        df = retry(ak.stock_individual_info_em, symbol=f"{market}{code}")
        name = df[df["item"] == "股票简称"]["value"].values[0]
        return str(name)
    except Exception as e:
        print(f"  [!] 获取 {code} 名称失败: {e}")
        return f"股票{code}"


def calc_buy_sell_price(code: str) -> dict:
    """
    基于近期均线 & ATR 计算建议买入价 / 卖出价 / 持有天数
    简化技术分析逻辑，仅供演示
    """
    try:
        today = date.today()
        start = (today - timedelta(days=180)).strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")

        df = retry(ak.stock_zh_a_hist,
                   symbol=code, period="daily",
                   start_date=start, end_date=end,
                   adjust="qfq")

        if df is None or df.empty or len(df) < 20:
            return {"buy_price": None, "sell_price": None, "hold_days": None}

        close = df["收盘"].values.astype(float)
        high = df["最高"].values.astype(float)
        low = df["最低"].values.astype(float)

        # ── 买入价：20 日均线 × 0.98（回调 2% 买入） ──
        ma20 = np.mean(close[-20:])
        buy_price = round(ma20 * 0.98, 2)

        # ── 卖出价：近 10 日最高价 × 1.05（涨幅 5% 止盈） ──
        recent_high = np.max(high[-10:])
        sell_price = round(recent_high * 1.05, 2)

        # ── 预计持有天数：基于 ATR 波动率估算 ──
        tr_list = []
        for i in range(1, len(close)):
            tr = max(high[i] - low[i],
                     abs(high[i] - close[i-1]),
                     abs(low[i] - close[i-1]))
            tr_list.append(tr)
        atr = np.mean(tr_list[-14:]) if len(tr_list) >= 14 else np.mean(tr_list)
        spread = sell_price - buy_price
        if atr > 0 and spread > 0:
            hold_days = max(1, min(int(round(spread / (atr * 1.5))), 20))
        else:
            hold_days = 5

        return {
            "buy_price": buy_price,
            "sell_price": sell_price,
            "hold_days": hold_days,
        }
    except Exception as e:
        print(f"  [!] 获取 {code} 行情失败: {e}")
        return {"buy_price": None, "sell_price": None, "hold_days": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None,
                        help="指定日期 (YYYY-MM-DD)，默认今天")
    args = parser.parse_args()

    target_date = args.date if args.date else date.today().isoformat()
    print(f"[*] 开始运行选股策略，目标日期: {target_date}")

    try:
        stock_codes = PLACEHOLDER_STOCKS  # TODO: 替换为 Sequoia-X 输出
        enriched_stocks = []

        for i, code in enumerate(stock_codes, 1):
            print(f"  [{i}/{len(stock_codes)}] 正在分析 {code} ...")
            name = get_stock_name(code)
            prices = calc_buy_sell_price(code)
            enriched_stocks.append({
                "code": code,
                "name": name,
                "buy_price": prices["buy_price"],
                "sell_price": prices["sell_price"],
                "hold_days": prices["hold_days"],
            })

        results = {
            "date": target_date,
            "strategy": "MaVolumeStrategy (占位)",
            "stock_count": len(enriched_stocks),
            "stocks": enriched_stocks,
        }

        os.makedirs("results", exist_ok=True)
        output_path = f"results/{target_date}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        print(f"\n[+] 结果已保存到 {output_path}")
        print(f"[+] 共选取 {len(enriched_stocks)} 只股票")

        # 打印摘要
        for s in enriched_stocks:
            bp = s['buy_price'] or 'N/A'
            sp = s['sell_price'] or 'N/A'
            hd = s['hold_days'] or 'N/A'
            print(f"  {s['code']} {s['name']} | 买入: {bp} | 卖出: {sp} | 持有: {hd}天")

        sys.exit(0)

    except Exception as e:
        print(f"[-] 运行失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日入口：自动确定最近交易日 → 跑 采集 → 分析 → 出HTML。
用法: python scripts/run_daily.py [YYYY-MM-DD]
不传参时取“今天（若为周末则返回上周五）”作为交易日。
需在仓库根目录运行（data/ 与 report.html 都落在仓库根）。"""
import subprocess, sys, os, datetime, shutil

def latest_trading_day():
    d = datetime.date.today()
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d.strftime("%Y-%m-%d")

if __name__ == "__main__":
    td = sys.argv[1] if len(sys.argv) > 1 else latest_trading_day()
    base = os.path.dirname(os.path.abspath(__file__))   # .../scripts
    root = os.path.dirname(base)                         # 仓库根
    print(f"[run_daily] 交易日 = {td}  cwd = {root}")

    steps = [("fetch_all.py", [td]), ("analyze.py", []), ("build_html.py", [])]
    for name, args in steps:
        cmd = [sys.executable, os.path.join(base, name), *args]
        print(f"[run_daily] ▶ {name} {' '.join(args)}")
        r = subprocess.run(cmd, cwd=root)
        if r.returncode != 0:
            print(f"[run_daily] ✗ {name} 失败，退出码 {r.returncode}")
            sys.exit(r.returncode)

    # 把分析结果也放到仓库根，便于提交/对外提供 JSON
    src = os.path.join(root, "data", "report_data.json")
    if os.path.exists(src):
        shutil.copy(src, os.path.join(root, "report_data.json"))
        print("[run_daily] 已复制 report_data.json → 仓库根")

    print("[run_daily] ✓ 全部完成 → report.html / report_data.json")

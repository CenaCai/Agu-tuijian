# Agu-tuijian（A 股情绪日报 · 推荐）

每日北京时间 **20:00** 自动生成 A 股「龙虎榜 + 题材热点 + 行业轮动 + 建议关注名单」市场情绪日报，输出单文件 HTML（`report.html`，资源全内联、可离线打开）。

> 旧版「5日5% 全市场硬门槛扫描」策略因规则过严 + 数据源被限流，长期选不出数据，已存档于 `scripts/run_selection_legacy.py`（仅供回溯，不再使用）。本仓库现行策略见下文。

## 现行策略：龙虎榜 + 题材动量，打分排序

不扫全市场，而是以**当日龙虎榜上榜股 + 同花顺强势股**为候选池（天然约 80~140 只动量票），再做多因子打分，取综合评分最高的 12 只进入「建议关注名单」。只要当日这两份数据存在，就一定出名单。

**打分维度（0–100）**：资金分(0–30) + 题材分(0–25) + 技术分(0–25) + 换手健康(0–10) + 行业分(0–10)。

**四周期评级**：超短期 / 短期 / 中期 / 长期，各映射为 强 / 较强 / 中性 / 偏弱 / 回避 五档。

**价格建议**（技术面推导）：
- 建议买入价 = min(支撑位, 收盘价×0.99)，支撑位 = max(MA5, 收盘价−1.2×ATR)
- 建议卖出价 = max(收盘价+2.5×ATR, 20日高点×1.02)，创新高再上调
- 止损价 = 买入价 − 1.5×ATR（下限兜底 买入价×0.85）
- 风险回报比 rr = (卖出−买入) ÷ (买入−止损)，仅作赔率参考，不含命中概率

## 数据源（全部实测可用，东财仅 1 次请求）

| 数据 | 来源 | 说明 |
|------|------|------|
| 龙虎榜 | 东方财富 datacenter-web | 仅 1 次请求 |
| 题材归因 | 同花顺 zx.10jqka.com.cn | 不封 IP |
| 行业分类 / 成分股 / 全市场 | 新浪财经 | 不封 IP |
| 个股行情 / 技术面 | 腾讯 web.ifzq.gtimg.cn | 不封 IP，限频→降并发+退避+续跑 |
| 基本面 | 新浪财经财报接口 | 不封 IP |

不依赖 `akshare` / `pandas` / `numpy`，仅 `requests` + 标准库。

## 文件说明

- `.github/workflows/daily_stock_pick.yml` — GitHub Actions 每日 20:00（UTC 12:00）自动运行
- `scripts/run_daily.py` — 入口：算最近交易日 → 采集 → 分析 → 出 HTML
- `scripts/fetch_all.py` — 统一采集层
- `scripts/analyze.py` — 分析 / 打分层
- `scripts/build_html.py` — HTML 生成层
- `requirements.txt` — 仅 `requests`
- `data/` — 运行时缓存（已被 `.gitignore` 忽略，每日重建）
- `scripts/run_selection_legacy.py` — 旧策略存档

## 本地运行

```bash
pip install -r requirements.txt
python scripts/run_daily.py            # 用今天（周末则返回上周五）
python scripts/run_daily.py 2026-08-06 # 指定交易日
```

产物落在仓库根：`report.html` 与 `report_data.json`。

## 触发方式

- 自动：每天北京时间 20:00（GitHub Actions 定时）
- 手动：仓库 **Actions** 选项卡 → `每日 A 股情绪日报` → **Run workflow**

## 重要说明

本报告由数据脚本自动生成，仅作市场情绪复盘与量化筛选参考，**不构成任何投资建议**。买卖决策与风险自担。

> 注意：GitHub Actions 运行器位于境外，腾讯/新浪/同花顺等境内接口一般可访问，但偶尔受网络/限频影响。若自动运行失败，可在 Actions 页面手动重跑，或改用境内自托管 Runner。

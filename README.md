# Agu-tuijian（A 股推荐）

每日北京时间 20:00 自动运行选股策略，结果以 JSON 格式保存在 `results/` 目录。

## 选股策略
基于 [Sequoia](https://github.com/sngyai/Sequoia) 开源项目的策略逻辑。

| 策略 | 逻辑 |
|------|------|
| 海龟交易法则 | 20日新高突破 + 成交额过亿 |
| 放量上涨 | 量比>2 + 涨幅>2% + 阳线 |
| 均线多头 | MA30 持续向上 + 趋势增幅>20% |

## 输出字段
- `code` — 股票代码
- `name` — 股票中文名称
- `strategy` — 命中的策略名
- `buy_price` — 建议买入价
- `sell_price` — 建议卖出价
- `stop_price` — 止损价（仅海龟策略）
- `hold_days` — 预计持有天数
- `detail` — 策略详情

## 触发方式
- 自动：每天北京时间 20:00
- 手动：Actions → Run workflow

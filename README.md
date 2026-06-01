# Agu-tuijian（A 股推荐）

每日北京时间 20:00 自动运行选股策略，结果以 JSON 格式保存在 `results/` 目录。

## 文件说明
- `.github/workflows/daily_stock_pick.yml` – GitHub Actions 工作流
- `scripts/run_selection.py` – 选股脚本（当前为占位版）
- `requirements.txt` – Python 依赖

## 后续完善
1. 在 `run_selection.py` 中对接真实的 Sequoia-X API
2. 确保 `results/` 目录下的 JSON 文件格式符合要求
3. （可选）添加一个简单的网页展示 `index.html`

## 触发方式
- 自动：每天北京时间 20:00
- 手动：在 GitHub 仓库的 **Actions** 选项卡点击 **Run workflow**

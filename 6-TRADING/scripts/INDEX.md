# 📜 自动化脚本索引 (6-TRADING/scripts/)
> **排程**: Linux crontab — 零Token Python 执行
> **用法**: 全部由 crontab 自动调度，人工干预需 `python3 <脚本路径>`

## 脚本列表

| 脚本 | 排程 | 职责 | 状态 |
|:---|:---:|:---|:---:|
| `v15_hourly_runner.py` | 每小时 | V15基线信号(CCXT/Gate.io→价格→RSI→信号) | ✅ 正常 |
| `a1_research.py` | 交易日01:00 | A1深度调研(零Token) | ✅ 正常 |
| `a4_validation_executor.py` | 每4h | A4技术指标验证 | ✅ 正常 |
| `dream_trade_exec.py` | 每8h | A5 OKX交易执行 | ⚠️ OKX不通 |

## 产物输出

| 脚本 | 产物路径 | 日志路径 |
|:---|:---|:---|
| `v15_hourly_runner.py` | `artifacts/v15/` | `logs/v15_cron.log` |
| `a1_research.py` | — | `logs/a1_cron.log` |
| `a4_validation_executor.py` | — | `logs/a4_cron.log` |
| `dream_trade_exec.py` | — | `logs/a5_cron.log` |

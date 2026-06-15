# Dreambuddy-V2 交易系统

## 关键路径
| 目录 | 用途 |
|---|---|
| `6-TRADING/scripts/` | 自动化脚本 (crontab) |
| `6-TRADING/skills/` | A 系列技能 |
| `6-TRADING/artifacts/` | 本地产物 |
| `.workbuddy/skills/boss-secretary/reports/trading/` | 主产物路径 |
| `.hermes/cron/jobs.json` | Hermes cron 配置 |

## A 系列
A1调研 -> A2第一性原理 -> A3战略 -> A4验证 -> A5执行 -> A6监控
A7实践论 | A8理论验证 | A9离场决策

## 调度
- Linux crontab: 零 Token (A1, A4, A5, v15)
- Hermes cron: AI 驱动 (A1-A6, A8, A9)

## 规则
1. OKX 命令必须带 `--profile dreamdemo`
2. 产物双通道: boss-secretary + 6-TRADING/artifacts/
3. 搜索默认 Tavily
4. 飞书: cli_aa95b2dee3b85bd1

## 服务器
- hermes (101.43.47.55), ubuntu, ~/Desktop/dreamv2.pem

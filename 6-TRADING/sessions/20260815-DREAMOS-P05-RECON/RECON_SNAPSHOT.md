# DreamOS P0.5 对账快照 — 2026-08-15 00:40 UTC

## 背景
调度器 8/14 12:30 后崩溃，23:20 重启后离场检查持续报告「0 个持仓」，
而交易所实际存在 3 笔空单 —— 账本↔交易所失联，持仓处于无主动管理状态。

## 根因（已验证）
| 层 | 事实 |
|---|---|
| 持仓所在 | Hyperliquid (api.hyperliquid.xyz)，钱包 0x81cA2cf3...（AGENT_C 与 AGENT_DREAM_OS 为同一钱包） |
| 调度器指向 | job 配置 `exchange="aster"` → ml_trade_service → fapi.asterdex.com |
| 网络 | fapi.asterdex.com 被墙（curl 000 / Connection reset）；api.hyperliquid.xyz 可达（HTTP 200） |
| 结果 | `_aster_fetch_positions()` 连接失败 → run_exit_check_all 返回 error dict → `_exit_check` 把 error 静默记成「0 个持仓」 |
| 附加 | env 中根本没有任何 ASTER_* 凭证（0 条），aster 路径本来就无法鉴权 |

## 交易所侧实况（00:21 UTC 快照）
账户权益 50.45 USDT | 可用 17.17 | 总名义 166.36 | uPnL ≈ -0.03

| 币种 | 仓位 | 开仓价 | 杠杆 | 名义 | uPnL | 交易所 TP | 交易所 SL |
|---|---|---|---|---|---|---|---|
| ETH | -0.0359 | 1880.6 | 5x | 67.51 | -0.126 | 1817.4 | 1893.3 |
| SOL | -0.71 | 75.85 | 5x | 53.85 | +0.200 | 73.633 | 76.918 |
| ARB | -602.7 | 0.07465 | 5x | 44.99 | -0.108 | 0.0703 | 0.0762 |

（空头：TP/SL 均为 buy-side reduceOnly 保护单，6 张齐全 ✓）

## 修复内容
1. **scheduler_jobs.json**: scan_main / exit_check `exchange: aster → hyperliquid`
2. **scheduler.py B1**: backtest/optimize 任务硬编码 Mac 路径
   (`/opt/anaconda3/bin/python3` + `/Users/zhangjiangtao/...`) → `sys.executable` + `Path(__file__)` 推导（跨平台）
3. **scheduler.py B2**: `_exit_check` 对 error 结果显式 WARNING 告警，不再静默记为「0 个持仓」

## 修复后验证（00:36 UTC）
- ✅ `离场检查完成: 3 个持仓, 0 个离场, tpsl更新=3`
- ✅ TP/SL 动态维护恢复: ETH SL=1904.30 TP=1833.21 / SOL SL=77.08 TP=73.39 / ARB SL=0.077 TP=0.070（action=modify）
- ✅ 交易所挂单复核: TP 三张已更新为新值；SL 保持原更紧值 —— 符合 modify_tpsl 棘轮保护（空头 SL 只向有利方向移动），行为安全
- ✅ scan 市场数据恢复: `BTC A5正常执行 | path=full_sacg entry=63134.5`（修复前 entry=0）
- ✅ backtest_evaluation / orchestration_optimize 恢复运行（Mac 路径修复生效）
- ✅ dry_run=true 保持不变: 不会真实开/平仓，真单执行仍需专项审批

## 当前状态
三笔空单已恢复主动管理（30 分钟一轮离场检查 + 交易所保护单动态维护）。
真实平仓执行权仍锁定（dry_run=true），待「真单解锁审批」后开启。

## 遗留问题（不阻塞）
- DeepSeek API 余额不足（http_402）→ LLM 分析降级 NoOp，走经典分析兜底（设计内降级）
- Tavily key 失效（已知网络限制）→ 基本面模块走 Mock/免费源
- v15_state.json（14-V15 老系统账本）与本 Hyperliquid 账户为两套体系，不在本次对账范围

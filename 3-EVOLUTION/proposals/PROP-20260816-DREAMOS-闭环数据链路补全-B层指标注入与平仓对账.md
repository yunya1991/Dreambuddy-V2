# PROP-20260816 — DREAMOS 闭环数据链路补全（B层指标注入 + 交易所平仓对账）

- 日期: 2026-08-15
- 类别: 系统升级（代码改动，影子模式内，零真单）
- 状态: ✅ 已批准（2026-08-16 用户飞书直接指示"直接落地修复吧"）→ ✅ 已实施（commit 6aa6719，2026-08-16）
- 来源: 2026-08-15 四大闭环实盘验证（FOUR_LOOP_VERIFICATION_20260815.md）发现 F-1/F-2

## 背景

PROP-20260815 闭环接线后实盘验证确认：四层物理导通、运转正常，但两条数据链路缺口使 B 层信号与 E 层反馈处于降级状态。

## 提案内容

### P1: B 层指标注入（修复 F-1）
F 层 orchestration_cycle job 在调用 run_cycle 前，为每个币种补充指标数据：
- 拉取 K 线（hyperliquid candles API，已在 AutoTrader._fetch_market_data 中有实现，复用）
- 计算并注入: ma5/ma10/ma20、momentum_direction、trend_strength、volatility、volume_ratio、price_position、四维评分（复用 scan 链路的评分函数或简化版）
- 验收: 不同币种的卦象/方向/置信度出现分化（对照实验已证明引擎判别力正常）；K线拉取失败时降级当前行为（默认值 HOLD），不阻塞周期

### P2: 交易所侧平仓对账（修复 F-2）
exit_check 增加持仓快照对账：
- 每次 fetch 后保存持仓快照；下一轮发现快照中的持仓消失 → 查询交易所成交历史（或账户 balance delta）确认真实平仓价 → 构造 real_fill 结果回填 P1-3 认知闭环
- 验收: 模拟 SOL 被交易所 TP 平仓场景（测试环境），pnl 正确进入 record_real_exit，lessons 落盘

## 不动的部分（红线）
- V9 参数不动；14-V15 与 A 系列 cron 不动
- dry_run 门禁不动（仍零真单）
- 不触及 C 层解锁（另行审批）

## 风险
- P1 K线拉取增加周期耗时（6 币种 × 1 次 candles 请求，预计 <10s）；失败降级不阻塞
- P2 对账误判（手动平仓/部分平仓）→ 以交易所成交记录为准，查不到则记 estimated 不进认知

## 测试要求
- 新增测试 ≥4 个；全量回归 ≥55 全绿；测试与生产状态隔离（conftest）

## 实施结果（2026-08-16，commit 6aa6719）

### P1 落地
- 新模块 `capabilities/trading/market_enrichment.py`：从 `_fetch_market_data` 的产出（价格/EMA/RSI/ATR/48根1hK线）推导 ma5/ma10/ma20、momentum_direction、volatility、volume_ratio、price_position、trend_strength、四维评分（价格行为代理简化版，已声明）
- `cli/scheduler.py` orchestrate job 接入：AutoTrader 单实例复用，逐币 enrich 后 run_cycle；失败降级不阻塞
- **实测验收（真实行情）**：5 币种信号分化 —— AVAX tech=0.30→HOLD 0.0985（Dui_58→Kun_47）、LINK mom=UP→LONG 0.1457、BTC LONG 0.1493、SOL LONG 0.1555、ETH LONG 0.1054；修复前全部相同 HOLD 0.1312 ✅

### P2 落地
- `cli/auto_trader.py`：run_exit_check_all 每次巡检保存持仓快照（SNAPSHOT_DIR 类属性，conftest 隔离）；快照 diff 发现消失持仓 → userFills 查 closedPnl≠0 成交 → 加权均价回填 `_feed_cognitive_loop(px_source=real_fill)`；确认不到只记日志不喂认知
- 快照 ts 保留首次观察时间（对账窗口起点不漂移）；基线快照已写入：SOL SHORT 2.15 @ 75.4246
- 调度器已重启加载新代码（单实例 PID 1825634，5 jobs loaded）

### 测试
- 新增 10 例：test_market_enrichment.py（5，含多空分化闭环证据）+ test_p2_position_reconciliation.py（5）
- 全量回归 65 passed ✅；conftest 新增 SNAPSHOT_DIR 隔离，测试不触碰生产 scheduler_data

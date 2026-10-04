---
name: "dream-backtest-verify"
description: "Orchestrates 5-step post-hoc backtest verification: load trades → fetch klines → run detector gate → rebound attribution → value report. Invoke for backtest verification of trading subsystems (BDSM/BCRM/strategy/evolution/washout)."
version: 1.0.0
created: 2026-09-22
updated: 2026-09-22
license: Internal
status: active
category: orchestration
triggers: [事后归因, 回测验证, 价值评估, backtest verify, 验证子系统价值, 止损反弹率, 触发门召回率]
depends_on: [bcrm2.data_fetcher, washout_trigger_gate, washout_detector]
provides: [backtest-verify-orchestration]
cognitive_links: [VM-1790008785279-4f8e9a51, VM-1789994567129-791d228a]
---

# Dream Backtest Verify

事后归因回测验证流程 — 对已平仓止损交易进行后视归因分析，验证交易子系统（如洗盘判定、BDSM、BCRM、战略层、自进化）的价值。

## 触发词

「事后归因」「回测验证」「价值评估」「backtest verify」「验证 子系统 价值」「止损反弹率」「触发门召回率」

## 何时调用

- 用户要求验证某个交易子系统的实际价值
- 子系统已落地（代码 + 测试 GREEN）但未实盘积累足够案例
- 案例库为空导致 KNN/Bayesian 路径无法验证，需要替代验证方案
- 需要评估"避免被扫损"类防御系统的有效性

## 5 步流程

### Step 1: 加载历史交易记录

数据源：`.workbuddy/trade_index/all_trades_index.jsonl`（jsonl 格式，每行一笔交易）

字段：`trade_id, coin, inst_id, direction, entry_price, exit_price, entry_time, exit_time, pnl, pnl_pct, exit_reason, confidence, source_system, strategy_source`

过滤规则：
- 按 `exit_reason` 关键词过滤目标样本（如止损出场：含 `STOP_LOSS`）
- 完整性过滤：`entry_time` 非空 + `exit_time` 非空 + `entry_price > 0` + `exit_price > 0`
- FAIL-OPEN：单条记录解析失败跳过，不中断

### Step 2: 拉取 K 线数据

使用 `bcrm2.data_fetcher.get_klines(symbol, timeframe, max_bars)`，OKX API 内置 fallback 链路（本地缓存 → OKX history-candles）。

**关键 bug 教训**：OKX `history-candles` 的 `before` 参数返回的是"比锚点新的最新一批"而非紧接其后，必须用前移游标 + `after` 参数正确拉取锚点后窗口。

拉取策略：
- **触发门判定**：用 1D 周期拉取 250+ 根（覆盖 MA200 + 30 天回看）
- **后视反弹验证**：用 1H 周期拉取 exit_time 后 48-50 根（覆盖 48 小时）
- `inst_id` 构造：`{coin}-USDT`（data_fetcher 内部自动 fallback 到 `-USDT-SWAP`）
- 每条交易之间 `time.sleep(0.5)` 避免限频

### Step 3: 运行触发门/检测器判定

对每条交易，用 entry_time 之前的 K 线作为输入，运行目标子系统的触发门或检测器：

```python
from bcrm2.washout_trigger_gate import WashoutTriggerGate
gate = WashoutTriggerGate(require_above_ma200=True)
activated = gate.should_activate(daily_df)
```

记录：`trigger_activated` (True/False)

**FAIL-OPEN**：任何单条交易拉数据或判定失败，跳过该交易继续下一条。

### Step 4: 后视归因（止损后价格反弹判定）

对每条止损出场交易，用 exit_time 之后的 K 线验证价格是否反弹：

- **方向感知**：long 止损看 `max_high >= entry_price`；short 止损看 `min_low <= entry_price`
- **24h 反弹**：exit_time 后 24 小时内价格回到 entry_price（说明是洗盘扫损）
- **48h 强反弹**：exit_time 后 48 小时内价格不仅回来还盈利 2%+（long: `max_high >= entry_price * 1.02`；short: `min_low <= entry_price * 0.98`）

记录：`rebound_24h` (True/False), `rebound_48h_strong` (True/False), `max_high_24h`, `max_high_48h`, `min_low_24h`, `min_low_48h`, `adverse_move_pct`

### Step 5: 输出价值评估报告

**统计指标**：
- 触发门激活率 = 通过触发门的交易数 / 样本数
- 止损后 24h 反弹率 = 反弹的交易数 / 样本数（说明是洗盘扫损）
- 止损后 48h 强反弹率 = 强反弹的交易数 / 样本数
- 潜在价值 = Σ(|pnl_pct| for rebound_24h=True 的交易)（避免被扫损的损失）
- 误判风险 = Σ(|pnl_pct| for rebound_48h_strong=False 的交易) - 已实现损失
- 净价值 = 潜在价值 - 误判风险

**输出文件**：
- 明细 CSV：`{subsystem}_backtest_result.csv`
- 汇总 JSON：`{subsystem}_backtest_summary.json`

**报告模板**：
```
=== {子系统名} 事后归因回测报告 ===
样本数: N 条止损出场交易
触发门激活率: X/N (X%)
止损后 24h 反弹率: X/N (X%)  ← 说明是洗盘扫损
止损后 48h 强反弹率: X/N (X%)
{子系统} 潜在价值（避免被扫损的损失）: +X.XX%
{子系统} 误判风险（继续下跌的额外损失）: +X.XX%
净价值: +X.XX%
```

## 评估结论模板

| 维度 | 判定 |
|------|------|
| 价值主张验证 | 反弹率 ≥ 70% → 洗盘现象真实存在 |
| 触发门召回率 | ≥ 50% 可用；< 20% 需要优化触发条件 |
| 触发门精度 | 通过触发门的交易中反弹比例 ≥ 80% 为佳 |
| 净价值 | > 0 正面；> 50% 高价值；< 0 负面 |

## 关键约束

1. **FAIL-OPEN 铁律**：任何单条交易失败不中断整体流程
2. **方向感知**：long/short 止损的反弹判定方向相反
3. **OKX API 限频**：每条交易之间 sleep 0.5s
4. **数据完整性**：过滤 entry_price=0 或 entry_time 为空的记录
5. **K 线周期匹配**：触发门用 1D（MA200 + 30 天回看），后视反弹用 1H

## 复用场景

- BDSM 三层矛盾感知算法的回测验证
- BCRM2.0 仓位连续性观测器的回测验证
- 战略层五计庙算的回测验证
- 自进化系统 probe 仓阈值的回测验证
- 任何"避免被扫损"类防御系统的回测验证

## 配套认知闭环

- 任务前 `recall`（硬约束，检索相关经验）
- 任务中执行本 SKILL
- 任务后 `record`（记录本次经验，tags 含「backtest-verify」）
- 任务后 `verify`（如本次验证了已有记忆）
- 任务后 hermes 反思（评估是否衍生新 SKILL）

## 已落地的协作编排 SKILL 体系

| SKILL | 触发词 | 状态 |
|-------|--------|------|
| dream-qwen-eval-collab | 千问评估/二轮评估/回送千问 | v1.0.0 ✅ |
| dream-research-workflow | 深度调研/市场调研/技术调研 | v1.0.0 ✅ |
| dream-tdd-dev-workflow | TDD 开发/红-绿-重构 | v1.0.0 ✅ |
| dream-bugfix-workflow | bug 修复/根因分析/5why | v1.0.0 ✅ |
| dream-eng-mgmt-workflow | 工程管理/排期/里程碑 | v1.0.0 ✅ |
| dream-backtest-verify | 事后归因/回测验证/价值评估 | v1.0.0 ✅ |

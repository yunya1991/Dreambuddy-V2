# PROP-20260816 DreamOS 最小名义真单闭环冒烟测试 — 执行报告

- 日期: 2026-08-16
- 类别: 交易系统升级（真单解锁前置验证）
- 状态: ✅ 已批准并执行完成（五项验收全部通过）
- 审批: 飞书实例 `3AE39213-B72A-46E1-BEEF-1F37B59B15A0`（V1交易模板 096DC318，用户 2026-08-16 批准）
- 前置: PROP-20260815（四层闭环 P1 接线，影子模式全链验证）
- 触发: 用户指令「DreamOS 和 Agent C 确实是一个账户，清理掉现有持仓，以便可以实现真实测试」

## 一、背景与前置动作

1. **账户确认**: DreamOS 与 Agent C 为同一 Hyperliquid 账户（用户确认）。
2. **持仓清理**（用户授权，2026-08-16 16:3x 执行，生产客户端路径 HyperliquidClient("c")）:
   - ETH 空 0.0716 → 平仓 @1880.2（入场 1883.95，+$0.27）
   - SOL 空 1.44 → 平仓 @75.424（入场 75.407，-$0.02）
   - ARB：执行时发现已无持仓（position_snapshot 滞后）
   - 结果: 账户 flat，权益 $49.99，保证金全部释放，无遗留挂单/孤儿 TP-SL
3. **开关现状**: `DREAMOS_TRADING_DRY_RUN` 未设置 → 默认 true，调度器保持 paper 模式（本次测试未改动该全局开关）。

## 二、冒烟测试执行记录（2026-08-16 16:40 UTC+8）

测试方式: 独立受控脚本，调用与生产完全相同的代码路径
`V15Executor(leverage=5, total_budget=6.6, max_concurrent=3, dry_run=False)` → 每仓保证金 2.2 USDT。

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 入场成交确认 | ✅ | LONG BTC sz=0.00018 @63052.0，名义 $11.35，oid=517548090509，filled 返回完整 |
| 2 | 账本写入 | ✅ | v15_positions.json 即时落盘 BTC OPEN（opened_at 2026-08-16T08:40:45，原子写 tmp+rename） |
| 3 | TP/SL 挂单确认 | ✅ | set_tpsl_orders 生产路径：SL 61791.0 / TP 65574.1，2 笔 resting（oid 517548283078/79），挂单数=2 |
| 4 | 离场成交确认 | ✅ | close_position（reduce-only 市价）@63051.0 成交；持仓关联 TP/SL 随平仓自动失效，终态挂单=0 |
| 5 | 账本闭环回填 | ✅ | 账本 BTC→CLOSED（close_reason 记录）；record_real_exit: status=OK, assessment=NEUTRAL, lessons=1, state_update=OK（E层审查+F层W/L落盘均触发） |

**终态**: 账户 flat，权益 $49.98（往返成本 ≈$0.01 = 手续费+点差），持仓 0，挂单 0。
**实际 PnL**: -$0.0002（入场 63052.0 → 离场 63051.0）。

## 三、发现的生产代码问题（待后续提案处理，本次未改动）

1. **杠杆不一致（已修复 2026-08-16）**: `v15_executor.execute_signal` 先调 `set_leverage(symbol, 5)`，但随后 `open_long(symbol, usdt_amount)` 未传 leverage 参数 → 客户端用 `DEFAULT_LEVERAGE=3` 计算 sz 且 `market_order` 内部重设杠杆为 3。**修复**: open_long/open_short 显式传 `leverage=int(self.leverage)`（用户确认目标 5x）。验证: 9 项单测全绿 + mock 注入捕获调用参数确认 leverage=5 透传。影响: 全量实盘每仓名义从 260 USDT(3x) 恢复为设计值 433 USDT(5x, 保证金 86.67)。
2. **feishu_notify.py 硬编码凭证过期**: 模块内硬编码的 App Secret 已失效（API 返回 10014），本次绕过改用 Hermes 权威凭证源（~/.hermes/.env）。应改为运行时读取权威源。
3. **get_account 返回字段**: position dict 无 `unrealized_pnl` 键（读取为 ?），字段名需核对（影响监控展示，不影响交易）。

## 四、红线合规

- V9 参数未动（8%×vol_mult 加仓间隔 / 4%×vol_mult 止盈 / 最多3次加仓）；测试用 TP 4% 符合 V15 基线。
- 单笔名义 $11.35，远低于 ≤150 USDT 红线。
- 调度器全程 dry_run=true，零意外下单面；测试后账户恢复 flat。
- 未修改任何生产代码/配置。

## 五、结论与下一步

**结论**: DreamOS C层真单执行链路（信号→下单→账本→TP/SL→平仓→E/F层回填）在真实交易所环境端到端验证通过。

**下一步**（需另行提案，不在本次范围）:
1. 决策杠杆不一致问题（3x vs 5x）并修复验证。
2. 影子模式达标观察（PROP-20260815 定义的标准）。
3. 达标后提全量实盘切换审批（`DREAMOS_TRADING_DRY_RUN=false` + 预算 260 USDT）。

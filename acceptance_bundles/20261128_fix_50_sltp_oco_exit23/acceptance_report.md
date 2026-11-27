# 验收报告：50 域 SL/TP 类别化 + OCO 成交回写 + exit23 归属隔离

## 基本信息
- 验收对象：云端 23/50 域「刚开空单很快被平仓」根因修复
- 验收时间：2026-11-28 01:25 (Asia/Shanghai)
- 验收人：AI
- 关联 commit：`78d05dac9`
- 云端部署：`dreambuddy-remote` HEAD = `78d05dac9`，`dreambuddy-exit23.service` 已重启（ActiveEnterTimestamp 2026-11-28 01:18:58 CST）

## 修复内容
1. `22-执行引擎中心/x1_live_executor.py`：SL/TP 改为 `live_symbols.json → sl_tp` 解析（决策声明 > 标的 > 类别 > 默认），替换全局硬编码 1.5%/3.0%。
2. `22-执行引擎中心/position_ledger.py`：reconcile 查到真实平仓成交时以 `exchange_sltp` 回写，并保留原归属 `source/domain`（50-nn 不再被记成 `ghost_stale`/`22-reconciled`）。
3. `23-.../scripts/exit_runner.py`：`--symbols` 只补录账本未知老仓，不再按标的名单接管其他域（50-nn）的持仓。

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 症状复测 | ✅ | `repro_after.log` 3 条 observed：SL/TP 解析 3.0/6.0（原 1.5/3.0）；reconcile `exit_reason=exchange_sltp source=50-nn`；exit23 checked 2→1 | 云端真实运行 |
| 日志证据 | ✅ | `/home/luke/logs/yijing/exit23.log`：重启后 `巡检完成 checked=1`（50-nn 的 XAG 不再被纳入）；云端 reconcile 输出 `exit_reason=exchange_sltp source=50-nn` | 强制项 |
| 回归测试 | ✅ | `test.log`：43 passed，`exit=0` | 22 域 33 + 23 域 10 |
| 影响面 | ✅ | `fix.diff`：仅 7 文件（3 源码 + 1 配置 + 3 测试），与方案一致 | 无方案外改动 |
| 边界验证 | ✅ | 决策自带 sl/tp 覆盖（1.2/2.4）；查不到成交时保持 `ghost_stale`+`22-reconciled`；来源不匹配仓位不被 23 接管 | 3 场景全通过 |

## 已知残留（非本次范围）
- 存量仓位仍沿用旧 1.5% OCO 保护，需自然到期/止损或手工重挂。
- `22-执行引擎中心/tests/test_ledger_janitor.py::test_j2` 为存量失败（git stash 验证与本次改动无关），未纳入本次范围。

## 验收结论
- [x] 五维全通过 → 验收通过
- [ ] 有红旗 → 验收不通过

## 签字
AI 验收：2026-11-28

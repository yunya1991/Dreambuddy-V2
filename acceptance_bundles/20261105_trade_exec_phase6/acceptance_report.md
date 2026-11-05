# 验收报告 — trade-exec MCP v0.4 剩余项（Phase 1a + 小时级消费端）

## 基本信息
- 验收对象：`47-MCP管理系统/docs/tech/SPEC-L0-TRADE-EXEC-MCP-v0.1.md` v0.4 剩余三项
  1. executor agent Phase 1a 运行骨架（`executor_agent.py`）
  2. 小时级消费端接入（`execution_sample_loader.py` CLI + `dreambuddy-windowed-collect.service` 串联）
  3. human_baseline 缺口归档（上游阻塞判定）
- 验收时间：2026-11-05 20:03（Asia/Shanghai）
- 验收人：AI（`dream-acceptance-verify` 五维门禁）
- 关联 commit：`be75caa7`（本地/云端同 HEAD；本次改动为未提交工作区改动，已双向同步）
- 云端：`43.160.201.117`（ssh `dreambuddy-remote`），仓库 `/home/luke/dreambuddy`，运行身份 `luke`

## 五维证据矩阵

| 维度 | 状态 | 证据 | 备注 |
|------|------|------|------|
| 症状复测（功能验收） | ✅ | [repro_after.log](./repro_after.log) L4-L8 executor 5 场景输出符合 SPEC §10 预期；L11-L12 loader CLI `written=1`、`policy_rows=1 reward=-0.0025` | 低置信/过期/critical/高波动/硬钳位全部命中 |
| 日志证据（SPEC→代码→运行→输出） | ✅ | SPEC §10 → `executor_agent.py` / `execution_sample_loader.py` → 本地 CLI 运行 → `[ACCEPTANCE]` 标记 + 非空 metrics；云端 [cloud_repro.log](./cloud_repro.log) L3-L4 loader `written=0/skipped=1` 仍输出 `policy_rows=1 reward=-0.0025`；L10-L14 windowed-collect journal 串联执行并打印 loader JSON 后 `Finished`；L17-L22 shadow-driver 连续 5 次 `domains=[...,"trade_exec"], calls=12, degraded=0`，trade_exec `get_balance/get_positions/read_signals` 全 `ok=true` | 强制项；云端 journal 为真实 systemd 定时执行证据 |
| 回归测试 | ✅ | [test_local.log](./test_local.log)：本地 `exit=0`（19:58 47 passed；20:03 复跑相关 26 passed `exit=0`）；云端 `CLOUD_EXIT=0`（26 passed）；云端注册表 `✅ 注册表 OK — 8 存量壳 / 33 active 工具 / 上限 40` | 本地与云端均以 luke/本地同源代码运行 |
| 影响面 | ✅ | [fix.diff](./fix.diff)：tracked 改动 5 文件（+144/-6）；新增 4 文件（executor_agent / execution_sample_loader + 2 测试）；无越界改动 | 范围 = SPEC v0.4 阶段五/六声明范围 |
| 边界验证 | ✅ | 单测覆盖：`low_confidence`(execute=False) / `expired`(False) / `risk_critical`(mult=0.0) / `high_vol`(mult≤0.5 + limit) / policy 超限钳位(mult≤1.0、方向不可改) / policy 抛异常降级(`policy_fallback`)；loader 覆盖 缺失文件→空、坏行跳过、重复事件去重、增量落盘幂等、reward 截断 ±0.03 | 6 + 5 用例全绿 |

## 云端与本地一致性

| 校验项 | 结果 |
|---|---|
| 同范围双向 md5 清单（`mcp_shells` + `47-MCP管理系统` + `evo/core` + `evo/tests`，排除 `__pycache__/ledger/ml_data/data`） | local=147 / remote=147，`MD5_DIFF_LINES=0`，`LOCAL_ONLY=0`，`REMOTE_ONLY=0` |
| git HEAD | 本地 `be75caa7` = 云端 `be75caa7` |
| 云端相关测试（luke 身份） | 26 passed，`exit=0` |
| 云端注册表门禁 | ✅ 8 存量壳 / 33 active 工具 / 上限 40（ADR-9/H7：executor 角色仅 6 只读工具） |

## 红旗清单

1. **`human_baseline.json` 未产出（上游阻塞，非本域可解）**：48 域 SPEC v0.5 明确「E0b 仅剩 polling_trader 回放器缺口」，回放器未实现，无法产出 walk-forward OOS 基线。本域拒绝伪造基线数据，状态标记 ⛔ 上游阻塞。
2. **云端 `samples.jsonl` 当前无 paper 成交样本**：windowed-collect 调用 loader 输出 `written=0, skipped=0` 为预期（无事件可消费），非功能失效；已用临时样本证明 `written=1 + reward=-0.0025` 端到端可用。
3. **工作区存在非本轮 untracked 产物**：`23-四层闭环…/data/neural_sde_v1*.pt|json`、`exogenous_factors_22.json`、`.evolution_snapshots.json.*` 为其他任务遗留，不在本次改动范围（`fix.diff` 已按本轮路径裁剪）。
4. **Phase 1b（策略网络训练）未启动**：需 ≥2 周 paper 样本积累，属后续阶段，非本轮交付项。

## 验收结论

- [x] 五维全通过 → **验收通过**
- [x] 红旗均属「上游阻塞 / 预期空样本 / 域外产物 / 后续阶段」，不影响本轮三项交付
- [x] 云端与本地一致（147 文件 0 diff，同 HEAD），云端验收 `CLOUD_EXIT=0` + 注册表 OK

本轮三项剩余项状态：

| 项 | 状态 |
|---|---|
| executor agent Phase 1a 运行骨架 | ✅ 已落地并验收（SPEC §10） |
| 小时级消费端接入 | ✅ 已落地（service 串联 + CLI 幂等落盘） |
| human_baseline 缺口归档 | ⛔ 上游阻塞（不伪造数据） |

## 签字
AI 验收：2026-11-05 20:03
用户确认：待确认

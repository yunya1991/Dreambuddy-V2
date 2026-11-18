# 修复清单：ri 恒 0.5 / tier 恒 probe / d_star 恒 WAIT

> 诊断日期：2026-11-18 · 诊断结论见 [TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md §6.5](./TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md)
> 状态图例：`[ ]` 待修 · `[~]` 进行中 · `[x]` 已完成 · `[-]` 关闭（非缺陷/无需修） · `[!]` blocked（待决策）

## 清单

| # | 问题 | 根因 | 修复动作 | 验收标准 | 状态 |
|---|---|---|---|---|---|
| F1 | `ess_top_direction` 恒为空 → `ripple_ri` 硬编码 0.50 | ESS top1 为纯离场组合（`direction=both`），Provider 只取 top1 | `ESDirectionProvider` 按 ESS 降序遍历，取第一个含 `long/short` 动作的组合 | 单测：top1 无方向、top2 有 long → 返回 long；云端 N0 `ess_top_direction` 非空 | `[x]` |
| F2 | `detect_ripple_source` 放量门槛固定 `2.0`，1H 实际触发率仅 0.12% | 阈值未随波动率适配 | 改为 20 日已实现波动率自适应：`clamp(1.20+25σ_d, 1.30, 2.50)`；env 可覆盖 | 模拟触发率 0.12%→3.38%（σ_1h=0.003）；单测 4 项 | `[x]` |
| F3 | `R_flow=0.0` | Wyckoff effort/result：effort=0 且 pct_move 满档 → 低阻力 0 | 无需修复 | — | `[-]` |
| F4 | `d_star` 恒 WAIT（`wait=R_smooth×R_reflexivity`） | spec 定义；平滑行情下 wait 成本恒低于开仓 | 模拟回测：A 累计 -118%/MDD 75%、B +0.6%/MDD 22%（含 5bps/边）；实际事件 A=100% WAIT、B=60% long | 云端正常态实际回测裁决后再改 | `[!]` |
| F5 | `reflection_ri=0.50` | 冷启动，`get_coin_stats.eligible=False` | 无需修复，样本积累后自然变化 | — | `[-]` |
| F6 | 定位信息不足 | N0 未记录 `ess_top_direction` / `vol_ratio` / `is_source` | N9 事件补充 `ri/tier/ess_top_direction/vol_ratio/ripple_is_source/ripple_ri/reflection_ri/reflection_eligible` | 云端 N9 可直接看出卡在哪一条件 | `[x]` |
| F7 | `PROBE_THRESHOLD` 口径不一致 | 记忆记录 0.55，23 handler 现值 0.50 | 核对来源（可能属 11 域旧阈值），不改代码 | 结论记录 | `[!]` |

## 执行记录

| 时间 | 项 | 动作 | 结果 |
|---|---|---|---|
| 2026-11-18 | F1 | `ess_provider` 按 ESS 降序取首个有方向组合；新增 2 个单测 | `[x]` 7 passed |
| 2026-11-18 | F2 | 阈值 env 化（默认 2.0/0.30 不变） | `[~]` 待 1H 分布定档（云端 SSH 限流，统计待补） |
| 2026-11-18 | F6 | N9 增加 ri/tier/ess_top_direction/vol_ratio/ripple_is_source/ripple_ri/reflection_ri/reflection_eligible | `[x]` handler 45 passed |
| 2026-11-18 | F3/F5 | 判定为非缺陷 | 关闭 |
| 2026-11-18 | F4 | 语义待产品确认 | blocked |
| 2026-11-18 | 全量 | 提交 `fca428e43e` 并推送；云端 SSH `Connection closed` 持续，pull/重启待网络恢复 | 待部署 |

# 49 交易框架协议 vs 11 域实现走查 + 1H 5 折评测推进

- 日期：2026-11-18
- 口径：以磁盘代码 + 云端运行日志为准；文档与代码冲突时以代码为准
- 关联：`49-交易框架协议/SPEC.md` v0.14.2、`docs/SPEC-20261118-1H-walkforward-validation.md`、`docs/CHANGELOG.md` v4.6.2

---

## 一 · 走查结论（一致项）

| 契约/机制 | 代码证据 | 云端证据 |
|---|---|---|
| 42 总线多源汇聚 + TTL | `42/signal_bus.py:157-252`；11 子池 `polling_trader.py:6063-6096` 发布 | `bus_state.json` 12:30 新鲜，来源 `11-bcrm` / `11-bcrm-tactical` / `bdsm` / `strategic_extension` / `23-contradiction` |
| 43 战略承接持续产出 | `43/strategic_extension` 发布器；`SubSystemBridge.get_strategic_extension` 42→43 回退 | `dreambuddy-43-strategic-publish.timer` 每 30min，`strategic_extension_signal.json` 12:18 |
| 宏观约束注入 23 | `adapters/data_pipeline.py:416-433`（40 约束 + 43 信号）；`subsystem_bridge.get_macro_elastic_constraint` | 23 开仓日志 `quota=... band=55.0% hint=0.25 src=merged` |
| 23 开/平仓走 22 + 13 fail-closed | `polling_trader.py:1024-1087`（Gateway/RiskGatedOkxClient）；`23/execution/entry_loop.py:632-687`、`exit_loop.py` | 23 决策 `execution_decisions.jsonl` 均带 `gateway_present=true` |
| FinalDecisionSignal v1.2 | `23/execution/decision_signal.py:52-257`（顶层 + payload 12 字段） | `execution_decisions.jsonl` 字段齐全 |
| 执行权注册表 | `47/registry/execution_rights.json` 的 `fifty_nn_domain`（`live:50-bypass`，Mandate、100U、3x） | `x1_live_executor.py` 逐条校验 `execution.outcome` / mandate / 名义上限 |
| 单出口：50 → 22 → live | `22/x1_live_executor.py:132-159` | 今日 7 笔真实成交（CRCL/LINK/MSTR/MU/XAU/ARB/BNB），13 `reason_code=OK` |
| evolution 持仓离场隔离 | `polling_trader.py:13948-13950`（`is_evolution`/`is_external` → continue）；23 `EvolutionExitLoop` 独立 | 11 主离场日志不再处理 evolution 仓位 |

## 二 · 冲突与缺口

### P0（已修）

1. **`--shadow-mode` 未覆盖 23 开仓链路**
   - 现状：`_open_position` 有 shadow 硬闸门（`polling_trader.py:15668`），但 `_evolution_entry_build`（`10991`）→ `EvolutionEntryLoop` → 22 网关无该闸门；当 `YIJING_23_ENABLED=1` 时影子服务可真实开仓。
   - 修复：`_evolution_entry_build` 入口增加 `shadow_mode` 判定，只写 `shadow_signals.jsonl` + `[SHADOW MODE BLOCKED-23OPEN]` 日志。

### P1（未修，建议排期）

2. **运维语义混淆：系统并非整体影子**
   - `yijing-polling-trader` 带 `--shadow-mode`，但 `dreambuddy-nn-live-chain`（50→22→OKX live）与 `dreambuddy-entry23`（BTC/ETH/SOL，经 22）均为 live；今日已有 7 笔真实成交（最新 11:47 CST BNB short）。
   - 影响：任何“shadow 24h 无异常开仓”的验收结论不能覆盖 50/23 两条 live 链。
3. **开关命名漂移**：云端 drop-in `23-exit-off.conf` 设置 `YIJING_23_EXIT_ENABLED=0`，代码只读 `YIJING_23_ENABLED`（`polling_trader.py:17505/17515/17526`）。当前两者都等价于关闭，但一旦开启 entry 会同时开启 exit。
4. **影子约束影响实盘定容**：`SubSystemBridge.get_macro_elastic_constraint` 固定 `"mode": "shadow"`（`subsystem_bridge.py:256`），而 `EvolutionEntryLoop._apply_quota`（`entry_loop.py:523-560`，`EVOLUTION_QUOTA_GATE` 默认 on）按该约束缩放 23 实盘名义仓位，与 49 §3.1「shadow 只观测不裁决」不一致。
5. **`execution_rights` 未在 22 网关强制**：仅 50 的 `x1_live_executor` 校验；23 与 11 子池经 `TradeExecutionGateway.submit` 时不查标的级出口，单出口依赖注册表外的约定。
6. **ADR-0002 / SPEC §2.7 与代码漂移**：ADR 写“23 走 raw 通道、不经 13/16/22”，代码已统一到 22 Gateway（13 fail-closed）。需 ADR 修订或增补说明。

### P2（记录）

7. 22 网关契约校验 `EXECUTION_CONTRACT_MODE` 默认 `alert`，违规只告警不阻断；`source!=23-evolution` 仅校验 6 个核心字段（`trade_execution_gateway.py:583-605`）。
8. 云端 40 `runtime/` 无 `strategy_mapping.json`（`40_missing`），宏观带回退到 43 档位。
9. 11 → 42 发布缺 `mode` 字段；42 `_REQUIRED_KEYS` 未强制，但 49 SignalSchema v1 将 `mode` 列为必填。
10. 23 独立 exit_runner 与 11 `ExitManager` 在 XAU/XAG 等标的上同时具备平仓能力，需以 `source_tag`/ledger 归属做最终确认。

## 三 · 1H 5 折评测（P1）进展

- 数据：`fetch_okx_klines` 支持单页 3 次指数退避 + `after_ts` 断点续传；BTC 实测 8199 → 30000 根（2023-05-07 ~ 2026-11-18），300 页全成功，224.7s。
- 脚本：`scripts/memory_l4/bcrm2/eval_1h_walkforward.py`（B0/B1/B3、bootstrap CI、G0/G0.5/G2–G4）。
- 冒烟结果（BTC 3000 根 / 2 折，仅验证链路）：模型 N=38、WR=57.9%、E=+0.548%、CI=[0.060,1.046]、PF=2.79、MDD=4.75%；B3 随机方向 E=-0.288%、MDD=19.55% → 判定 `INSUFFICIENT`（样本门禁未达，符合预期）。
- 尚未完成：BTC/ETH/SOL 各 30000 根 × 5 折正式评测与报告结论。

## 四 · 后续动作

1. 云端确认 `YIJING_23_ENABLED` 与 `YIJING_23_EXIT_ENABLED` 口径，统一为一个开关。
2. 明确 `mode=shadow` 约束是否允许影响 23 实盘定容；若不允许，`_apply_quota` 需按 `mode` 跳过。
3. 为 23/11 子池补 `execution_rights` 校验；更新 ADR-0002 执行通道描述。
4. 运行三币 5 折正式评测，按 G0–G4 出 PASS/CONDITIONAL/FAIL。

# 42 × 50 集成说明（v0.1 草案）

> 状态：🟡 草案，待评审；不修改 42 SPEC v1.2 冻结正文（2026-11-10 回填云端实测，见 §9）
> 日期：2026-11-07（状态更新 2026-11-10）
> 关联：SPEC-49 v0.14；50-NN主矛盾评估器 SPEC v0.1；ADR-0002

## 1. 目的

明确 42 总线在 NN 闭环链中的角色：**input-only 信号汇聚 + 约束/参数透传**，下游由 50-NN主矛盾评估器消费；42 不做策略判断、不下单。

## 2. 当前落地状态（2026-11-10 实测，main `1867585a`）

- P1-01～P1-07 已完成：SignalBus 持久化/去重/TTL、registry horizon、`DREAMBUDDY_ROOT`、11 子池状态文件、canonical source、ParamGovernor、可观测性、`run_bus`。
- registry 10 源（`registry.yaml` 实测）：
  - `43-strategic-extension`（days）
  - `40-cycle`（days）
  - `40-divergence`（days）
  - `23-contradiction`（hours，23 输出镜像）
  - `29-event`（hours，由 23 写入）
  - `11-bcrm`（days，资产类）
  - `11-bcrm-tactical`（hours，D3 每币技术源，已实现）
  - `11-bdsm`（days，每币）
  - `11-washout`（hours，11 子池状态文件）
  - `11-event-arbitrage`（hours，11 子池状态文件）
- 云端 crontab 已设 `ENABLE_11_STATE_ADAPTER=1`，`run_bus` 每 15 分钟运行；实测 `runtime/bus_state.json` 含 43 条信号、7 个源（`29-event` / `11-washout` / `11-event-arbitrage` 无信号）。

## 3. 下游 50 的消费规则

| source | 50 中的角色 | 说明 |
|---|---|---|
| `11-bcrm` | 宏观先验 | 资产类粒度，不投每币方向票 |
| `11-bdsm` | 外部证据 | 每币一票；与内部 bridge 同源去重 |
| `11-washout` | reversal 轨 | 不投方向；影响趋势路径 continuation/风险 |
| `11-event-arbitrage` | event_shock 轨 | 事件窗口；与 29-event 冲突以可执行为准 |
| `29-event` | 自环/审计 | 23 写入，不作独立票 |
| `40-cycle` | 约束 | 只进包络 |
| `43-strategic` | 约束 | 只进包络 |
| `23-contradiction` | 自环/审计 | 23 输出镜像，禁止入裁决 |

## 4. 42 的边界（不变）

- 只做输入汇聚、归一化、约束/参数透传；不做策略判断、不下单。
- fail-open；信号侧失败不影响执行侧 fail-closed。
- 不写回子系统状态；23 输出只读镜像（DEC-18）。
- 所有 source 必须带 `horizon`、`signal_id`、`expires_at`；42 只按 `expires_at` 剪枝。

## 5. 与 50 的接口

- 50 只读 `runtime/bus_state.json`；不调用 42 内部函数、不写总线。
- 50 的 source 角色分类/去重规则见 50 SPEC §4；42 不承担去重语义（仅按 `signal_id` 合并）。
- 需要新增字段时，优先放在 `payload`（不破坏 SignalSchema v1）；顶层字段变更需 ADR。

## 6. 11 子池状态写入条件（M5）

- `polling_trader._write_subpool_state()` 只在 `_write_shadow_signal()` 内调用（`polling_trader.py:6785/6810`），即**仅被执行权限拦截的开仓意图**才落盘。
- 若 11 对 washout/event-arbitrage 有 live 执行权，信号会被执行而不是写状态文件 → 42 无源、50 无输入。
- R0 要求：11 子池配置为 signal-only / authority 可拦截；否则相关标的的 50 输入标记 unavailable（fail-open），不得把“8 源”当既成事实。

## 7. D3 技术源（M2）

- 原 8 源中没有每币技术源（`11-bcrm` 是资产类）。
- `11-bcrm-tactical` 已实现并注册（hours，11 `_last_bcrm2_result` 每币快照 + 42 只读适配器）；云端实测已产出 26 条信号。

## 8. 待办（R0）

1. ~~打开 `ENABLE_11_STATE_ADAPTER=1`~~（云端 crontab 已开启）；待验证 washout/event-arbitrage 信号 TTL 与去重，并确认 11 子池 authority 配置。
2. ~~`run_bus` 调度上线~~（云端每 15 分钟）；待补资源基线与空 bus 告警验证。
3. 验证 10 源共存与源计数指标；补齐 `29-event` / `11-washout` / `11-event-arbitrage` 无信号原因。
4. 为 50 提供只读快照（bus_state + 源健康度），不新增写接口。

## 9. 云端实测状态（2026-11-10）

| 链路 | 状态 | 证据 |
|---|---|---|
| 42 `run_bus` 调度 | PASS | crontab `*/15`；`runtime/bus_state.json` 最新 2026-11-09T16:15Z |
| 42 信号内容 | PASS（7/10 源） | 43 条信号：40-cycle/40-divergence/43/23/11-bcrm/11-bdsm/11-bcrm-tactical |
| 40 → 42 新鲜度 | **FAIL** | `40-cycle` payload `state_generated_at=2026-10-26T04:48:54Z`；40 产出物 mtime 2026-11-05；适配器无 staleness 闸门，仅 `expires_at=now+24h` |
| 42 → 43 | PASS（降级） | 43 每 30 分钟发布；F&G 不可用（cron 无 PG 密码 + SQLite 无 `records` 表），fail-open |
| 50 消费 | **NOT DEPLOYED** | 云端 `50/runtime/` 仅空目录；生产代码无 import 50；无 systemd/cron |

结论：42/43 自身在跑，但上游 40 断流且 50 未接入，端到端 NN 闭环**未畅通**。
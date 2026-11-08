# 42 × 50 集成说明（v0.1 草案）

> 状态：🟡 草案，待评审；不修改 42 SPEC v1.2 冻结正文
> 日期：2026-11-07
> 关联：SPEC-49 v0.14；50-NN主矛盾评估器 SPEC v0.1；ADR-0002

## 1. 目的

明确 42 总线在 NN 闭环链中的角色：**input-only 信号汇聚 + 约束/参数透传**，下游由 50-NN主矛盾评估器消费；42 不做策略判断、不下单。

## 2. 当前落地状态（2026-11-07，main `3422766`）

- P1-01～P1-07 已完成：SignalBus 持久化/去重/TTL、registry horizon、`DREAMBUDDY_ROOT`、11 子池状态文件、canonical source、ParamGovernor、可观测性、`run_bus`。
- registry 8 源：
  - `43-strategic-extension`（days）
  - `40-cycle`（days）
  - `23-contradiction`（hours，23 输出镜像）
  - `29-event`（hours，由 23 写入）
  - `11-bcrm`（days，资产类）
  - `11-bdsm`（days，每币）
  - `11-washout`（hours，11 子池状态文件）
  - `11-event-arbitrage`（hours，11 子池状态文件）
- `ENABLE_11_STATE_ADAPTER` 默认关闭（回滚路径）；R0 需打开并验证。

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

- 42 现有 8 源中没有每币技术源（`11-bcrm` 是资产类）。
- R0 新增 `11-bcrm-tactical`：11 `_last_bcrm2_result` 每币快照 + 42 只读适配器；无该源时 50 的 D3=neutral（降级可观测），不得用资产类信号冒充。

## 8. 待办（R0）

1. 打开 `ENABLE_11_STATE_ADAPTER=1`，验证 washout/event-arbitrage 信号 TTL 与去重；确认 11 子池 authority 配置。
2. `run_bus` 调度上线（按 horizon/频率）+ 资源基线。
3. 验证 8 源共存、空 bus 告警、源计数指标；新增 `11-bcrm-tactical`。
4. 为 50 提供只读快照（bus_state + 源健康度），不新增写接口。
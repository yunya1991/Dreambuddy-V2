# PLAN: NN 闭环链施工计划 v0.2（基于缺失项核查报告）

> 版本：v0.2
> 日期：2026-11-09
> 状态：待批准
> 关联：SPEC.md v0.3.0、SPEC-M1、SPEC-M2、SPEC-M3、PLAN-v0.1、REVIEW-20261109、缺失项核查报告（2026-11-09）
> 原则：**先止血、后接通、最后反射弧**；硬门禁 G1-G4 不可跳阶段。
> 本版变更：基于实际代码核查，修正 v0.1 中 R0-5/F1-F3/R1 的完成状态，聚焦剩余缺失项。

---

## 一、当前真实状态（已完成 vs 未完成）

### ✅ 已完成（有代码+测试证据）

| 工作包 | 节点 | 证据 |
|---|---|---|
| R0-1 | 40 日更流水线脚本 | `40/scripts/run_daily_pipeline.sh`（链序 p1→p4，失败接 15 告警） |
| R0-3 | shadow 解除条件预注册 | `43/strategic_extension/signal_publisher.py` `_shadow_gate_decision()` + 8 场景测试 |
| R0-5 | element_comparison 外发 | `signal_publisher.py` L202-207/L301 → payload `strategic_elements`；runtime 信号确认存在 |
| R0.5-F1 | source 命名统一 | `strategic_extension_adapter.py` 双写 + `mappings.py` SOURCE_ALIASES |
| R0.5-F2 | DEFAULT_DIMENSION=C7 + 权重归一 | `mappings.py` L91；w4/dominance 按 source 归一 |
| R0.5-F3 | 源年龄校验 | `path_synthesis.py` `_freshness()` L80-113（TTL 指数衰减，>2×TTL 丢弃） |
| R1-N1 | dimension_forces | `50/core/dimension_forces.py` |
| R1-N2 | contradiction（23 复刻） | `50/core/contradiction.py` |
| R1-N3 | 角色四分 + macro_force 权重表（G1 红线=0） | `mappings.py` MACRO_FORCE_SOURCES / SOURCE_WEIGHT_MAP |
| R1-N4 | 40-divergence 外发 | `42/adapters/cycle_state_adapter.py` `build_divergence_signal` |
| R1-N5 | 11 param_consumer | `11/scripts/memory_l4/param_consumer.py` |
| R1-N6 | 16 SSoT 版本戳 | `16/core/capital_allocator/constraint_envelope.py` |

**测试基线**：50 = 141 passed，42 = 75 passed，43 = 70 passed，11 N5 = 6 passed，16 N6 = 11 passed。

### ❌ 未完成（缺失项核查确认）

| 工作包 | 缺失项 | 阻塞门禁 |
|---|---|---|
| R0-4 | washout 激活（被 p3_sector_transmission 失败阻塞） | G1 |
| R0.5-F4 | degraded_events 统一审计流 | — |
| R0.5-F5 | direction_leak_check（constraint 通道剥方向） | — |
| R2-T1 | 三类矛盾对象（macro_micro_conflict / temporal_conflict / 维度间） | G2 |
| R2-T2 | bus_history 归档（42 run_bus 追加快照上限 500） | — |
| R2-T3 | pit_replay.py 历史重放 A/B 报告 | G4 |
| R2-T4 | resonance_matrix.py + Granger 检验 | G2 |
| R2-T5 | 矛盾去重规则（同标的同维度仅一个矛盾对象） | — |
| M2 | resonance_matrix.json 产出物、40-resonance 源注册、F_macro 四分量 | G2 |
| M3 | task_dispatcher.py、resonance_sensor.py、weight_profile 三档、trigger_flap | — |

---

## 二、不做清单（Scope Exclusion）

1. **不重做已完成项**：R1 N1-N6、F1-F3、R0-3/R0-5 已有代码+测试，不再返工
2. **不改 23 系统**：50 独立实现，不侵入 23 矛盾框架
3. **不碰实盘执行**：G3 未解除前 50 paper only，不接 13 下单链路
4. **不调权重阈值**：G4 未解除前 W6 不学习、权重不微调
5. **不新建独立 evidence.py/dedup.py/intent_tracks.py/horizon.py/constraints.py**：功能已内联于 path_synthesis/mappings/constraint_loader，仅需更新 SPEC §1 目录结构说明

---

## 三、剩余里程碑（按依赖顺序）

```text
M0 止血收尾（F4/F5 + R0-4 根因修复）
  └─> M1 宏观力传导底座（resonance_matrix + Granger + 40-resonance 注册）
        └─> M2 三类矛盾 + 时序裁决（T1/T5 + F_macro 消费）
              └─> M3 回放底座（T2 bus_history + T3 pit_replay）
                    └─> M4 反射弧（M3 task_dispatcher + resonance_sensor + weight_profile + trigger_flap）
```

每个里程碑独立可交付、独立验收；后续里程碑开工前必须确认前置门禁。

---

## M0 · 止血收尾（1-2 天，42/50/40 小改动）

**目标**：解除 G1 前提（washout 激活）+ 补齐 F4/F5 止血项，使降级可观测、防双重计数。

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| M0-1 | 修复 `p3_sector_transmission.py` 失败（exit=1），恢复流水线至 p4 | `40/scripts/p3_sector_transmission.py` | 手动跑 `run_daily_pipeline.sh` 全链成功 | 全链 exit=0；washout_verdicts.json generated_at ≤24h |
| M0-2 | 验证 washout 真实激活（非 unknown_fallback） | `40/scripts/p3_washout_integration.py` | 查 washout_verdicts.json | 至少 3 标的非 unknown（trigger 门设计如此，市场不满足时 unknown 属正常，关键是流水线跑通） |
| M0-3 | F4 degraded_events 落地：各降级点写 `42/runtime/degraded_events.jsonl` | 42/50/43 各降级点（首批 6 类：桥关闭默认值/source_stale/resonance_fallback/trigger_flap/dispatcher_down/washout_unknown/direction_leak_fail） | 注入降级事件 → jsonl 有记录 | jsonl 文件存在且含 ts/layer/source/reason/detail |
| M0-4 | F5 direction_leak_check：constraint_loader 剥方向 + 审计 | `50/adapters/constraint_loader.py` | 含 direction/net_bias 的 43 信号输入 → 钳位只取幅度，审计有 leak_check | per_asset_class 返回值不含 direction；degraded 含 direction_leak_check 结果 |

**M0 退出标准**：
- 40 流水线全链跑通（exit=0），washout_verdicts.json 刷新
- `42/runtime/degraded_events.jsonl` 存在且有记录
- constraint_loader 返回值不含方向性字段
- 50 全套测试 141+ 新增止血测试全绿
- **G1 解除前提满足**（washout 激活 + 宏观数据源稳定）→ macro_force 权重可从 0 解禁

---

## M1 · 宏观力传导底座（3-4 天，40 侧为主）

**目标**：产出 resonance_matrix + Granger 检验，为 M2 三类矛盾提供 R(s)/F_macro/t_arrive 数据。

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| M1-1 | 新建 `40/scripts/p3_resonance_matrix.py`：计算 R(s)={corr0, lag_profile, beta, down_corr}，基于 token_sequence.parquet | 新建 + `40/resonance_matrix.json` 产出物 | ETH/SOL 的 corr0/lag/beta 与原型复算一致 | resonance_matrix.json 存在，含全量标的 R(s) + generated_at |
| M1-2 | Granger 式检验：上游收益对标的未来收益的增量预测力（控制标的自相关后） | 同上，结果写入 resonance_matrix.json `granger_p` 字段 | p 值入文件；不显著的标的标记 | 每标的含 granger_p 值 |
| M1-3 | fail-open：样本不足/数据停滞 → R=恒等（corr0=1），审计 degraded=resonance_fallback | 同上 | 注入不足样本 fixture | degraded 含 resonance_fallback |
| M1-4 | 42 `cycle_state_adapter.py` 增读 resonance_matrix，随 40 信号 payload 外发 | `42/adapters/cycle_state_adapter.py` | run_bus 后 bus_state 含 resonance 字段 | 40 信号 payload 携带 resonance_matrix |
| M1-5 | 50 `mappings.py` 补全 `40-resonance` 源注册：MACRO_FORCE_SOURCES / SOURCE_WEIGHT_MAP / SOURCE_DIM_MAP / SOURCE_TF_MAP（当前仅 SOURCE_TTL_HOURS 有） | `50/core/mappings.py` | `role_of("40-resonance")="macro_force"`；权重表有 40-resonance | 四表均含 40-resonance |

**M1 退出标准**：
- resonance_matrix.json 日更产出，含 R(s) + granger_p
- 42 外发 resonance 字段
- 50 识别 40-resonance 源（role=macro_force）
- **G2 判定落档**：Granger 显著的标的 t_arrive 启用；不显著的 t_arrive 禁用 + 传导语义降级为"宏观因子暴露"

---

## M2 · 三类矛盾 + 时序裁决（3-4 天，50 侧为主）

**目标**：实现 SPEC-M2 §2.2 三类矛盾对象 + F_macro 消费 + 矛盾去重。

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| M2-1 | F_macro 四分量计算（D1/D2/D4/washout）：F_macro(s)=F_macro(upstream)×corr0×layer_gate | `50/core/dimension_forces.py` | fixture：BTC 龙头 F_macro 直传；ETH 按 corr0 衰减 | dimension_forces 输出含 F_macro 分量 |
| M2-2 | 三类矛盾对象生成：macro_micro_conflict / temporal_conflict / 维度间矛盾 | `50/core/contradiction.py`（扩展） | 三类 fixture 分别生成对应矛盾对象 | contradiction 输出含三类矛盾 type 字段 |
| M2-3 | horizon 分层裁决：≤1d 微观主导 0.7 / ≥5d 宏观主导 0.7 / 过渡带各半折置信 | 同上 | horizon 边界 fixture | 裁决权重符合分层规则 |
| M2-4 | t_arrive 到达窗口：微观方向在 t_arrive 前有效但置信度按 (1-(t_arrive-now)/lag) 衰减 | 同上 | t_arrive 前后 fixture | 置信度衰减曲线正确 |
| M2-5 | 矛盾去重：同标的同维度仅一个矛盾对象（有 lead-lag→temporal_conflict；无→macro_micro_conflict） | 同上 | 同标的同维度宏微观反向 fixture | 仅生成一个矛盾对象，无双重惩罚 |
| M2-6 | 维度间矛盾：D1 看多 vs D2 资金流出/D4 过热，复用 23 四维权重维度级裁决 | 同上 | D1×D2 反向 fixture | 维度间矛盾被识别 |

**M2 退出标准**：
- 宏观 long/微观 short fixture 下 50 输出含三类矛盾对象
- G2 判定结果应用（Granger 不显著的标的 t_arrive 禁用）
- 无双重惩罚（同标的同维度仅一个矛盾对象）

---

## M3 · 回放底座（2-3 天，42/50 侧）

**目标**：建立 bus_history 归档 + pit_replay 回放能力，为 G4（PIT≥200 决策）提供数据底座。

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| M3-1 | 42 `run_bus.py` 追加 bus_history 快照（上限 500 条，滚动覆盖，原子写） | `42/run_bus.py` | 连续 run 3 次 → bus_history 含 3 条快照 | `42/runtime/bus_history.jsonl` 存在，上限 500 |
| M3-2 | 50 决策落盘：每次 decision 输出追加到 `50/runtime/decisions.jsonl` | `50/core/decision.py` | 跑一次决策 → jsonl 有记录 | 决策含 ts/signal_id/direction/confidence/contradiction_ref |
| M3-3 | 新建 `50/tools/pit_replay.py`：读 bus_history 重放，输出 A/B 方向命中报告 | 新建 | 用 fixture bus_history 重放 → 输出命中率报告 | 报告含样本数/命中数/置信度分布 |

**M3 退出标准**：
- bus_history 滚动归档正常
- pit_replay 可跑通（即使样本不足 200 仅作工程验证）
- **G4 数据底座就绪**：decisions.jsonl 开始积累，目标 ≥200 条后解禁权重微调

---

## M4 · 反射弧（4-5 天，42/40/50 侧，依赖 M1-M3）

**目标**：实现 SPEC-M3 正向/逆向反射弧。

| # | 任务 | 改动位置 | 验证 | 退出标准 |
|---|---|---|---|---|
| M4-1 | 42 `task_dispatcher.py`：task schema/持久化（dispatch_tasks.jsonl）/去重/优先级 P0>P1>P2/P2 保底 60% 时间片/salience 配额 | 新建 + 测试 | 10 并发 fixture 无重复任务；P2 时间片统计 ≥60% | dispatcher 可用，P2 不饿死 |
| M4-2 | 龙头监控门（|F_macro|≥0.4 → P0 正向任务） | 42 或 40 侧 | 龙头信号 fixture → P0 任务生成 + P2 让渡日志 | macro_led 触发正常 |
| M4-3 | 40/43 `resonance_sensor.py` 服务化（SLA<60s，on-demand 计算 R/F_macro/t_arrive/regime_overlay） | 新建 | 任意标的请求返回完整 R/F_macro/t_arrive | sensor 可用，样本不足 degraded |
| M4-4 | salience 门（conf≥0.6 + 配额制每源 4h≤2 次 P1 触发） | 42 dispatcher | 微观高置信 fixture → P1 任务；第 3 次被配额拦截 | 配额生效 |
| M4-5 | 50 trigger/weight_profile 三档：默认 / macro_led(0.50-0.50) / micro_led(0.40-0.60) | `50/core/mappings.py` + `decision.py` | macro_led/micro_led fixture 分别产出对应 profile | 决策 payload 含 trigger/profile |
| M4-6 | micro_led regime_overlay 叠加裁决：trend→trend intent 优先；range→reversal 升权 | `50/core/decision.py` | trend/range fixture 分别产出对应 intent 偏向 | regime_overlay 影响裁决 |
| M4-7 | trigger_flap 防护：同一标的 4h 内 trigger 切换 ≤2 次，超出锁定上一 profile + 审计 | 同上 | 快速交替 fixture → 锁定 + 审计 trigger_flap | 防振荡生效 |

**M4 退出标准**：
- 正向反射弧：龙头信号 → P0 调度 → 微观 on-demand 计算 → macro_led 决策
- 逆向反射弧：微观高置信 → P1 调度 + sensor → micro_led 决策（含 regime_overlay）
- trigger_flap 防护 + P2 保底 60% 均生效

---

## 四、硬门禁汇总（违反即停工回退）

| 门禁 | 内容 | 当前状态 |
|---|---|---|
| G1 | R0 未完 → macro_force 权重=0 | ⏳ M0 完成后解除 |
| G2 | Granger 不显著 → t_arrive 禁用 | ⏳ M1 完成后判定 |
| G3 | 13 未接入 → 50 paper only | 🔴 未开始（M4 后 C1） |
| G4 | PIT <200 决策 → 禁调权重阈值 | ⏳ M3 完成后开始积累 |

---

## 五、首批开工项（批准后即刻）

**M0 止血收尾**（无架构风险，1-2 天可验）：

1. **M0-1** 修复 `p3_sector_transmission.py` — 先看日志定位失败原因，当天可修
2. **M0-3** F4 degraded_events 落地 — 新建 42 侧审计写入点，改动 <150 行
3. **M0-4** F5 direction_leak_check — constraint_loader 剥方向 + 审计，改动 <80 行

M0 完成后 → G1 解除 → 启动 M1。

---

## 六、风险与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| p3_sector_transmission 失败根因未知 | 阻塞 washout 激活 + G1 | 先查日志定位，可能是数据源/API 变更 |
| Granger 检验全量不显著 | t_arrive 全局禁用，时序矛盾退化为 horizon 规则 | 接受降级，M2 仍可落地 macro_micro_conflict + 维度间矛盾 |
| resonance_matrix 计算耗时超 SLA | sensor 服务化受阻 | 先离线日更，sensor 按需调用走缓存+异步 |
| P2 保底 60% 实现复杂 | dispatcher 开发延期 | 先用简单滑动窗口统计，后续优化 |

---

## 附录 A · 与 PLAN-v0.1 的差异

| v0.1 任务 | v0.2 状态 | 说明 |
|---|---|---|
| R0-1 恢复 40 调度 | ✅ 脚本已建，需修 p3_sector | 流水线存在但中途失败 |
| R0-2 开 43 桥 | ✅ 已完成（shadow 条件已预注册） | — |
| R0-3 shadow 条件文档化 | ✅ 已完成 | 代码即文档 |
| R0-4 washout 激活 | ❌ 被 p3_sector 阻塞 | 非 washout 逻辑问题 |
| R0-5 element_comparison 外发 | ✅ 已完成（strategic_elements 字段） | v0.1 表述为"未实现"系误判 |
| F1-F3 止血 | ✅ 已完成 | — |
| F4 degraded_events | ❌ 未实现 | M0-3 |
| F5 direction_leak_check | ❌ 未实现 | M0-4 |
| R1 N1-N6 | ✅ 全部完成 | — |
| R2 T1-T5 | ❌ 全部未开始 | M2/M3 拆分 |
| S1/S2 反射弧 | ❌ 全部未开始 | M4 |

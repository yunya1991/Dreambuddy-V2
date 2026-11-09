# SPEC-M1: 神经传递打通与 23 矛盾框架复刻（50-NN主矛盾评估器）

> 版本：v0.1（调研落地稿）
> 日期：2026-11-09
> 状态：🟡 设计态，待评审；**是对 SPEC.md v0.2.0 的修订增补，不覆盖其冻结条款**
> 关联：50 SPEC v0.2.0 §4（矛盾评估机制）、23 SPEC-主要矛盾识别与最小阻力路径设计、42×50 INTEGRATION-v0.1
> 调研依据：2026-11-09 全链路代码考古 + 代理回测（40 token_sequence 1D，BTC/ETH/SOL 各 295 根，EMA12 代理收益）+ 40/43 深度评审（v0.1 增补 R0）

---

## 零 · 问题陈述（代码实证）

### 零A · R0 级前置发现（2026-11-09 深度评审增补）：神经链的"脑"是死的

在谈角色/权重之前，40/43 深度评审发现**信号活性本身不成立**，这是比 B1-B5 更前置的问题：

| # | 问题 | 实证位置 | 影响 |
|---|---|---|---|
| R0-1 | **40 全流水线停滞 14 天**：cycle_state/asset_rotation/sector_transmission/fund_flow/strategy_mapping/washout_verdicts/meme_platform/stovall_breadth 的 generated_at 全部为 2026-10-26；全仓库无任何调度器/launchd 引用 p1-p4 脚本 | 40 各产出物 generated_at 字段 | 42 适配器每日照常把陈旧文件包装成 ts=当天 的信号发布（freshness=0.979），下游在消费"尸体数据" |
| R0-2 | **43 与 40 的桥默认关闭**：`CYCLE_STATE_BRIDGE` env 默认 False；40 cycle_state→天/地/将三维、fund_flow/washout→道维的承接映射代码已写好但从未生效。总线实测五维 dao50/tian59/di50/jiang50/fa50——四个 50 是 fail-open 默认值 | 43 `five_domain_feature_computer.py`（env 开关）；`cycle_state_adapter.py` L118-221；42 bus_state.json payload | **43 实际没有承接 40**；"40→43→50"链在 40→43 段已断开 |
| R0-3 | **43 shadow 硬编码 True**（signal_publisher.py L196/L218），且本地无 runtime 产出文件（信号由云端 11 侧产出回灌） | 43 `signal_publisher.py`；43/runtime/ 为空 | 43 信号永不参与裁决；16 capital_allocator 读的是同一来源 |
| R0-4 | 40 的 risk_guards.freshness 检测只在**生成时刻**计算（age_hours=9.9），消费时刻不重算；X1 未达标（80/100 样本）、P5/P6=REJECT → 周期判定从未被验证方向准确率 | 40 `strategy_mapping.json` risk_guards；`x1_metrics_status.json`；`p5_gate_status.json` | stale 防护设计存在但被绕过；宏观方向本身未经验证 |
| R0-5 | 43 的 `element_comparison` 会标注战略层 vs 40 分支视角的分歧作为"矛盾系统介入触发依据"（SPEC §11.3/12.2），但分歧结果未外发——与 40 divergence 内部消化同类病 | 43 `strategic_elements_deriver.py` L277 | 矛盾触发信号再次内部消化 |

**推论**：本 SPEC 的 M1-M9 全部建立在"40/43 在产出活信号"的假设上，该假设当前不成立。R0（信号活性修复）必须先于 R0.5 执行，且 R0 完成前禁止基于当前链路做任何权重/回测结论。

### 零B · 原始断点（v0.1 保留）

用户判断：**40/42 宏观弹性调控到 50 的神经传递断裂；50 应包含宏观vs微观、时序、力量三类矛盾，基于矛盾处理产出决策，而不仅是弹性约束**。实证确认 5 个断点：

| # | 断点 | 实证位置 | 影响 |
|---|---|---|---|
| B1 | `40-cycle`/`43-strategic` 角色=constraint，path_synthesis 直接丢弃，永不生成 path | 50 `core/mappings.py` L9；`core/path_synthesis.py` L184-187 | 宏观力量对 `w4.force` 贡献恒为 0 |
| B2 | source 三方命名不一致：50 认 `43-strategic`，42 registry 用 `43-strategic-extension`，42 实际发布 `strategic_extension`；50 别名表无后两者 | 50 `core/mappings.py` L62-72；42 `adapters/strategic_extension_adapter.py` L41 | 43 信号 `role=unknown`，以 C3/weight=0.05 混入投票（串线） |
| B3 | `force_score` 逐 path 累加 `weight×conf`，未按 source 归一；实测 11-bcrm-tactical 26 path×0.35=9.10，占总力量 87% | 50 `core/w4.py` L28-43；bus 实测 34 path | "外部权重和=1.0" 语义失效；裁决退化为币数投票 |
| B4 | 40 的 divergence（n_divergent=2/5）与 sector_transmission 分歧已在 40 内部产出，但 42 适配器只发 real_cycle+MA200 汇总 | 42 `adapters/cycle_state_adapter.py` L58-98；40 `asset_rotation.json` | 宏观内部矛盾不外发，50 无输入可对撞 |
| B5 | 新鲜度只校验总线 `expires_at`，不校验源数据年龄；40 状态 2026-10-26 生成、11-09 发布被算成 freshness=0.979 | 50 `core/path_synthesis.py` L77-93 | 14 天前宏观数据被当新鲜信号 |

结构性缺失：

- SPEC 列出的 `dimension_forces.py / contradiction.py / intent_tracks.py / horizon.py / constraints.py` **未实现**；`dominance.py` 只按 horizon 分组无跨层比较；w4 把 hours/days path 直接混算出一个全局 force。
- 实测有效维度仅 D3(29)/C6(4)/C3(1)，D1/D2/D4/C7/C8/NEWS 全为 0；`DEFAULT_DIMENSION="C3"` 不在 `VALID_DIMENSIONS` 内（硬 bug）。
- `make_decision` 无运行时入口，只在测试中被调用；`bus_state.json` 无历史快照 → 真实 PIT 回测不可能。

代理回测结论（局限：3 币 10 个月、EMA12 代理、代理指标替代真实 11 源）：

| 前视 H | 宏观(MA200) | 微观mom5 | 50/50融合 | 冲突子集胜者 |
|---|---|---|---|---|
| 1d | 0.567 | 0.780 | **0.811** | 微观(mom5) 68% |
| 5d | 0.556 | 0.718 | **0.744** | 宏观(state) 83% / 微观(mom5) 68% |
| 20d | 0.549 | 0.601 | **0.628** | — |
| 40d | 0.563 | 0.570 | **0.606** | — |

三个判断：①宏观方向含独立信息（54.5–56.7%，跨 H 不衰减）；②无条件让宏观压微观是错的，胜负取决于 horizon 与信号类型 → 需要**时序矛盾建模 + 分 horizon 裁决**；③50/50 融合全 horizon 优于纯微观（+2.6~3.6pp），当前 40 权重 0 确实在丢信息。

---

## 一 · 设计原则

1. **打通而非旁路**：40/43 从"仅约束"升级为**宏观矛盾力量（macro_force）**，与 11-* 微观力量在维度层对撞；约束包络职责保留且独立（钳位仍不进矛盾评分，SPEC §4.10 不变）。
2. **复刻而非依赖**：50 复刻 23 已验证的矛盾框架**设计口径**（共振检测→4维冲突裁决→主导性评估；C1-C8 维度对立面；力量对比量化；验证闭环），独立实现、不 import 23 运行时模块/状态（SPEC §0.2 隔离约束不变）。
3. **时序即矛盾**：23 的 C6 时序维度（短期看多↔长期看空）落地为 50 的一等矛盾类型，裁决按评估 horizon 分层，不做全局加权混算。
4. **fail-open 不变**：任何新输入缺失 → 对应维度 neutral + degraded 标注，不阻断决策。
5. **先止血后重构**：R0.5 修串线/归一/新鲜度，R1 才引入宏观力量与维度力量，R2 落地时序矛盾与回测底座。

## 二 · 复刻清单（23 → 50）

| 23 模块（成熟实现） | 50 新模块 | 复刻内容（设计口径，独立实现） |
|---|---|---|
| `core/contradiction_identifier.py`（PrimaryContradictionIdentifier） | `core/contradiction.py` | 三步法：①共振检测（≥0.6 方向一致度）②4维冲突裁决（力量0.40/紧迫0.15/一致0.25/影响0.20，50 已具 w4 雏形）③主导性评估（≥0.55）；次要矛盾权重降至 ≤0.3（重心原则） |
| `core/dimension_force_evaluator.py` + `core/dimension_mapping.py` | `core/dimension_forces.py` | 维度级多空两面对立：每维度独立计算多/空力量，输出 dimension_strength 与主方向；维度集合沿用 50 现有 D1-D4/C6-C8/NEWS，映射对齐 23 C1-C8（D1=C4 宏观利率、D2=C1 资金流、D3=C3 技术、D4=C2 情绪、C6=C1 估值、C7=C7 隐性、C8=C8 宏观交叉、NEWS=事件） |
| C6 时序维度定义（短期看多↔长期看空） | `core/temporal_conflict.py` | 见 §四 M6 |
| `core/dominance_resolver.py` | `core/dominance.py`（改造） | 跨 horizon 主导者评估：先维度内成对支配（同 horizon），再维度间 Copeland，最后时序矛盾裁决；保留 argmax shadow 回退标注 |
| 验证闭环（ShadowRL/回测回流矛盾权重） | `core/w6.py`（扩展样本） | 样本 schema 增加 `temporal_conflict_id / dimension / horizon`；回测与在线结果回流调整维度权重与宏观权重 |
| 矛盾强度调制 HJB lagrangian | 决策输出调制 | 主矛盾方向：resistance 下调、position_band 内取上限侧；次矛盾方向：resistance 上调、仓位折半；映射规则预注册，不做自由放大 |

## 三 · 角色与映射修订（R0.5 止血，M1-M3）

### M1 source 命名统一（canonical source 修订）

- 42 总线 canonical source 定为 **`43-strategic`**；42 适配器双写过渡（`SOURCE_ALIAS_MODE=1` 时同发 `43-strategic` 与旧名 `strategic_extension`，对齐 bdsm P1-05 先例）；registry name 同步改为 `43-strategic`。
- 50 `SOURCE_ALIASES` 增补：`"strategic_extension"→"43-strategic"`、`"43-strategic-extension"→"43-strategic"`（过渡期内容错，双写期结束后旧名进审计告警）。

### M2 角色四分（替代现有三分）

| 角色 | source | 50 内处理 |
|---|---|---|
| `micro_force`（原 external） | 11-bcrm-tactical / 11-bdsm / 11-washout / 11-event-arbitrage | 生成 path，参与维度力量 |
| `macro_force`（新增） | 40-cycle / 43-strategic / 40-divergence（新增源，见 M7） | 生成 path（D1/C4 维度，horizon=days/weeks），参与维度力量与时序矛盾 |
| `constraint` | 40/43 的**包络字段**（position_band/leverage_cap/asset_count_cap 等，走 constraint_loader，不经 bus evidence） | 只钳位，不进评分（不变） |
| `self_mirror` | 29-event / 23-contradiction | 只审计（不变） |

- 同一 source 可同时承担两角色：40-cycle 的**方向/置信度**进 macro_force，**包络字段**进 constraint；两条通道独立，互不污染。
- **双重计数防护（评审增补）**：constraint 通道字段必须是**方向中性的幅度量**（position_band/leverage_cap/asset_count_cap），禁止携带方向偏置；方向性内容只允许走 macro_force 通道。40 `strategy_mapping` 当前的建议字段含方向语义，进入 constraint_loader 前必须剥离方向（只取幅度），否则同一宏观信息在钳位和投票中被计两次。审计增加 `direction_leak_check` 字段。
- macro_force 权重预注册：`40-cycle=0.15 / 43-strategic=0.10 / 40-divergence=0.05`（合计 0.30）；micro_force 合计 0.70，按现有比例等比缩放（11-bcrm-tactical 0.245 / 11-bdsm 0.14 / 11-washout 0.105 / 11-event-arbitrage 0.105 / 11-bcrm 0.105）。W6 可学习，截断 [0.3,1.5] 不变。

### M3 权重按 source 归一 + 维度/默认值修复

- `force_score`（w4）与 `_strength`（dominance）改为：path 有效权重 = `source_weight / 该 source 当批 path 数`（按 (source) 归一，消除币数放大）；单 path 权重截断 [0, 1]。
- `DEFAULT_DIMENSION` 改为 `"C7"`（隐性/未分类，VALID_DIMENSIONS 成员）；C3 保留在 23 侧术语，50 内部统一 C7。
- D2/D4 当前无源：维度输出 `neutral + degraded=no_source`，impact_score 的覆盖度按有源维度计。

## 四 · 矛盾层落地（R1/R2，M4-M7）

### M4 dimension_forces.py（R1）

- 每维度独立聚合该维度所有 path：long_force/short_force（source 归一后权重×confidence），输出 `dimension_force = {dimension, direction, strength, path_count, degraded}`。
- 无 path 维度 → neutral，不参与 impact 覆盖度，审计标注。
- 禁止用资产类信号冒充每币 D3（SPEC §4.1a 既有约束保留）。

### M5 contradiction.py（R1，复刻 23 三步法）

输入：dimension_force 集合 + path 集合。输出：主矛盾对象。

```
primary_contradiction = {
  "type": "resonance" | "conflict",
  "leader_dimension": "D1" | "D3" | ...,
  "direction": "long" | "short" | "neutral",
  "strength": 0.0-1.0,           # 共振度或主导度
  "resonance": float,            # Step1
  "arbitration": {force, urgency, consistency, impact},  # Step2（复用 w4）
  "dominance_matrix": ...,       # Step3（复用 dominance）
  "secondary": [维度列表],       # 次要矛盾，权重 ≤0.3
  "temporal_conflicts": [...],   # M6
}
```

- Step1 共振检测：≥0.6 维度方向一致 → resonance 型主矛盾，strength=共振度。
- Step2 冲突裁决：共振 < 0.6 时，4 维评分（力量 0.40/紧迫 0.15/一致 0.25/影响 0.20，权重冻结沿用 SPEC §4.4）在**维度级**（非 path 级）计算，识别主导维度。
- Step3 主导性评估：主导维度力量占比 > 0.55 → dominant；否则输出 conflict_flag，决策置信度 ×0.85~0.95（沿用 SPEC §4.4 口径）。
- 重心原则：非主导维度力量在最终决策中权重封顶 0.3。

### M6 temporal_conflict（R2，时序矛盾，23 C6 落地）

- 定义：同一 symbol/asset_class 上，`macro_force`（days/weeks）与 `micro_force`（minutes/hours）方向相反，且双方 strength 均 ≥ 0.3 时，生成 `TemporalConflict` 对象：
  `{symbol, macro_dir, micro_dir, macro_strength, micro_strength, macro_age_hours, conflict_id}`。
- 裁决规则（回测佐证，预注册，禁止在线自由调整）：

| 评估 horizon | 主导方 | 依据 |
|---|---|---|
| 决策目标 ≤ 1d | micro 主导（0.7），macro 降权为 veto 约束 | 代理回测：mom5 微观在 H=1 冲突胜率 68-71% |
| 决策目标 ≥ 5d | macro 主导（0.7），micro 降级为入场时机 | 代理回测：state 类微观在 H=5/10 冲突胜率仅 8-17%，宏观跨 H 不衰减 |
| 2-4d 过渡带 | 0.5/0.5，输出 conflict_flag + 置信度折半 | 回测模糊区 |

- 落地方式：50 决策输出改按 `decision_horizon` 生成（默认 hours，约束包络可指定 days）；两个 horizon 的裁决并行产出，审计记录双方。
- 40 数据年龄纳入：`macro_age_hours > 72h` 时 macro_strength ×0.7 衰减，> 7d 时 macro 降级为仅约束（fail-open）。

### M7 40 内部矛盾外发（R1，42 适配器扩展）

- 42 `cycle_state_adapter` 增读 `asset_rotation.json.divergence` 与 `cycle_state.json.sector_transmission`，发布新增信号：
  - `source=40-divergence`，symbol=MACRO，direction=象限方向，confidence=基础置信×(1-背离率)（当前实例：0.8×(1-2/5)=0.48），horizon=days，payload 携带 n_divergent/n_scored/quadrant/hy_oas_check。
  - 背离率 ≥ 0.5 或 HY OAS 背离时，direction 降为 neutral、conflict_flag=true（移交矛盾框架，不在 40 侧强行裁决，对齐 40 SPEC §3.3）。
- 43 侧：five_domain 五维分数与 war_state/tier 原样进 payload（已具备），50 将 43 映射为 D4（情绪/治军）+ C6 估值辅助维度（具体映射在 M4 落地时冻结）。

## 五 · 新鲜度与回测底座（M8/M9）

### M8 源数据年龄校验（R0.5）

- `path_synthesis._freshness` 增加第二因子：payload 含 `state_generated_at` / `updated_at`（40/43/11 子池约定字段）时，按源年龄计算 `source_freshness = exp(-age_hours / ttl_hours)`，ttl 预注册（40-cycle=168h、43-strategic=72h、11-*=24h）；最终 freshness = min(bus_freshness, source_freshness)。
- 源年龄超 2×ttl → evidence 直接丢弃 + degraded=source_stale（fail-open）。

### M9 回测/回放底座（R2）

- 42 `run_bus` 每次 flush 后追加写 `runtime/bus_history/bus_state_YYYYMMDDTHHMMSSZ.json`（上限 500 份，滚动清理）；50 每次 `make_decision` 落盘 `runtime/decisions/decision_<ts>.json`。
- 新增 `tools/pit_replay.py`：按时间轴重放 bus 快照 → make_decision → 与后续 K 线对齐计算方向命中/收益，输出 A/B 报告（现状映射 vs 本 SPEC 映射）。
- 准入门槛：≥ 30 天连续快照、≥ 200 条决策后，才允许用 PIT 回测结论调整权重（防小样本过拟合，对齐 23 W6 500 样本门槛口径）。

## 五A · 消费侧接入与审计流（2026-11-09 评审增补，M10/M11/M12）

评审（REVIEW-20261109 §一/§四）发现的三个消费侧缺口，纳入本 SPEC 范围：

### M10 degraded_events 统一审计流（R0.5）

- 各层降级事件（桥关闭吃默认值、源数据 stale、resonance_fallback、trigger_flap、dispatcher_down、washout unknown_fallback、direction_leak_check 失败）统一写入 `42/runtime/degraded_events.jsonl`：`{ts, layer, source, reason, detail}`。
- 42 StateStore 增加 degraded 域视图；**任何降级持续 >24h 未恢复 → 告警**（复用 15-监控告警）。
- 原则：fail-open 是容错不是静默——降级必须可观测，否则 fail-open 变成 fail-silent。

### M11 消费侧归口与补通（R1）

| 缺口 | 现状实证 | 修复 |
|---|---|---|
| 16 双事实源 | 16 `capital_allocator/constraint_envelope.py` L19-28 直读 43 文件，绕过 42 总线（总线信号过 F1-F5 过滤，文件未过） | 统一 SSoT：16 改读 42 bus_state.json 中的 43 信号；过渡期文件加 `version` 戳，16 校验版本一致才消费，不一致取更保守值并记 degraded |
| 11 不消费 42 参数 | `params_active.json` 消费者仅 23/43/l1_trading（grep 实证） | 11 侧新增 param_consumer shim（对齐 23 `param_consumer.py` 契约），消费 long_threshold_multiplier/position_size_factor；不消费=行为不变（fail-open 兼容） |
| 13 零接入 | grep 13 对 50/42 无消费 | R3 前完成契约：13 消费 50 FinalDecisionSignal 的 execution_rights/mandate_id/kill_switch 字段，fail-closed 语义不变；契约冻结前 50 不得 live（SPEC §3.1 已有，此处落实责任方） |

### M12 宏观力权重上限（R0-R2 期间）

- 40 周期判定未通过 X1/P5/P6 前，macro_force 合计权重**硬上限 0.15**（而非 M2 的 0.30）；X1 达标（100 样本/2 周/方向准确率过基线）后解锁至 0.30，经 48 训练门禁后方可再上调。
- 理由：架构可信度上限 = 主网络判断质量；未验证的大脑只配低权重。

## 五B · 不可跳阶段硬门禁（评审增补，写入各 SPEC 引用）

| 门禁 | 规则 | 违反后果 |
|---|---|---|
| G1 | R0 未完成 → macro_force 权重强制 0 + 审计 `macro_stale` | 50 决策降级为纯微观裁决 |
| G2 | Granger 检验不显著 → t_arrive 机制禁用 | 时序矛盾退化为 SPEC-M1 horizon 规则 |
| G3 | 13 未接入 → 50 不得 live（paper only） | execution_rights=live 请求拒绝 |
| G4 | PIT 样本 <200 或 <30 天 → 禁止用回放结论调权重/阈值 | 权重变更训练门禁拒绝 |

## 六 · 阶段路线

| 阶段 | 内容 | 退出标准 |
|---|---|---|
| **R0 信号活性**（2026-11-09 增补，最高优先） | R0-1：恢复 40 流水线调度（p1→p4 每日运行，launchd/cron 登记），修复前冻结下游对 40 信号的消费权重；R0-2：打开 `CYCLE_STATE_BRIDGE=1` 并验证五维分数不再是默认 50；R0-3：43 shadow 解除条件预注册（连续 N 天五维非默认 + P3 一致性维持 ≥95% 后才允许 shadow=false）；R0-5：43 `element_comparison` 分歧经 42 外发为审计信号 | 40 产出物 generated_at ≤ 24h；43 五维至少三维有真实输入；R0 完成前 50 的 macro_force 权重强制为 0 并审计标注 `macro_stale`，禁止基于当前链路做权重/回测结论 |
| R0.5 止血 | M1 命名统一、M3 权重归一+DEFAULT_DIMENSION 修复、M8 新鲜度 | 回放：43 不再以 unknown 投票；单源力量占比 ≤45%；stale 源可观测降级 |
| R1 宏观力量 | M2 角色四分、M4 维度力量、M5 三步法、M7 40 背离外发 | 回放：D1 维度有非零力量；主矛盾对象含 leader_dimension；differential harness 对基线分歧率可解释 |
| R2 时序矛盾+回测 | M6 temporal_conflict、M9 快照/PIT 回放 | 冲突样本上分 horizon 裁决可复算；A/B 报告产出 |
| R3 闭环 | W6 维度/宏观权重学习、48 反馈接入 | ≥200 决策样本后权重更新走训练门禁（SPEC §5.1 不变） |

## 七 · 验收清单（每条可测）

1. `role_of("strategic_extension")` 在过渡期内归一为 `43-strategic` 且 role=macro_force；不再出现 unknown source 生成 path。
2. 同一 bus 输入下，任一 source 对 force 的贡献 ≤ 其声明权重 ±10%（归一后）。
3. 40 状态 14 天未更新时，其 path freshness < 0.2 且审计含 source_stale。
4. 构造宏观 long/微观 short 的 fixture：`decision_horizon=hours` 时方向=short（micro 主导），`decision_horizon=days` 时方向=long（macro 主导），且产出 temporal_conflicts 审计。
5. dimension_forces 输出覆盖 D1-D4/C6-C8/NEWS 全维度，无源维度标 degraded。
6. PIT 回放脚本可对 ≥2 份历史 bus 快照产出决策与命中率报告。

## 八 · 非目标

- 不修改 23 任何运行时文件/样本/权重；复刻仅限设计口径（隔离约束不变）。
- 不改变约束包络钳位顺序与 13/16 风控边界（SPEC §4.10/§3.1 不变）。
- 不做宏观力量对微观的单向压制（回测已证伪该方案）。
- 不在 R0.5 阶段动 w4 四维权重冻结值。

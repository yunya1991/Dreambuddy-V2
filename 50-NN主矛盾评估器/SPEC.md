# SPEC: 50-NN主矛盾评估器（NN Main Contradiction Evaluator）

> 版本：v0.1（评审稿）
> 日期：2026-11-07
> 状态：🟡 设计态，未实现；R0 前需通过 SPEC 评审 + ADR-0002
> 归属：50-NN主矛盾评估器（NN 闭环链的决策层实现）
> 上游：42 神经网络交易协调层（8 源总线）、40 周期神经网络（宏观约束）、43 战略承接推演层（弹性约束）、48 涌现架构（数据/训练/度量）
> 下游：执行层 13 通用风控 / 16 调控系统 / 22 执行引擎 / 11 交易执行器
> 对照：23 四层闭环自进化交易架构（独立运行，不受本模块影响）

---

## §0 定位与边界

### 0.1 定位

50 是 **NN 闭环链的"矛盾力量评估器 + 最终决策出口"**：

- 消费 42 总线的子系统信号（BCRM2.0 / BDSM / 洗盘 / 事件套利 / 29 事件等）；
- 消费 40/43 的弹性约束包络（资产偏置、多空数量、仓位、杠杆）；
- 复用 23 已验证的**主矛盾架构设计思想**（矛盾维度、力量评估、4 维裁决、成对支配、W6），但**独立实现**；
- 输出 `FinalDecisionSignal v1`（`source=50-nn`），供执行层 paper（初期）/ live（评审后）。

### 0.2 不做什么

| 禁止 | 原因 |
|---|---|
| 不 import 23 的运行时模块/状态 | 23 仅提供可参考/复制的主矛盾架构设计，不是运行时依赖；避免污染与重构传导 |
| 不写 23 的样本/权重/状态 | 23 独立对照实验，必须零改动 |
| 不做数据采集 / 宏观约束生成 / 执行下单 / 训练数据生产 | 分别归 18-21/38、40/43、13/16/22/11、48 |
| 不直接改 40/50 权重 | 训练走 48 + 门禁（40 P5/P6 / 50 训练门禁） |
| 不做 8 路等权投票 | 子系统角色/粒度/horizon 不同，必须分类、去重、分轨 |

### 0.3 与其他域的边界

| 域 | 50 的关系 |
|---|---|
| 49 交易框架协议 | 契约 SSoT；50 只读消费 SignalSchema v1 / FinalDecisionSignal v1 / MacroElasticConstraint v1 |
| 42 协调层 | 只读 `runtime/bus_state.json`；不写总线、不改适配器 |
| 40/43 | 只读 `cycle_state.json` / `strategy_mapping.json` / `strategic_extension_signal.json`；不回写 |
| 48 涌现架构 | 读训练产物/基因登记；写反馈样本（按 48 接口）；不直接改 40 |
| 23 | **无运行时依赖**；仅在设计中参考其主矛盾架构；不 import、不写、不读其运行时状态（对照数据由 48 读取） |
| 13/16/22/11 | 50 输出决策信号；执行层 fail-closed；execution_rights 单出口 |

---

## §1 系统结构

```text
42 bus_state.json ──┐
40 cycle_state ─────┤
43 strategic_ext ───┤
48 training/genes ──┤
13 risk state ──────┘
          ↓
  adapters/ (只读)
          ↓
  core/evidence.py        证据对象 + 角色分类 + provenance
  core/dedup.py           同源去重 / 多子池聚合
  core/dimension_forces.py D1-D4 / C6-C8（D3 由路径共振传入）
  core/contradiction.py   共振 + 4 维冲突裁决 + 主矛盾
  core/dominance.py       成对支配 / Copeland 矩阵
  core/intent_tracks.py   trend / reversal / event_shock
  core/horizon.py         minutes/hours/days/weeks 分层
  core/constraints.py     40/43 包络（只钳位）
  core/w6.py              独立权重学习（独立样本存储）
  core/decision.py        FinalDecisionSignal v1 (source=50-nn)
          ↓
  adapters/execution_writer.py → 13 → 16 → 22 / 11 执行器
          ↓
  adapters/feedback_writer.py  → 48（全链路数据/样本）
```

---

## §2 输入契约

### 2.1 42 总线（8 源）

| source | 粒度 | horizon | 角色 | 50 内处理 |
|---|---|---|---|---|
| `11-bcrm` | 资产类 | days | 宏观先验 | `weight_factor` / 约束上下文，不投每币方向票 |
| `11-bdsm` | 每币 | days | 外部证据 | 每币一票（与内部 bridge 同源时去重） |
| `11-washout` | 每币 | hours | reversal 轨 | 不投方向；下调趋势路径 continuation、提高尾部风险 |
| `11-event-arbitrage` | 每币/事件 | hours | event_shock 轨 | 事件窗口内参与 shock；与 29-event 冲突以可执行为准并审计 |
| `29-event` | symbol/MACRO | hours | event_shock 轨 | **自环**（23 写入）；只作审计/一致性，不作独立票 |
| `40-cycle` | 宏观 | days | 约束 | 只进包络 |
| `43-strategic` | 资产类 | days | 约束 | 只进包络 |
| `23-contradiction` | 23 输出镜像 | hours | 自环 | 只审计，禁止入裁决 |

> 42 的 `ENABLE_11_STATE_ADAPTER` 默认关；R0 需打开并验证 TTL/去重；bus 缺失时 fail-open。

### 2.2 约束输入

- 40 `strategy_mapping.json`：`position_band_pct`、`risk_guards`；
- 43 `strategic_extension_signal.json`：`per_asset_class`（tier/position_band/war_state/risk_exposure_hint）；
- 43 `a3_strategy_adapter`：`leverage_cap`（当前未发布进 strategic_extension，R1 补齐）；
- 16：资产数量/多空数量/杠杆的参数化（R1）。

### 2.3 数据/基因输入

- 48 训练产物/度量/基因登记（只读）；
- 50 自身 runtime（权重/样本/审计）独立存储，路径由 `DREAMBUDDY_ROOT` 统一。

---

## §3 输出契约

- 复用 `FinalDecisionSignal v1`；`source="50-nn"`；必填字段不变。
- `payload` 追加：`evidence_summary` / `gene_versions` / `constraint_id` / `constraint_applied_at` / `control_group`（可选）。
- 输出前只做约束复核（更保守值），不重复相乘；保留 `constraint_id`。
- 执行层路由：`source=50-nn` → paper（初期）；live 需 `execution_rights` 授权；同标的同时刻单出口。
- 审计 JSONL：每条证据、去重、调制、主矛盾、约束钳位、最终决策均可追溯。

---

## §4 矛盾评估机制

### 4.1 证据对象

```text
evidence_id, source, subsystem, symbol/asset_class, granularity,
direction, confidence, horizon, intent, dimension_hint,
risk_exposure_hint, ts, expires_at, provenance, payload
```

`provenance ∈ {42-bus, internal, self-mirror, constraint}`。

### 4.2 角色分类

- **约束**：40-cycle、43-strategic → 不投票。
- **外部证据**：11-bcrm（先验）、11-bdsm、11-washout、11-event-arbitrage。
- **自环**：29-event、23-contradiction → 仅审计。
- **不可用**：缺失/TTL 过期 → 不参与，fail-open。

### 4.3 维度与力量

- 维度：D1 宏观利率 / D2 资金流 / D3 技术 / D4 情绪 / C6 估值 / C7 叙事 / C8 VIX / NEWS。
- 维度排序由真实力量评估器决定；D3 由路径共振传入；数据不足降级 neutral。
- 子系统票只在同维度内决定多/空；`11-bcrm` 资产类先验不投每币 D3。

### 4.4 4 维裁决

- 力量对比 0.40 / 时间紧迫性 0.15 / 证据一致性 0.25 / 市场影响 0.20。
- 证据一致性直接消费“内部 vs 42”的对账结果：一致 → 置信度 ×1.0~1.15；分歧 → ×0.85~0.95 + `conflict_flag`。
- 共振阈值 0.6；主导阈值 0.55（沿用 23 架构设计口径，独立实现）。

### 4.5 Dominance

- 成对支配 + Copeland 矩阵；输出可解释 dominance 矩阵与主导者；argmax 仅作 shadow 回退。

### 4.6 intent 分轨

- `trend`：常规方向票。
- `reversal`（洗盘）：不投反向票；下调趋势路径 continuation、提高尾部风险；趋势市降权、震荡市升权。
- `event_shock`：显式窗口（strength / expires_at / event_phase）；窗口内主矛盾由事件指定，其余维度降为次要矛盾；退出条件显式。

### 4.7 horizon 分层

- minutes/hours（washout/event-arb/29-event）与 days（bcrm/bdsm/43）分组；跨层只加权汇总，不做共振。

### 4.8 去重与多子池

- `(source, symbol, dimension, horizon)` 只计一票；
- `11-bdsm` 42 版与内部 bridge 同源时：bus 新鲜取 bus，否则取 bridge，严禁双票；
- 同源多子池在 11 侧聚合（payload.subpools 保留明细）；未聚合时 50 加权聚合并按 `1-dispersion` 打折。

### 4.9 W6 与自票

- 50 独立样本存储/权重版本；样本带 provenance；NN→23 基因注入前不污染 23 的 W6。
- 50 自身候选设自票上限；不得单独决定主导者；独立证据复核 + 审计。

### 4.10 约束包络

- 顺序：`full_freeze/FREEZE 否决 → position_band ∩ position_cap ∩ asset_count ∩ long/short_count ∩ leverage_cap → macro_mult → 13 最终钳位`。
- 约束只钳位，不进矛盾评分、不重复相乘。

---

## §5 独立进化链路

```text
50 决策 → 执行层 → 成交/PnL/拒单/全链路数据 → 48
        → 48 训练建议（50 权重/策略 + 40 宏观）
        → 门禁（50 训练门禁 / 40 P5/P6）
        → 采纳/拒绝审计 → 50 下一轮
```

- 在线：W6 维度权重（独立存储）。
- 离线：48 数据/训练网关；OOD 隔离；walk-forward；相变度量（E5）。
- 50 不读取/不写入 23 的样本、权重、运行时状态；对照数据由 48 汇总。

---

## §6 基因治理

| 流向 | 内容 | 规则 |
|---|---|---|
| **48 → 40** | 统一数据口径、训练、度量 | 主供体；建议制 + 40 P5/P6 门禁 |
| **NN → 23** | 50 验证过的优质基因（维度口径/置信度校准/证据融合） | 经原 42→23 shadow 端口；选择性采纳；不破坏 23 主链 |
| **23 → NN** | **仅设计参考/复制** | 不做持续基因流；不 import；不构成运行时依赖 |
| 50 内部基因 | 从设计参考复制后独立演进的模块 | `genes/registry.json` 记录来源/版本/差异/测试 |

基因登记字段：`gene_id, source, version, module|config, shadow_evidence, promotion_state, rollback`。

---

## §7 目录结构（建议）

```text
50-NN主矛盾评估器/
├── SPEC.md
├── core/
│   ├── evidence.py / dedup.py / dimension_forces.py / contradiction.py
│   ├── dominance.py / intent_tracks.py / horizon.py / constraints.py
│   ├── w6.py / decision.py
├── genes/
│   ├── registry.json
│   └── <gene_id>/{module.py, gene.json, tests/}
├── adapters/
│   ├── bus_reader.py / macro_reader.py
│   ├── execution_writer.py / feedback_writer.py
├── runtime/            # 权重、样本、审计（独立）
├── scripts/
└── tests/
```

---

## §8 开关与回滚

| 开关 | 默认 | 作用 | 回滚 |
|---|---|---|---|
| `ENABLE_50_SHADOW` | 0 | 50 shadow 决策/审计 | 置 0 |
| `ENABLE_50_FUSION` | 0 | 50 证据融合调制 | 置 0 |
| `ENABLE_50_EXECUTION` | 0 | 50 → paper MCP | 置 0，回 23 |
| `ENABLE_50_LIVE` | 0 | 50 live 灰度 | 置 0，execution_rights=disabled |

- 所有开关默认 0；bus 缺失/过期 → fail-open（不产生决策）。
- 13 风控始终 fail-closed；execution_rights 单出口。

---

## §9 验收与对照实验

### 9.1 功能验收

- 8 源可读；同源去重无双计；provenance/审计完整；
- 4 维裁决/Dominance/主矛盾可解释；约束钳位可复算；
- paper 执行对账完整；50 全程不写 23/40/43。

### 9.2 对照实验（23 vs 50）

同一输入快照并行：

| 指标 | 目标 |
|---|---|
| 方向一致率 | 可解释（不强制相同） |
| 主矛盾维度一致率 | 可解释 |
| 置信度校准 | 50 不劣于 23 |
| paper PnL / 最大回撤 / 换手 | 风险调整后 50 不劣于 23 |
| W6 归因覆盖率 | ≥90% |
| 无双计审计 | 100% 通过 |

≥4-8 周 shadow；评审通过后 live 灰度。

---

## §10 路线（R0-R5）

| 阶段 | 内容 | 周期 |
|---|---|---|
| R0 | 目录/SPEC/基因复制与一致性测试；42 bus 只读适配；shadow 决策 | 1 周 |
| R1 | 约束包络字段化（43/16/execution_rights） | 1 周 |
| R2 | 融合机制（去重/provenance/intent/horizon/4 维/Dominance/W6） | 2 周 |
| R3 | 执行接线（13→16→22 paper） | 2 周 |
| R4 | 48 数据/训练网关 + 50 训练门禁 | 2-3 周 |
| R5 | 双链对照 ≥4-8 周 + live 灰度 | 持续 |

---

## §11 风险

| 风险 | 对策 |
|---|---|
| 独立实现与 23 设计漂移 | gene registry + 一致性测试 + 设计参考版本记录 |
| 50 与 23 数据层仍经 42 | 有意的信号耦合；代码/状态/存储隔离 |
| 双链执行冲突 | execution_rights 分区 + paper-only 起步 + 13 最终钳位 |
| 48 训练网关未就绪 | 50 先 shadow + 独立 W6；训练闭环等 48 R4 |
| 40 门禁 | 训练建议制；P5/P6 不放宽 |
| 契约 source 新增 | ADR-0002 + manifest 更新（additive） |

---

## §12 变更记录

- v0.1（2026-11-07）：初稿；双决策链、独立实现、基因方向 NN→23、48 为 40 唯一对接口。
# SPEC: 50-NN主矛盾评估器（NN Main Contradiction Evaluator）

> 版本：v0.2.0（评审稿，按同行评审 M1-M9 修订）
> 日期：2026-11-07
> 状态：🟡 设计态，未实现；**第二轮复审通过（M2/M5，2026-11-07）+ ADR-0002 accepted**；R0 前需 MVB 5/5；v0.2.0 修订：**新增 evidence→path 合成层（M2）**、执行权/Mandate/kill-switch（M4）、11 子池写入条件（M5）、约束字段与相关资产定义（M7）、W6 样本 schema/冷启动（Minor）；v0.1.1 已修 horizon/预注册/29-event/R0
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
  core/path_synthesis.py  evidence → path（confidence/expected_return/resistance/continuation）
  core/dimension_forces.py D1-D4 / C6-C8（D3 由 path_synthesis + 11-bcrm-tactical 提供）
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
| `29-event` | symbol/MACRO | hours | event_shock 轨 | **自环**（由 23 的 `kline_event_handler` 写入）；只作审计/一致性，不作独立票。**输入依赖披露**：50 的事件轨完整性依赖对照方 23 的写行为；23 停写时 50 降级为 unavailable（fail-open），并记录依赖事件 |
| `40-cycle` | 宏观 | days | 约束 | 只进包络 |
| `43-strategic` | 资产类 | days | 约束 | 只进包络 |
| `23-contradiction` | 23 输出镜像 | hours | 自环 | 只审计，禁止入裁决 |

> 42 的 `ENABLE_11_STATE_ADAPTER` 默认关；R0 需打开并验证 TTL/去重；bus 缺失时 fail-open。
>
> **11 子池状态写入条件（M5 修复）**：`polling_trader._write_subpool_state()` 只在 `_write_shadow_signal()` 内调用（`polling_trader.py:6785/6810`），即仅“被执行权限拦截的开仓意图”才落盘。若 11 对 washout/event-arbitrage 有 live 执行权，信号会被执行而不是写状态文件 → 42 无源、50 无输入。R0 必须显式配置 11 子池为 signal-only/authority 可拦截，或将相关标的的 50 输入标记 unavailable（fail-open）。

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

### 3.1 执行权与安全契约（M4 修复）

50 直接向执行层出信号，必须先过执行权与风控：

| 项 | 规则 |
|---|---|
| `execution_rights` | `outcome ∈ {paper, live:50-bypass, disabled}`；**默认 paper**；同一标的 live 仅一个出口 |
| Mandate | 50 输出携带 `mandate_id` / `authority`；无 Mandate 只能 paper |
| kill-switch | 文件/环境开关（`50_KILL_SWITCH=1`）立即停止 50 信号；13 风控 fail-closed |
| 限额 | 日限额/单标的限额/杠杆上限由 16/13 钳位；50 不得自行放大 |
| 审计 | `decision_id / constraint_id / evidence_id / mandate_id / execution_rights outcome / kill_switch 状态` |
| live 灰度 | 仅 R5 评审通过后；50 live 与 23 live 不得同标的并存 |

> 47 `execution_rights.json` 当前只有 `eleven_domain` 与 BTC/ETH，无 50 分区；R1c 需扩展 schema 并走双人审批（DEC-26）。

---

## §4 矛盾评估机制

### 4.1 证据对象

```text
evidence_id, source, subsystem, symbol/asset_class, granularity,
direction, confidence, horizon, intent, dimension_hint,
risk_exposure_hint, ts, expires_at, provenance, payload
```

`provenance ∈ {42-bus, internal, self-mirror, constraint}`。

### 4.1a Evidence → Path 合成（M2 修复，R0 必建）

23 的矛盾识别 / DominanceResolver / W6 以 **paths** 为输入；50 的输入是 **evidence**。没有合成层，`core/contradiction`、`core/dominance`、`core/w6` 无法按文档实现。R0 新增 `core/path_synthesis.py`：

| path 字段 | 来源/算法 |
|---|---|
| `path_id` | `ev:{source}:{symbol}:{dimension}:{horizon}:{intent}` |
| `source` | evidence.source |
| `direction` | evidence.direction |
| `confidence` | `evidence.confidence × freshness × (1 - conflict_penalty)` |
| `expected_return` | 归一化证据分：`confidence × horizon_factor`（**不是年化收益**，只用于排序；口径写死） |
| `resistance` | `1 - confidence` |
| `continuation_score` | trend: `confidence × horizon_persistence`；reversal: `1 - trend_confidence`；event_shock: `evidence.confidence` |
| `metadata` | dimension_hint / intent / granularity / evidence_id / provenance |

约束：

- 只有 `role=external evidence` 的 evidence 生成 path；constraint / self-mirror 不生成。
- 同 `(source, symbol, dimension, horizon)` 去重后只生成一条 path；`bdsm` / `11-bdsm` 别名先归一化。
- `confidence=0` 或 TTL 过期的 evidence 不生成 path（fail-open）。
- **D3 数据源**：42 现有 8 源中没有每币技术源（`11-bcrm` 是资产类）。R0 必须新增 `11-bcrm-tactical`（11 每币 BCRM2 结果持久化 + 42 适配器）；注意 `_last_bcrm2_result` 当前仅为“最后一币”单值、逐币推理时覆盖，R0 需新增 per-symbol 快照文件。无该源时 D3=neutral（降级可观测），不得用资产类信号冒充 D3。
- **source 映射**：50 必须定义自己的 `SOURCE_DIM_MAP` / `SOURCE_WEIGHT_MAP` / `SOURCE_TF_MAP`（或统一读 `metadata.dimension_hint`）；不得直接复用 23 的映射表（其键为 `bcrm`/`bdsm`/`strategic` 等，`11-*` 源会全部退化为 C3 / 0.05 / medium）。
- Dominance 只在**同 horizon** 的 path 集合内两两比较；跨 horizon 不做 dominance。

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

- **唯一事实源：SignalSchema v1 的 horizon 枚举（minutes/hours/days/weeks）**；本模块不自定义第二套口径（v0.1.1 修订）。
- minutes/hours（washout/event-arb/29-event）与 days（bcrm/bdsm/43）分组；跨层只加权汇总，不做共振。

### 4.8 去重与多子池

- `(source, symbol, dimension, horizon)` 只计一票；
- `11-bdsm` 42 版与内部 bridge 同源时：bus 新鲜取 bus，否则取 bridge，严禁双票；
- 同源多子池在 11 侧聚合（payload.subpools 保留明细）；未聚合时 50 加权聚合并按 `1-dispersion` 打折。

### 4.9 W6 与自票

- 50 独立样本存储/权重版本；样本带 provenance；NN→23 基因注入前不污染 23 的 W6。
- 自票上限：**50 当前不生成候选**，该规则暂不适用；若未来 50 自产候选（如内置策略），再启用自票上限与独立证据复核（审计字段预留）。

### 4.10 约束包络（M7 修复）

- 顺序：`full_freeze/FREEZE 否决 → position_band ∩ position_cap ∩ asset_count ∩ long/short_count ∩ leverage_cap → macro_mult → 13 最终钳位`。
- 约束只钳位，不进矛盾评分、不重复相乘。
- **字段定义**（43/16 必须提供；缺失则 fail-open 到更保守默认）：
  - `asset_groups`：资产分组/相关资产桶（如 L1_anchor / L2_major / L4_meme）；无分组时退化为资产类（crypto_usdt 等）。
  - `asset_count_cap`：每个资产组允许的最大持仓标的数。
  - `long_count_cap` / `short_count_cap` / `net_bias`：多/空持仓数量上限与净偏置。
  - `position_band` / `position_cap`：仓位带与单标的上限。
  - `leverage_cap`：杠杆上限（43 `a3_strategy_adapter` 已计算，R1a 需发布进 strategic_extension payload）。
- 16 `capital_allocator`（`16-调控系统/core/capital_allocator/component.py`）负责计数/杠杆钳位；13 最终否决。
- **“相关资产”判定**：以 43 发布的 `asset_groups` 为准；43 未提供时按资产类退化，并在审计中标注 `degraded=asset_group_missing`。

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

### 5.1 W6 样本 schema 与冷启动

- 样本：`decision_id, evidence_id, dimension, intent, provenance, predicted_direction, confidence, realized_return, label_ts`。
- 触发：≥500 条带标签样本 / 24h；权重截断 [0.3,1.5]；学习率/正则沿用 23 设计口径（独立实现）。
- **冷启动**：前 500 样本使用等权默认值；冷启动期输出 `w6_state=cold_start`，不得用于 A/B 结论。
- 存储：`50/runtime/w6/` 独立；禁止写 23 `contradiction_samples.json`。

### 5.2 状态、故障与恢复

- 50 runtime 持久化 `state.json`（证据缓存/去重键/最后决策）；崩溃重启后从磁盘恢复。
- bus 缺失/过期 → fail-open（不产生决策）；执行侧 → fail-closed（13 风控）。
- kill-switch 置位 → 停止输出，保留审计。

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

- 8 源可读 + `11-bcrm-tactical`（D3）；同源去重无双计；provenance/审计完整；
- 4 维裁决/Dominance/主矛盾可解释；约束钳位可复算；
- paper 执行对账完整；50 全程不写 23/40/43。

### 9.2 对照实验（23 vs 50，v0.1.1 预注册）

**先注册后运行**（在 R5 开始前锁定，不得事后调整）：

**主指标（3 项）**
| 指标 | 判定 |
|---|---|
| 方向一致率 | 相对 R0-04 分歧率基线的**增量**解释，不解释绝对值 |
| 主矛盾维度一致率 | 同上 |
| paper 风险调整收益差 | **非劣效边界：Sharpe 差值 95%CI 下界 > -0.2** |

**安全指标（2 项）**
| 指标 | 判定 |
|---|---|
| 最大回撤 | 50 不显著高于 23 |
| 单标的双出口次数 | 0（execution_rights 事后审计） |

**辅助**：W6 归因覆盖率 ≥90%；无双计审计 100%。

**统计效力（Minor 修复）**：

- 预注册**最小成交笔数/最小周数**（功效分析）；4-8 周只是下限，样本不足则延长。
- Sharpe 差值置信区间用 **block bootstrap**（处理交易收益自相关）；必要时用 Deflated Sharpe。
- 多重比较：**Holm 或 BH（FDR）**，预注册族错误率。
- 非劣效边界 `-0.2` 需在预注册文档中给出业务可接受性依据。

**W6 冷启动披露**：50 的 W6 从零样本启动，前 4-8 周权重学习必然弱于 23；因此 A/B 只解释“相对分歧率基线的增量”，冷启动期结论不作为架构优劣证据。差分基线由 R0-04 differential harness 提供（固定 10-20 组历史快照，同输入跑 23 与 50，逐字段 diff：维度排序/主矛盾/dominance 矩阵/置信度）。

≥4-8 周 shadow；预注册指标全部可裁决后，评审通过方可 live 灰度；多重比较校正。

---

## §10 路线（R0-R5）

| 阶段 | 内容 | 周期 |
|---|---|---|
| R0 | **底座验证周**：bus ≥6 源在线率 + TTL + 连续 3 日信号量>0；**新增 `11-bcrm-tactical`（D3 源）**；契约 const→enum + manifest 升版 + `from_50_signal` 路由；**evidence→path 合成层 + 一致性测试**；**50 execution_rights/Mandate/kill-switch 骨架**；differential harness（分歧率基线）；基因复制；shadow 决策；资源基线。**不达标不进 R2** | 1-2 周 |
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
- v0.1.1（2026-11-07）：按外部评审修订——horizon 唯一事实源改为 SignalSchema v1；§9.2 对照预注册（3 主 + 2 安全指标、Sharpe 95%CI 下界 > -0.2、多重比较校正）；W6 冷启动披露 + differential harness 基线；29-event 输入依赖标注；R0 重定义为底座验证周（bus ≥6 源/TTL/3 日信号量/契约落地/资源基线）。
- v0.2.0（2026-11-07）：按同行评审 M1-M9 修订——新增 §4.1a evidence→path 合成（23 算法输入形态修正）；D3 数据源明确为 R0 新增 `11-bcrm-tactical`；新增 §3.1 执行权/Mandate/kill-switch/限额/审计；§2.1 补 11 子池状态写入条件；§4.10 补 asset_groups/asset_count_cap/long-short_count_cap/net_bias/leverage_cap 定义；§5.1 W6 样本 schema/冷启动；§5.2 状态恢复/fail-open/fail-closed。
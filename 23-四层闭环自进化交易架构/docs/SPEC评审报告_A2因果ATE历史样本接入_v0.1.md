# 同行评审报告 — SPEC-A2 因果 ATE 历史样本接入

> **评审对象：** [SPEC-A2-因果ATE历史样本接入.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/SPEC-A2-因果ATE历史样本接入.md)（v1）
> **评审日期：** 2026-10-14
> **评审方法：** `dream-science-peer-review` — 4 视角独立评审 + Devil's Advocate 让步阈值协议 + 7 模式阻断清单
> **实证依据：** 本报告所有「数据结论」均由**真实数据 POC**支持（全量 290,921 条 `shadow_rl_samples.jsonl`，真实 `CausalEngine`），非推测。

***

## 评审摘要

- **整体评价：修改后接受（Major 5 条 / Minor 5 条）**
- **7 模式阻断清单：3 项不通过**（模式 3 方法捏造、模式 5 结果幻觉、模式 6 逻辑跳跃、模式 7 边界忽略）
- **Devil's Advocate：1 条评分 5（致命，已实证）→ 作者必须让步**
- 核心结论：**SPEC 的方向（喂历史样本）成立且价值可证**，但**源B 的 treatment 定义存在致命缺陷**，须修正后方可落地。

***

## 一 · 实证 POC（评审的硬证据）

命令（可复现）：对全量 `gene_data/shadow_rl_samples.jsonl`（N=290,921），`X=[R_up,R_down,R_smooth,R_flow,R_reflexivity]`，`y=reward`，`CausalEngine.estimate_ate(method="dml")`。

| # | treatment 定义 | ate | 95% CI | significant | method |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 1 | `quality_score > median`（**SPEC 原方案**） | 0.0 | [0.0, 0.0] | **False** | `linear_regression`（causalml 报错降级） |
| 2 | `open vs WAIT` | -0.00095 | [-0.00324, +0.00134] | False | `causalml_dml` |
| 3 | `long_only vs 其余` | 0.00534 | [0.00280, 0.00787] | **True** | `causalml_dml` |
| 4 | `R_up > median` | 0.00298 | [0.000045, 0.00592] | **True** | `causalml_dml` |

**关键实证：**
- `quality_score` 分布**高度退化**：`1.0→197,390 条`、`0.97→23,067`、`0.94→40,033`、`0.95→209`、`0.9→181`。median=1.0 → `> median` 几乎全为 0 → **treatment 单水平** → causalml 抛 "Treatment vector must have at least two levels" → 降级后 `ate=0`。
- 换成 `R_up>median` 或方向性 action 后 **ATE 显著且 CI 不含 0** → 核心价值主张**可达成**。
- `reward` 稀疏：仅 **14.8%** 样本 `reward≠0`，全量均值 ≈ 0 → y 信号弱（需注意样本构造）。

***

## 二 · Journal-Fit Reviewer（是否适合当前市场/目标）

**意见：** A2 的动机正确——ATE 因样本恒 <500 而形同虚设，接入历史样本是对的方向。源B（29 万条实盘沉淀）确实比 live 6 条路径更能代表统计总体。

**保留意见：**
- 源B 是 shadow RL 样本，其 `reward` 含大量 `WAIT`（78.1%）产生的近零奖励，**样本分布与"主要矛盾识别"发生的时刻分布不一致**：identify() 的样本是「有矛盾信号时」，而 shadow_rl 是全时段。→ 用源B 估计的因果先验可能与 live 场景**分布错配**。建议在 SPEC 中显式声明该错配，并在对照实验中检验（若错配严重，则以源A 为准）。
- 市场适配：源B 覆盖 290k 条但时间跨度未知（疑似短期高频），存在 regime 漂移（SPEC 已列风险，但缓解仅"取最近 N 条"，不足）。

***

## 三 · 方法评审

**M1（Major·致命）— 源B treatment 定义退化。**
SPEC §2.2 用 `quality_score > median` 作 treatment。实证（POC#1）证明该字段退化为单水平 → ATE 恒 `0.0`/不显著。**必须改**：改用连续且保证两水平的 treatment（`R_up > median`，或方向性 action `long_only`，二者均实测显著），并加**退化保护**（treatment 水平数 <2 → 返回空 → 中性 no-op）。

**M3（Major）— 双源混合估计不可行。**
SPEC §2.3 允许 `source="live+bootstrap"` 混合。但源A `y=actual_return`（量级 ~1e-3）、源B `y=reward`（±1）；treatment 分别为 `power` 与 `quality_score`；混淆变量不一致 → **混合后 ATE 无统计意义**。**必须改**：两源**不混合**，各自独立估计；源A 已标注样本 ≥500 → 独用源A，否则独用源B。

**Minor m5：** 源A 持久化补点未细化（W6 `_save()` 每 100 条才落盘，<100 条进程重启即丢）。需明确「每标注即落盘 或 maxlen 阈值」。

***

## 四 · 统计评审（调用 `dream-science-statistics-check` 视角）

**M2（Major）— 显著性门槛与 treatment 强耦合。**
SPEC 验收②要求「significant=True 且 CI 不含 0」。实证显示：**同一批数据、不同 treatment 定义，显著性从 False（open/quality）翻转为 True（long_only/R_up）**。→ 验收②不是"数据达不达标"，而是"命题设计对不对"。**必须改**：在 SPEC 中固化 **treatment 选择依据 + POC 证据表**，并把「treatment 退化」列为阻断验收的前置条件。

**Minor m6：** 290k 条 DML 的 CI 基于渐近正态近似，未做 **多重比较校正**（若对多个 treatment/维度反复试，存在 p-hacking 风险）。建议 SPEC 声明「treatment 预注册」：先固定 `R_up>median`，不得事后挑选显著者。

**Minor m7：** 报告应含**效应量**（ate 相对 y 的标准差）而不只 p/CI；`ate=0.00298` 相对 `std(y)=0.27` 效应量极小（Cohen's d≈0.011），**统计显著但实务上近乎无影响**——这削弱了"ATE 调制 strength"的实务价值，SPEC 须诚实声明。

***

## 五 · Devil's Advocate（让步阈值协议）

| 编号 | 反驳 | 评分 | 让步判定 |
| :-- | :-- | :-- | :-- |
| D1 | 「源B 用 `quality_score` 做 treatment 会退化为单水平，ATE 恒 0，SPEC 的核心能力根本不生效。」 | **5**（实证 POC#1 证实） | **作者必须让步** → 改 treatment（见 M1） |
| D2 | 「验收②'统计显著'能否达成完全取决于 treatment 定义，SPEC 却默认其可达，属结果幻觉。」 | **4**（实证 POC 支持） | **让步** → 固化为前置条件（见 M2） |
| D3 | 「源A/源B y 尺度差 3 个数量级，混合估计统计上无意义。」 | **4** | **让步** → 取消混合（见 M3） |
| D4 | 「默认 `enable_causal_historical_samples=True` 直接违反硬约束 HC-AGI-07（新模块默认关，Shadow ≥7 天 + Sharpe 正向才小流量）。」 | **4** | **让步** → 默认改 False 或显式申报豁免（human-in-the-loop） |
| D5 | 「即便 ATE 显著，效应量 d≈0.011 近乎零，'用 ATE 调制 strength'在实务上无意义，是否应放弃 A2？」 | **3**（有道理但不足以推翻：ATE 可作诊断/先验，且源A 累积后情形可能不同） | **作者可坚持**，但 SPEC 必须诚实声明效应量边界 |

**Devil's Advocate 结论：** D1 为致命缺陷须立即修复；D2/D3/D4 须修改；D5 保留但须在 SPEC 中显式标注边界（不得夸大 ATE 实务价值）。

***

## 六 · 7 模式阻断清单

| 模式 | 检查项 | 结论 |
| :-- | :-- | :-- |
| 1 幻觉引用 | 行号/文件引用可验证（`MIN_SAMPLES=500`@L91、`calibrate_impact_multipliers` 无生产调用者经 grep 证实） | ✅ 通过（Minor m4：L234-248 应精确到 L239-244） |
| 2 数据造假 | 290,921 条经 `wc -l`+逐行 `json.loads` 实测；分布经 `np.unique` 实测 | ✅ 通过 |
| 3 方法捏造 | **不通过** — treatment 退化（M1） + 混合源不可比（M3） | ❌ |
| 4 框架锁定 | 部分 — 未充分对比「修复 `calibrate_impact_multipliers` 死代码」这一替代路径 | ⚠ Minor |
| 5 结果幻觉 | **不通过** — 验收②假设显著可达，但原 treatment 下实测不显著（M2/D2） | ❌ |
| 6 逻辑跳跃 | **不通过** — "源B≥500 → ATE 立即生效"混淆「可估计」与「生效(含显著)」（M5） | ❌ |
| 7 边界忽略 | **不通过** — 未声明源B 为「观察性代理、非干预因果」，且未声明效应量极小的实务边界（m2/m7/D5） | ❌ |

***

## 七 · 综合意见（Major/Minor）

### Major（必须修改）
- **M1** 源B treatment 改用连续/方向性变量（`R_up>median` 或 `long_only`），并加退化保护。
- **M2** 验收②的显著性须与 treatment 定义绑定，固化「treatment 预注册 + POC 证据」，treatment 退化为阻断项。
- **M3** 取消源A/源B 混合估计，两源独立（源A ≥500 优先，否则源B）。
- **M4** 开关默认值须遵 HC-AGI-07（默认 False 或申报豁免）。
- **M5** 澄清"生效"=可估计 + 有效应量 + 对照可复现；不得声称"必显著"。

### Minor（建议修改）
- **m1** "对照 B：n<500 时 strength 逐位相同" 表述与 A2 流程不一致，需澄清。
- **m2** 声明源B 为观察性代理、非干预因果（观察性关联的因果近似）。
- **m3** 补充替代路径对比（`calibrate_impact_multipliers` 死代码）说明为何本次不选。
- **m4** 行号精确化（`estimate_ate` 不足分支 L239-244）。
- **m5** 源A 持久化补点细化（每标注即落盘）。
- **m6** 声明 treatment 预注册、禁 p-hacking；报告效应量。
- **m7** 诚实声明效应量极小（d≈0.011）的实务边界。

***

## 八 · 修改建议（供作者执行）

1. **§2.2 源B 契约**：`treatment = R_up>median`（实测 significant），`X=[R_down,R_smooth,R_flow,R_reflexivity]`（去 treatment 共线）；备选敏感性分析 `long_only`。新增「退化保护」。
2. **§2.3 优先级**：删除 `live+bootstrap` 混合，改为「源A ≥500 独用，否则源B 独用」。
3. **§4.1 开关**：默认 `False`（遵 HC-AGI-07）；给出显式开启指引（环境变量/Shadow 验证后）。
4. **§5 TDD**：新增用例 `test_degenerate_treatment_returns_insufficient`、`test_no_mixed_source_estimation`、`test_bootstrap_treatment_R_up_is_significant`（用固定切片断言 significant）。
5. **§6 验收**：新增「treatment 预注册」与「效应量报告」列为必交付；显著性的含义绑定 treatment。
6. **新增 §1.1 观察性边界声明**：明确源B 为观察性代理，不宣称干预因果。

***

## 九 · 复审结论

**决议：修改后接受。** 完成上述 5 条 Major + 7 条 Minor 后，SPEC v2 可进入落地实现（T1 RED）。

***

## 十 · 评审报告勘误（v0.1 附加说明，2026-10-14）

> 本节为**落地前实证复核**后的勘误。不改变 v0.1 的多视角评审结论（Major/Minor 仍有效），仅**修正 §一 的 POC 证据口径**，并据此调整验收设计。

**勘误 1（POC 口径不自洽）：** §一 POC 表用 `X=[R_up,R_down,R_smooth,R_flow,R_reflexivity]`（**X5，含 treatment 定义变量 R_up**），而本报告「修改建议 1」要求 X 去掉 R_up（**X4**）。把 treatment 的定义变量放进 X 属**过控制/共线**，会放大甚至制造伪显著 → **X5 口径的方法学是错误的**。

**勘误 2（POC 不可复现）：** 落地前于全量 290,969 条（有效 279,452）复核：

| 口径 | treatment | ate | 95% CI | significant |
| :-- | :-- | :-- | :-- | :-- |
| X5（v0.1 POC 口径） | `R_up>median` | 0.00319 | [−7.5e-06, 0.00638] | **False** |
| X4（正确口径） | `R_up>median` | 0.00163 | [−0.00045, 0.00371] | False |

v0.1 记为 `0.00298 / [4.5e-05, 5.9e-03] / True`。文件仅增 48 行，CI 下界即由 `+4.5e-05` 翻转为 `−7.5e-06` → **原「显著」为 0 上的刀锋伪显著**，不可复现。

**勘误 3（正确口径下全部不显著）：** X4 口径下 `action=="long"`→−0.00204/False（符号较 v0.1 POC 的 +0.0053 翻转）；`light_long`→−0.00029/False；`short`→−0.0103/False；最近 20k/50k 条 → `ate=0.0`。**源B 无任何预注册 treatment 定义可稳定显著。**

**结论调整（已据用户裁决落入 SPEC v3）：**
- 验收② 从「`significant=True` 且 CI 不含 0」**降级为「如实报告 ate/CI/significant/效应量」**，显著与否不作为通过门槛。
- 验收①（可估计）③（对照可复现）不变；treatment 退化仍为阻断项。
- 新增 §6.2 调制副作用（恒定 ×0.95）裁决项。
- **本轮「再评审」须针对 SPEC v3 + 调研增补后的版本另行开展（v0.2）。**

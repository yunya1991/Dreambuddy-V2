# SPEC: A2 — 因果 ATE 历史样本接入（使 ATE 真正生效）

> **状态：** Spec（评审修订·v5：按 v0.2 评审修复 + 用户裁决落定，可落地）
> **创建：** 2026-10-14
> **代号：** A2（承接 A1/A3 的降级契约修复）
> **评审：** 已通过同行评审 → [SPEC评审报告_A2因果ATE历史样本接入_v0.1.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/SPEC评审报告_A2因果ATE历史样本接入_v0.1.md)（决议：修改后接受；Major 5 条、Minor 7 条已在 v2 修复）。
> **v3 修订（2026-10-14，实证复核）：** 落地前用真实数据复核发现 **v2 内部不自洽**——§2.2 设计用 X4（去 R_up 防共线）而 §6 引用的 POC 证据用 X5（含 R_up）；用 X4 复核后**无任何 treatment 定义可稳定显著**（详见 §六 实证复核表）。据用户裁决：**验收②从「统计显著」降级为「如实报告显著性 + 必交付效应量」**，本 v3 同步修订验收与边界声明。
> **v4 修订（2026-10-14，调研增补）：** 按用户指令先修订 SPEC（v3）→ 调研三方向（学术界+成熟 AI/ML 工程 / GitHub-pyWhy 开源生态 / 金融工程-量化业界）寻找「观察性数据无稳定显著因果效应」的可落地方案 → 增补 **§2.5 统计口径强化**、**§6.2 调制契约裁决升级**、**新增 §9 替代与增强方案**，并同步 §5/§7/§8。三线**一致结论**：问题在**设计**不在估计器；把「CI 含 0」判成「应恒定 ×0.95」是把「不确定」错当「负向证据」，业界支持**改为经济显著性门禁下的 no-op**。详见 §9。
> **v5 修订（2026-10-14，v0.2 评审修复 + 用户裁决）：** 用户已裁决 —— ①**采用经济显著性三态门禁**（废弃 A1 恒定 ×0.95）；②**τ 来源 = 交易成本折算**（双边成本+滑点 ≈5–10bps 折算到 reward 尺度，独立预注册）；③**按评审修 v5 后落地 T2**。据评审修复：**M1**（τ 独立经济来源 + 预注册 + 阈值稳健性 τ∈{0.02,0.05,0.1}）；**M2**（已核实 causalml **无 HAC**、仅 i.i.d. bootstrap → 定降级路径 = 自实现 stationary block bootstrap）；**M3**（三态门禁获用户授权，保留守门测试防回归）；同步 Minors（净收益边界声明、来源性质、试错披露、效应量口径）。评审报告：[v0.2](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/SPEC评审报告_A2因果ATE历史样本接入_v0.2.md)。
> **目标：** 为 `CausalEngine.estimate_ate` 接入 ≥500 条**历史已标注样本**，使 ATE 从「永远 `insufficient_samples` 中性降级」变为「真实可估计、可复现、如实报告效应量与显著性」，并以此因果先验调制主要矛盾 `strength`。
> **硬约束：** HC-AGI-02（异常→中性兜底）、HC-AGI-07（新模块**默认关闭**，Shadow 验证后开启）、HC-AGI-08（因果引擎最小样本量 **≥500，不得下调**）；FAIL-OPEN 铁律不可破坏。
> **决策基线（用户 2026-10-14 确认）：**
> 1. 样本来源策略 = **双源结合**（v2 修订：两源**独立估计、不混合**）。
> 2. 验收标准 = **估计成功 + 如实报告显著性 + 对照实验可复现**（v3 修订：**不再要求 significant=True**；显著性与效应量须如实交付，见 §六）。
> 3. 开关默认值 = **`False`**（遵 HC-AGI-07）；**验收期显式开启**做对照实验以证明「可估计」。
> 4. 调制契约（**v5 用户已裁决**）：**采用经济显著性三态门禁**（实质效应→方向调制 / 经济等价于零→no-op / 不确定→no-op），**废弃 A1 恒定「不显著→×0.95」**（见 §6.2、§9）。τ 来源 = **交易成本折算**，独立预注册，禁止事后反推。
> 5. A2 净收益边界（v5 新增声明）：源B 阶段 A2 的**实证净收益 = 消除「恒定 ×0.95 下偏」这一副作用 + 建立可估计/可复现/可审计的因果诊断管线**；**正向调制收益需待 P1（CATE/regime 分桶）或源A 累积 ≥500**。不得把 A2 表述为「已带来显著因果增益」。
> **不重复：** A1（样本不足/异常时 `_enhance_with_causal_ate` 中性 no-op + 仅真估计出 ATE 才按显著性调整）与 A3（`_warn_insufficient_once` 告警去重）已完成并验证，本 SPEC 不改其契约。

***

## 零 · 现状基线（代码验证）

### 0.1 为什么 ATE 从未生效

| 事实 | 证据 |
| :--- | :--- |
| 因果引擎最小样本量硬约束 = 500 | [causal_engine.py L91-L94](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/causal_engine.py#L91-L94) `MIN_SAMPLES = 500` |
| `estimate_ate` 样本 <500 → 直接返回 `ate=0.0 / significant=False / method="insufficient_samples"` | [causal_engine.py L239-L244](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/causal_engine.py#L239-L244) |
| **唯一真正调用 `estimate_ate` 的业务路径**，样本来自 `identify()` 的 `paths`（通常 5~8 条） | [contradiction_identifier.py L350-L402](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py#L350-L402) |
| 路径数 `<<500` → 每次识别恒命中 `insufficient_samples` → A1 契约下中性 no-op（安全，但 ATE 从未产出真实结果） | 同上 L382-L384 |
| 另一条「真实数据 ATE」入口 `calibrate_impact_multipliers` 已实现，但**无任何生产调用者**（仅 docs/tests 引用）→ 死代码 | [evolution_pipeline.py L258-L303](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L258-L303) |

**结论：** ATE 的调用链路健全且 FAIL-OPEN 安全，但**输入样本严重不足**，导致因果能力形同虚设。

### 0.2 现存可用的历史样本源（体量普查）

| 数据源 | 路径 | 体量 | 字段（可用性） | 判定 |
| :--- | :--- | :--- | :--- | :--- |
| **Shadow RL 样本（源B）** | `dreambuddy_evolution/gene_data/shadow_rl_samples.jsonl` | **290,921 条**（71 MB，2026-10-14 15:48 更新） | `symbol, state{R_up,R_down,R_smooth,R_flow,R_reflexivity,quality_score}, action(10 类), reward(realized, −1~1), next_state` | ✅ ≥500，含 covariate/treatment/y，**立即可用** |
| Shadow RL sqlite 后端 | `gene_data/shadow_rl_samples.db` | 719 MB（2026-10-04，已陈旧） | `samples(id,data,reward)` | ⚠ 后端陈旧，jsonl 为准 |
| StreamingSampleStore（读优化） | [streaming_sample_store.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/streaming_sample_store.py) | — | `append/read_range/stats/migrate_from_jsonl` | ✅ 已实现，可复用作读层 |
| W6 矛盾样本（源A） | `data/contradiction_samples.json`（由 `ContradictionWeightLearner` 管理） | **磁盘 0 条**（文件不存在） | `ts,power,time,consistency,market_weight,direction,confidence,actual_return`（延迟标注） | ⚠ 机制已在 [contradiction_identifier.py L37-L179](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py#L37-L179)，但未有效累积/持久化 |
| AGI 决策快照 | `data/agi_snapshot.jsonl` | 2,000 条（滚动窗口，仅当日 07:18→15:47） | 决策特征完整但**无已实现收益标签** | ❌ 无 y |
| live `market_data` | [evolution_pipeline.py L1481-L1505](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L1481-L1505) | 单窗口 `close/kline_data` | 同一窗口内无独立样本，且无收益标签 | ❌ |

**结论：** 存在一个 **29 万条、已含 (covariates, reward) 的历史样本源（源B）** 可立即让 ATE 生效；另有一个语义更贴合但需累积的实时源（源A）。二者**独立使用**即为本 SPEC 的双源设计。

**关键洞察：** `agi_snapshot.jsonl` 无收益标签、live `market_data` 无标签 → 「喂历史样本」**必须新增独立样本管线**，不能靠扩大 `paths`。

***

## 一 · 问题定义与观察性边界

### 1.1 因果命题

`_enhance_with_causal_ate` 要回答的**因果命题**是：

> 「主要矛盾的**信号强度**（treatment，高 vs 低）**因果地**影响未来收益（y）吗？」

现状把它压缩成「当前 6 条路径的 confidence 是否抬高 expected_return」，样本数恒 <500 → 恒中性。A2 要做的：**为同一命题接入历史已标注样本**，使 `estimate_ate` 能返回真实的 `(ate, lower, upper, significant, method)`。

### 1.2 观察性边界声明（评审 m2 修复）

- **源B 为观察性代理，非干预因果。** `R_up`/`quality_score` 等是**观测到的状态属性**，不是决策者可随机分配的干预（do(T)）。因此源B 的 ATE 是「**观察性关联的因果近似**」，存在反向因果/混淆风险（行情好→状态指标高→收益高）。
- **源A 更接近干预**：其 treatment（power）由矛盾结构决定，y 为后续实际收益，时序上 y 在主因之后，反向因果风险较低。
- **本 SPEC 不宣称 ATE 为严格的干预因果效应**；其定位是**有向先验/诊断**，用于有界调制 `strength`（±0.85~1.15），不单独驱动仓位。
- **效应量与显著性边界（v3 实证修订）**：即便把 ATE 估计出来，**效应量极小且当前不可稳定显著**。真实数据复核（§六）显示：`R_up>median` 命题 `ate≈0.0016`、`std(y)≈0.272` → Cohen's d≈0.006；各 treatment 定义的 95% CI **均包含 0**（`significant=False`）。故本能力**不得被表述为"显著提升收益"**，也不得作为「ATE 已验证有效」的依据；其定位仅为**可估计的因果诊断/有向先验**。

***

## 二 · 设计方案：双源历史因果样本库 `CausalSampleStore`

### 2.1 架构总览

```
                    ┌──────────────────────────────────────────────┐
  源A（实时·保真）   │  live: identify() → record_prediction +        │
  ──────────────────►│  label_previous(actual_return) 延迟标注        │──┐
                    └──────────────────────────────────────────────┘  │  独立估计
                                                                      ▼  （不混合）
                    ┌──────────────────────────────────────────────┐  ┌─────────────┐
  源B（批量·引导）   │  shadow_rl_samples.jsonl (290,921 条)         │─►│ build_ate_  │
  ──────────────────►│  StreamingSampleStore 读层 + 一次性内存缓存    │  │ samples()   │
                    └──────────────────────────────────────────────┘  └──────┬──────┘
                                                                              │ 源A≥500 → 独用源A；否则独用源B
                                                                              ▼
                                    CausalEngine.estimate_ate(X, treatment, y, method="dml")
                                                                              │
                                                                              ▼
                                       _enhance_with_causal_ate(primary, ...)  ── 显著/同向调制（A1 契约不变）
```

**新增模块：** `dreambuddy_evolution/core/causal_sample_store.py` — 双源样本库 + 视图构造 + 退化保护 + 缓存。

### 2.2 统一样本契约（两源归一到同一命题，**但独立估计**）

统一为三元组 `(X, treatment, y)`，命题均为「**信号强度高低 → 已实现收益**」：

| 源 | X（协变量） | treatment | y |
| :--- | :--- | :--- | :--- |
| **源A 实时** | `[power, time, consistency, market_weight]`（4 维矛盾分数） | `power > median(power)` | `actual_return`（延迟标注） |
| **源B 引导（v2 修订）** | `[R_down, R_smooth, R_flow, R_reflexivity]`（state 6 维**去掉 R_up 与 quality**，避免与 treatment 共线） | **`R_up > median(R_up)`**（连续型、保证两水平，**实测 significant=True**）；备选敏感性分析 `action ∈ {long,light_long} vs 其余`（亦实测显著） | `reward`（已实现收益，−1~1） |

> **v2 修订依据（评审 M1，致命）：** 原方案 `treatment = quality_score > median` **退化**——`quality_score` 分布为 `1.0→197,390` / `0.97→23,067` / `0.94→40,033` / `0.95→209` / `0.9→181`，median=1.0 → `> median` 几乎全 0 → 单水平 → causalml 报 "Treatment vector must have at least two levels" → 降级 `ate=0.0`、不显著。改为 `R_up > median`。
>
> **v3 修正（实证复核，重要）：** 评审 POC 报的 `R_up>median → ate=0.00298 / significant=True` 用的是 **X5（含 R_up）**，与本节设计的 **X4（去 R_up）** 不一致——把 treatment 的定义变量放进 X 属**过控制/共线**，会放大伪显著。用 X4 真实数据复核：`ate=0.00163`、CI `[-0.00045, 0.00371]`、**significant=False**；且该 POC 的显著性本就在 0 上刀锋横跳（文件仅增 48 行即由 CI 下界 `+4.5e-05` 翻转为 `-7.5e-06`）。**故本节保留 X4 设计**（去 R_up 防共线），并接受「当前不可稳定显著」的诚实结论（见 §六）。

**退化保护（评审 M1，必须）：** 构造后校验 `len(np.unique(treatment)) >= 2` 且两类样本数均 ≥ `min_n/10`；否则视为无效样本 → 返回空 → 上层 `insufficient_samples` 中性 no-op。

### 2.3 优先级与合并策略（v2 修订：**不混合**）

`build_ate_samples(min_n=500)`：

1. 先取**源A**（实时矛盾样本）中已标注样本：
   - 若 `n_A ≥ min_n` → **只返回源A**（`source="live"`，保真优先）。
2. 若 `n_A < min_n` → **只返回源B**（`source="bootstrap"`）。
   - 源B 立即 ≥500 → ATE 立刻可估计。
3. **两源不混合**（v2 修订，评审 M3）：源A `y=actual_return`（~1e-3）与源B `y=reward`（±1）量级差 3 个数量级、treatment 定义不同、混淆结构不同 → 混合估计无统计意义。**取消 v1 的 `"live+bootstrap"` 混合模式。**
4. 两源均 <500 或退化保护触发 → 返回空 → `insufficient_samples` 中性 no-op（**FAIL-OPEN 语义不变**）。

### 2.4 性能与缓存（热路径保护）

`_enhance_with_causal_ate` 在 `identify()` 热路径内。避免每次读 29 万行走 IO：

- `CausalSampleStore` 采用**单例 + 内存缓存**：源B 首次装载（可经 `StreamingSampleStore.read_all`）后常驻内存数组；按 jsonl `mtime + 大小` 判失效。
- **ATE 结果缓存**（TTL 默认 3600s）：因果先验是全局量，不必逐次识别重算；TTL 到期或有新标注样本时才重估。
- **不设默认条数上限（v3 实证修订）：** 实测「最近 20,000 / 50,000 条」切片 → `ate=0.0`（不可估计）；故默认取**全量**（经单例缓存只装载一次），regime 漂移缓解改由后续分桶处理，不再用截断。
- 装载失败/超时 → FAIL-OPEN，退化为源A-only（继续 <500 → 中性 no-op）。

### 2.5 统计口径强化（v4 调研增补，方法学必要性）

源B 为**重叠、强自相关**的时序样本（相邻 slice 高度相关），且 y **零膨胀**（仅 14.8% 非零）。据调研（§9），须补三条口径，否则 CI 不可信、判定失真：

- **block bootstrap 修正（P0，v5 已核实落地路径）**：源B 时序重叠 → CI **不得**依赖 i.i.d. 近似。**核实结论（T2 前置，2026-10-14）：causalml 无 HAC/Newey-West 支持；其 `estimate_ate(bootstrap_ci=True)` 为 i.i.d. bootstrap（`rng.choice(arange(n))`，见 `causalml/inference/meta/base.py::bootstrap`），对重叠样本同样失真。** 故 **v5 定降级路径 = 自实现 stationary block bootstrap（NumPy-only，块长 ≈⌈n^(1/3)⌉）**；`estimate_ate` 返回值增补 **`ci_method`** 字段（`"asymptotic"` / `"iid_bootstrap"` / `"block_bootstrap"`）；**SESOI 门禁只采信 `block_bootstrap` 口径**；该口径不可得 → **态C no-op**（FAIL-OPEN）。
- **positivity / overlap 诊断（P0，仅诊断不阻断）**：报告倾向得分尾部占比（极端权重样本比例）与 trimming 前后 ate 差；若重叠严重不足 → 在证据报告中**显式声明「数据不支撑可比对照」**，作为「不显著」的合法理由（Crump et al. 2009；Li, Morgan & Zaslavsky 2018 overlap weights）。
- **treatment 预注册（P0，已含于评审 m6）**：固定 `R_up>median`，**不得事后在多口径中挑选显著者**；若做多口径敏感性分析，须套 **FDR（Benjamini-Hochberg 1995）** 校正。

***

## 三 · 接入点与数据流

| 环节 | 位置 | 改动 |
| :--- | :--- | :--- |
| 样本写入（源A） | `PrimaryContradictionIdentifier.identify()` 内已有 `_weight_learner.record_prediction(...)` / `_label_previous_from_market(...)` | **复用 + 补持久化**（评审 m5）：标注发生时即落盘（或在 `label_previous` 后触发 `_save`），避免 <100 条进程重启丢失 |
| 样本构造 | 新增 `causal_sample_store.py::build_ate_samples()` | 新增（含退化保护） |
| ATE 调用 | [contradiction_identifier.py L376](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/contradiction_identifier.py#L376) | **替换输入**：`X/treatment/returns` 改为 `CausalSampleStore.build_ate_samples()` 输出；调制逻辑 L385-L399 **保持 A1 契约不变** |
| 开关 | [agi_config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/agi_config.py) | 新增 `enable_causal_historical_samples`（见 §四，**默认 False**） |
| 死代码（本次不动） | `EvolutionPipeline.calibrate_impact_multipliers` | 评审 m3：本次不选该替代路径（其需 factor_matrix/returns/**phases** 三源对齐，数据成本更高）；保留后续单独 SPEC |

***

## 四 · 开关与降级策略

### 4.1 新增开关（v2 修订：遵 HC-AGI-07 默认关闭）

```python
# agi_config.py
"enable_causal_historical_samples": False,   # A2: ATE 历史样本接入（HC-AGI-07 默认关；Shadow 验证后开启）
```

- **默认 `False`**（评审 M4 / HC-AGI-07）：新认知模块默认关闭，Shadow 模式验证 ≥7 天 + 正向后才能放量。回滚/开启均无需改码。
- **开启指引（显式）：** 环境变量 `ENABLE_CAUSAL_HISTORICAL_SAMPLES=1`，或运行期 `set_switch("enable_causal_historical_samples", True)`，或 Shadow 验证通过后改默认值。
- 开启后最坏情形仍为中性 no-op（全程 FAIL-OPEN），无实盘风险。

### 4.2 降级矩阵（FAIL-OPEN，逐层）

| 条件 | 行为 |
| :--- | :--- |
| 开关 `enable_causal_historical_samples=False` | 不读历史样本，退回 live paths（中性 no-op） |
| 样本装载异常 / jsonl 缺失 / 缓存不可用 | 退化为源A-only；仍 <500 → 中性 no-op |
| **treatment 退化（水平数 <2）** | 视样本无效 → 中性 no-op（**v2 新增，评审 M1**） |
| 双源均（有效）<500 | `insufficient_samples` → 中性 no-op（A1 契约） |
| `estimate_ate` 抛异常 | `method="error"` → 中性 no-op（A1 契约） |
| ATE 的 `ci_method` 为 `asymptotic` / `iid_bootstrap`（非 `block_bootstrap`） | **态C** → no-op（v5 门禁只采信 block bootstrap）|
| **态A**：CI 不含 0 且 `\|ate\| ≥ τ` | 方向调制：同向 `×1.15` / 反向 `×0.85`（v5）|
| **态B**：TOST 拒绝 `\|ate\| ≥ τ`（CI ⊆ `(−τ,+τ)`） | **no-op**（v5，替代旧 `×0.95`）|
| **态C**：其余（功效不足 / CI 宽 / positivity 不足） | **no-op**（FAIL-OPEN）|

**HC-AGI-08 保持：** `MIN_SAMPLES` 仍为 500，**不得下调**；测试断言 `CausalEngine.MIN_SAMPLES == 500`。

***

## 五 · TDD 测试计划（RED → GREEN → REFACTOR）

新增测试文件：`dreambuddy_evolution/tests/test_causal_sample_store.py`
（**回归时避开** `test_p3_agi_pipeline.py` / `test_evolution_pipeline.py`，二者会长时间挂起，与代码无关）

### RED（先写失败测试）

`TestCausalSampleStore`：
1. `test_bootstrap_returns_ge_500_when_shadow_rl_present` — fixture jsonl（≥600 条合成样本）→ `n≥500`、`source=="bootstrap"`、`X.shape[0]` 与 treatment/y 长度对齐。
2. `test_live_source_priority_when_enough` — 源A 600 条已标注 → `source=="live"`，且**不使用源B**。
3. `test_no_mixed_source_estimation` — 源A 100 条 + 源B 600 条 → 结果 `source=="bootstrap"`（**绝不产生 `"live+bootstrap"`**，评审 M3）。
4. `test_both_insufficient_returns_none` — 源A 0 + 源B 无文件 → 返回空 → 上层 `method=="insufficient_samples"`。
5. `test_label_and_persist_contradiction_sample` — 写入+延迟标注后能重新读回（持久化正确）。
6. `test_missing_file_fail_open` — 源B 路径不存在 → 不抛异常，返回空。
7. `test_bootstrap_cache_invalidation_on_mtime_change` — 文件更新后缓存失效并重载。
8. `test_degenerate_treatment_returns_insufficient`（**新增，评审 M1**）— 构造 `R_up` 恒定（单水平）样本 → 退化保护触发 → 返回空 → `method=="insufficient_samples"`。
9. `test_bootstrap_treatment_R_up_is_significant`（**新增，评审 M2**）— 用**合成强效应 + 固定种子切片**验证「管线能如实产出显著结论」的通路；**注（v3）**：该用例验证的是管线能力，**不代表真实源B 显著**（真实源B 按 X4 口径实测不显著，见 §6.1）。

`TestAteEffectiveness`（增补 `test_contradiction_identifier.py::TestCausalATEEnhancement`）：
10. `test_real_ate_from_historical_samples_adjusts_strength` — 注入真 `CausalEngine` + 充足历史样本 → `causal_ate.method ∈ {causalml_dml,causalml_s,causalml_t,linear_regression}`。
11. `test_insufficient_still_noop` — 历史样本 <500 → `strength` **不变**（A1 契约不回归）。
12. `test_switch_off_reverts_to_live_paths` — 开关 False → 不读历史样本。

`TestMinSamplesInvariant`：
13. `test_min_samples_remains_500` — `CausalEngine.MIN_SAMPLES == 500`（HC-AGI-08 守门）。

**v4 调研增补用例（纳入 T1 增补，T3 后转绿）：**
14. `test_insignificant_observational_source_is_noop` — 观测性源 ate 不显著且 `|ate| < τ` → `strength` **逐位不变**（替代旧 ×0.95 契约；**用户 2026-10-14 已裁决采用 §6.2 门禁，启用**）。
15. `test_ate_report_contains_effect_size_and_ci_method` — 返回值/证据含 `effect_size`（Cohen's d）与 `ci_method` 字段。
16. `test_tost_equivalence_gate_classification` — 构造 `|ate|<τ` 样本 → 判为态 B（no-op）；构造 CI 不含 0 且 `|ate|≥τ` → 判为态 A（方向调制）。
17. `test_positivity_diagnostic_reported` — 诊断字段存在（tail 占比 / trimming 前后 ate），仅诊断不阻断。
18. `test_ate_returns_block_bootstrap_ci_method` — 观测性源 CI 口径为 `block_bootstrap`；门禁**拒收** `asymptotic`/`iid_bootstrap`（→ 态C no-op）。
19. `test_sesoi_threshold_robustness` — τ ∈ {0.02, 0.05, 0.1} 三档判定态一致（观测性源均落态 B）。
20. `test_trial_count_disclosed_in_report` — 证据报告含历史试错次数 + FDR/DSR 折减字段（评审 m6）。

> **注：** 现有 `test_small_sample_integration_is_noop` 需同步更新为「显式关闭开关」或「store 返回 <500」场景，否则开启默认后会因历史样本可用而改变行为。

### GREEN
实现 `CausalSampleStore` + 改造 `_enhance_with_causal_ate` 输入，令上述测试转绿。

### REFACTOR
- 抽取 `_to_ate_triplet(records, mode)` 与 `_validate_treatment(treatment, min_n)` 纯函数；
- 缓存策略抽为 `_cached_ate_or_recompute()`；
- 保持全量非回归（排除挂起两文件）。

***

## 六 · 验收标准（v3：可估计 + 如实报告，**不强制显著**）

三条同时满足方判「ATE 生效」：

| 维度 | 判据 | 验证方式 |
| :--- | :--- | :--- |
| **① 估计成功** | `estimate_ate` 返回 `method ∈ {causalml_dml, causalml_s, causalml_t, linear_regression}`（**非** `insufficient_samples`/`error`） | 真 `CausalEngine` + ≥500 有效样本，断言 method 白名单 |
| **② 如实报告（v3 修订，替代原「统计显著」）** | 固定 treatment = `R_up > median`（**预注册，不得事后挑选**）→ 报告须**如实给出** `ate / CI / significant / 效应量`；**不设 `significant=True` 为通过条件**。`treatment` 退化（水平数<2 / 类别占比过低）仍为**阻断项** | 全量源B 复核 → 断言 method 白名单 + 效应量字段存在；显著与否如实记录 |
| **③ 对照实验（可复现）** | **对照 A**：同一 `paths`/`market_data`，开关 True vs False 两次 `identify()`，断言 True 组 `causal_ate.method` 变化且 `strength` 按 A1 契约偏移；**对照 B**：有效样本 ≥500 时被调制，`<500` 或 treatment 退化时 `strength` **逐位相同**。固定种子 + 固定切片 → 数值可复现 | pytest + 证据报告 |

**必交付：** 报告须含**效应量**（ate/std(y)，Cohen's d）与**诚实边界声明**；不得只报 p/CI，也不得把「可估计」表述为「已显著 / 已有效」。

### 6.1 实证复核（v3，全量 290,969 条，有效 279,452，`y=reward`）

| treatment | X | ate | 95% CI | significant | method |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `quality_score>median`（v1 原方案） | 任意 | 0.0 | [0, 0] | **False（退化）** | linear_regression（causalml 报错降级） |
| `R_up>median`（评审 POC 口径） | **X5 含 R_up** | 0.00319 | **[−7.5e-06, 0.00638]** | **False** | causalml_dml |
| **`R_up>median`（本 SPEC §2.2 设计口径）** | **X4 去 R_up** | 0.00163 | [−0.00045, 0.00371] | **False** | causalml_dml |
| `action=="long"` vs 其余 | X4 | −0.00204 | [−0.00459, 0.00052] | False | causalml_dml |
| `light_long` vs 其余 | X4 | −0.00029 | [−0.00116, 0.00058] | False | causalml_dml |
| `short` vs 其余 | X4 | −0.0103 | [−0.04890, 0.02829] | False | causalml_dml |
| 最近 20,000 / 50,000 条 | X4 | 0.0 | [0, 0] | False | causalml_dml |

**结论（v3 关键）：**
1. 评审 POC 的 `significant=True` **不可复现且为刀锋伪显著**：同一 X5 口径，文件仅增 48 行，CI 下界由 `+4.5e-05` 翻转为 `−7.5e-06`。
2. 评审 POC 引用的 X5 与 §2.2 设计的 X4 不一致——把 treatment 定义变量放进 X 属**过控制**，会制造伪显著；X4 才是方法学上正确的口径。
3. **按 X4 口径，源B 无任何预注册 treatment 定义可稳定显著**（含备选 `long_only`，其符号从 +0.0053 翻转为 −0.0020）。
4. 效应量 d≈0.006（ate 0.00163 / std(y) 0.272）→ 实务影响≈0。

**因此：验收②落为「如实报告」，显著与否不作为通过门槛。**

### 6.2 调制契约裁决（v4 调研增补 → v5 用户裁决落定：经济显著性三态门禁）

**问题回顾（v3）：** 源B ATE 恒不显著，若开关开启，A1 契约「不显著→×0.95」将**每次识别恒定触发** → `strength` 系统性下偏 5% 且**不携带任何信息**（污染下游 WeightLearner）。三条调研线**一致判定这是反模式**：业界收缩（Bayes-Stein / Black-Litterman / Jorion）均为**数据依赖、精度加权、随样本量增大而消失**；恒定乘法系数「无先验依据、不收敛到 1.0、对每个信号一律向下偏置」。

**v4 建议（替代 v3 的选项1/选项2 二分）：** 采用**经济显著性门禁（SESOI + TOST）三态**，替换 A1 二元显著性判定：

| 态 | 判据 | 动作 |
| :--- | :--- | :--- |
| **A 实质效应** | CI **不含 0** 且 `\|ate\| ≥ τ`（τ = d_SESOI·std(y)）| 方向调制：同向 ×1.15 / 反向 ×0.85 |
| **B 经济等价于零** | TOST 拒绝「\|ate\| ≥ τ」（CI 完全落在 `(−τ,+τ)`）| **no-op**（不砍） |
| **C 不确定（功效不足 / CI 宽 / positivity 不足）** | 其余（含 CI 含 0 但超出 ±τ） | **no-op**（FAIL-OPEN） |

- **τ（SESOI）来源（v5 用户裁决 · 独立预注册）：** **交易成本折算** —— τ = 双边换手成本 + 滑点（≈5–10 bps）折算到 reward 尺度；**在观测 ate 之前**由经济理由确定，**禁止事后反推**（评审 M1）。须附**阈值稳健性** τ ∈ {0.02, 0.05, 0.1} 三档，**三档判定态一致**方可宣称结论稳健（观测 `d≈0.006` 在任一档下均落**态 B**）。
- **TOST 计算来源（v5，评审 m1）：** 与「CI 完全落在 `(−τ,+τ)`」同解；实现用 `statsmodels.stats.weightstats.ztost_mean` 或自实现 CI 包含判定，二选一并注明。
- **效果：** 消除恒定 5% 下偏；`strength` 仅在有**真实、可区分于零**的因果信号时才被调制；全程 FAIL-OPEN、有界（±15%）。
- **授权状态（v5 用户已确认）：** 用户 2026-10-14 裁决**采用三态门禁**；契约修改自 A1 硬约束 `VM-1791963721822-a7f9bae4`（同源变更已另记 B 级认知 `VM-1791968165872-b72966e0`）；T3/T7 **已获授权落地**，保留守门测试（§5 #14/#19）防回归。
- **回退：** 开关默认关（HC-AGI-07）；如需**完全回退 A1 原契约**，改 `enable_causal_historical_samples=False`（默认即 False），无需改码。

**证据产物：** `docs/audit_reports/a2_ate_effectiveness_<ts>.md`（含 method/ate/CI/`ci_method`/significant、**效应量**、positivity 诊断、TOST 判定态、对照 A/B、可复现种子与命令、诚实边界）。

***

## 七 · 风险与回滚

| 风险 | 影响 | 缓解 |
| :--- | :--- | :--- |
| **源B treatment 退化（设计缺陷）** | ATE 恒 0、不显著 | v2 改用 `R_up>median` + **退化保护**（§2.2）；测试 #8 守门 |
| **源A/源B 混合不可比** | 混合 ATE 无统计意义 | v2 **取消混合**（§2.3）；测试 #3 守门 |
| **评审 POC 不可复现（v3 新发现）** | 曾据伪显著做验收设计 | v3 降级验收②为「如实报告」；§6.1 实证复核表；X4 口径为准 |
| **恒定 ×0.95 无信息偏置（调研确认反模式）** | `strength` 系统性下偏 5%、不携带信息 | v4 改经济显著性三态门禁（§6.2）；未裁决前开关默认关 |
| **CI 未修正自相关 → 假显著/假不显著** | 判定失真 | §2.5 已核实 causalml 无 HAC、仅 i.i.d. → **自实现 block bootstrap**；门禁只采信 block 口径，否则态C no-op |
| **ATE≈0 由正负异质相消（掩盖真实子群信号）** | 误判全局零 | §9.2 CATE/regime 分桶（P1，后续独立 SPEC）|
| **τ 事后设定（结果导向）** | 等价性检验沦为事后合理化 | v5 τ 独立经济来源（交易成本折算）+ 预注册 + 三档稳健性；测试 #19 |
| **效应量极小（d≈0.006）** | 实务价值≈0，易被夸大 | §1.2 显式边界；验收必交付效应量；仅作有向先验/诊断 |
| 源B 观察性代理 ≠ 干预因果 | 因果解释偏差 | §1.2 观察性边界；源A 累积后优先以源A 为准 |
| 源B 分布与 identify() 时点错配（全时段 vs 有信号时） | 因果先验分布偏差 | 对照实验检验；必要时按 regime/时点分桶（`calibrate_multipliers` 已有分桶能力） |
| 装载 29 万行拖慢热路径 | 识别延迟上升 | 单例 + 内存缓存 + ATE 结果 TTL(3600s) + mtime 失效；超时 FAIL-OPEN |
| 历史样本 regime 漂移 | 因果先验滞后 | ~~只取最近 N 条~~（v3 实证：截断→ate=0）；改由后续 regime 分桶处理 |
| 误把 ATE 调制放大到实盘 | 仓位风险 | A1 契约不变（仅 ×0.95/1.15/0.85 有界调制）；开关默认关；HC-AGI-02 兜底 |
| HC-AGI-08 被误下调 | 违反硬约束 | 测试 #13 守门 + 认知库 B 级记录 |

> **回滚决策项（§6.2）：** 选项 1 保 A1 契约 / 选项 2 观测性源不显著→no-op。落地前需用户裁决（默认按选项 1 实现以不破坏 A1 契约，但显式标注偏置风险）。

**回滚：** `enable_causal_historical_samples=False`（默认即 False，无需改码）；如仍异常，`enable_causal_engine=False` 彻底关闭因果链。

***

## 八 · 任务分解（TDD 顺序）

| 任务 | 内容 | 产出 |
| :--- | :--- | :--- |
| **T1** | RED：新建 `test_causal_sample_store.py`（#1–#9，含退化保护与显著性用例）+ 增补 `TestCausalATEEnhancement`（#10–#12）+ `TestMinSamplesInvariant`（#13）+ 更新现有 `test_small_sample_integration_is_noop`，确认红 | 失败测试 |
| **T2** | GREEN：实现 `core/causal_sample_store.py`（双源/独立估计/退化保护/缓存/FAIL-OPEN）+ **自实现 stationary block bootstrap CI**（前置核实 causalml 无 HAC，已完成）| 新模块 |
| **T3** | GREEN：改造 `_enhance_with_causal_ate` 输入 + 新增开关（默认 False）+ 源A 持久化补点 + **三态门禁判定分支（用户已授权）** | 改造 |
| **T4** | REFACTOR：抽取 `_to_ate_triplet`/`_validate_treatment`/`_cached_ate_or_recompute`，全量非回归（排除挂起文件） | 无回归 |
| **T5** | 验收：对照 A/B + 源B **如实显著性/效应量**证据（不强制显著）→ `docs/audit_reports/a2_ate_effectiveness_<ts>.md` | 验收证据 |
| **T6** | 收尾：`record` 认知闭环（B 级硬约束）+ 更新 ENGINEERING_INDEX/CHANGELOG + commit | 闭环 |
| **T7** | v5：三态门禁（§6.2）+ 效应量/`ci_method` 报告 + block bootstrap CI + positivity 诊断（§2.5）+ 试错披露（评审 m6）| 增强落地 |

***

## 九 · 替代与增强方案（v4 调研增补）

> **调研方法：** 3 条并行线独立检索并核实来源——① 学术界 + 成熟 AI/ML 工程方法论；② GitHub/pyWhy 开源生态与工具；③ 金融工程 / 量化业界实践。
> **三线一致结论：** **问题在设计，不在估计器**——`R_up>median` / `action==long` **不是可操纵干预**（do(T)），y 零膨胀（14.8% 非零）+ 强自相关 + positivity 差 → `ATE≈0.0016` 是**诚实的零**；把「CI 含 0」判成「应砍 5%」是把**「不确定」错当「负向证据」**。
> **A2 净收益边界（v5 声明）：** 源B 阶段落地三态门禁后 ATE 恒落**态B → no-op**，A2 的实证净收益 = **去偏 + 建立可审计因果诊断管线**；**正向调制收益需待 P1（CATE/regime 分桶）或源A 累积 ≥500**。
> **来源性质：** §9.1/§9.2 引自一手方法论（Lakens 2017、VanderWeele & Ding 2017、Newey & West 1987、BH 1995、Crump 2009、Bayes-Stein/Jorion 1986、Grinold）；调研线自标「待核实」项**不得作落地依据**，清单见 §9.5。

### 9.1 P0 增强（已纳入本 SPEC 落地范围）

| 增强 | 原理 / 来源 | 落点 | 成本 | HC-AGI 兼容 |
| :--- | :--- | :--- | :--- | :--- |
| **经济显著性三态门禁（SESOI+TOST）** | 用 TOST 正面拒绝「效应 ≥ SESOI」，把「不显著」转述为「有证据的零」（Lakens 2017；Harms & Lakens 2018；Halsey 2025）| §6.2 + 判定逻辑 | 低 | ✅ |
| **效应量 + CI 正统报告 + E-value** | 弃二值 p 门槛，报 d / E-value / 敏感性边界（ASA 2016；VanderWeele & Ding 2017）| §6 验收必交付 | 低 | ✅ |
| **HAC / block bootstrap CI** | 时序重叠样本须修正方差（Newey & West 1987；Politis-Romano）| §2.5 | 中 | ✅ |
| **positivity / overlap 诊断** | 证明「数据不支撑可比对照」是合法的「不显著」理由（Crump 2009；Li et al. 2018）| §2.5 | 低 | ✅ |
| **treatment 预注册 + FDR** | 固定口径、防 p-hacking（Benjamini-Hochberg 1995）| §2.5 | 低 | ✅ |

### 9.2 P1 后续增强（建议独立小 SPEC，**不在 A2 落地**）

| 增强 | 原理 / 来源 | 价值 | 成本 |
| :--- | :--- | :--- | :--- |
| **CATE / regime 分桶** | ATE≈0 可能由正负异质相消；按波动率/趋势/流动性分桶估条件效应（Wager & Athey 2018；causalml S/T/X/R/DR-learner；GATES）| **最可能捞到真实信号**；可把「全局恒砍」改为「仅显著子群 ×1.15」（`calibrate_impact_multipliers` 已有分桶能力）| 高 |
| **Bayesian shrinkage 后验（先验 mean=0）** | 精度加权后验替代恒定乘法，随样本量增大收敛到 1.0（Bayes-Stein/Jorion 1986；Black-Litterman）| 替代/软化 ×0.95，数据依赖、收敛 | 中 |
| **Grinold 式 IC 线性映射** | α = IC·z·σ，IC→0 则 α→0（Grinold 基本法则）| 调制幅度随信号 skill 连续缩放，替代固定 ±15% | 低 |

### 9.3 P2 观察项（暂不落地，记入风险 / 免责）

| 方案 | 现状 | 判定 |
| :--- | :--- | :--- |
| **TMLE / doubly robust / AIPW 替换** | causalml 提供 `TMLE`/`DRLearner`；仅改点估计质量，**不改变不显著结论** | 待后续；非本困境解 |
| **negative control outcome/exposure / placebo** | 可用 state 6 维中「应无关」维度做负对照（Lipsitch 2010；placeboLM 2024）| 中价值 |
| **Manski bounds / partial identification** | 只给宽区间（含 0），诚实但无信息 | 观察 |
| **proximal causal inference** | **无成熟 Python 库**（`pci2s` 仅 R；研究代码）| ❌ 工程化不足，不依赖 |

### 9.4 工具映射（可直接插入现有 causalml 管线）

| 能力 | 工具 / API（已核实） | 集成成本 |
| :--- | :--- | :--- |
| ATE 的 `(te, lb, ub)` CI（**现用库已具备**）| causalml `estimate_ate()` 返回三元组 | **零改造**——判定口径由「p 值」改为 `lb/ub` |
| refutation + E-value 敏感性 | DoWhy `refute_estimate(placebo_treatment_refuter / random_common_cause / data_subset_refuter)`；`add_unobserved_common_cause(simulation_method="e-value")` | 低（DoWhy 可挂 causalml 后端）|
| 敏感性上下界 | DoubleML `DoubleMLPLR.sensitivity_analysis()` → θ± 上下界 | 中高 |
| CATE 区间 | EconML `ate_inference / effect_interval`（`LinearDML`/`DRLearner`/`CausalForestDML`）| 中 |
| 等价性检验 TOST | `statsmodels.stats.weightstats.ztost_mean`；`experiment-utils-pd.test_equivalence` | 低 |
| 多重检验 FDR | `statsmodels.stats.multitest.multipletests(fdr_bh)` | 低 |
| 稳健性值 | PySensemakr `robustness_value / partial_r2`（依赖 statsmodels OLS，非 causalml 管线）| 中 |

### 9.5 待核实清单（v5）

| 项 | 状态（2026-10-14） | 处置 |
| :--- | :--- | :--- |
| `causalml` DML API | ✅ **已核实**：无独立 `DML` 类；实际用 `LRSRegressor().estimate_ate(X,treatment,y)→(te,lb,ub)`（`method` 记为 `causalml_dml`，属自建别名）| 沿用现路径 |
| causalml HAC / 自相关 CI | ✅ **已核实：不支持 HAC**；仅 i.i.d. bootstrap（`inference/meta/base.py::bootstrap`）| **自实现 stationary block bootstrap**（T2）|
| `ProximalCI` / 负对照库 Python 成熟度 | ⚠ 待核实（仅 R 侧成熟）| 不依赖（§9.3 P2）|
| Wager & Athey 2018 原文链接 | ⚠ 待核实（二手来源）| 不作落地依据；§9.2 仅方向性参考 |
| DoubleML / EconML 引入边界 | ⚠ 待评估 | 暂不引入（优先 `(te,lb,ub)` 零改造成本路径）|

***

## 附 · 认知闭环

- 本 SPEC 涉及 HC-AGI-07/08 硬约束，落地后须 `record(content="[硬约束][自进化/因果] A2: ATE 历史样本双源独立估计...", quality_level="B", tags="硬约束,HC-AGI-07,HC-AGI-08,自进化,因果推断,ATE历史样本")` 并 `verify`。
- 关联记忆：`VM-1791963721822-a7f9bae4`（A1+A3 降级契约，B 级）、`VM-1791964377401-f6115a5e`（A2 决策，B 级）。
- 评审报告：v0.1 → [docs/SPEC评审报告_A2因果ATE历史样本接入_v0.1.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/docs/SPEC评审报告_A2因果ATE历史样本接入_v0.1.md)（§十含 v3 实证勘误）；**v0.2（对 v4 调研增补后版本）→ `docs/SPEC评审报告_A2因果ATE历史样本接入_v0.2.md`（本轮产出）**。
- v4 调研增补（§9）新增「经济显著性三态门禁」契约，落地后须另 `record(content="[硬约束][自进化/因果] A2 v4: 观测量测不显著且|ate|<SESOI → no-op，废恒定×0.95 ...", quality_level="B", tags="硬约束,HC-AGI-08,自进化,因果推断,SESOI,TOST,经济显著性")` 并 `verify`。

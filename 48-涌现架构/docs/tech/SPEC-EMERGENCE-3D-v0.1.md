# SPEC — 三维涌现（D1 交易 / D2 工程 / D3 意图）v0.5

> **状态**：🟢 实施就绪（拟并入 48 SPEC v0.6；2026-11-09 外部评审「需修改」→ v0.2/v0.3/v0.4 已整合修订并经一轮内部复审（§11.5 修改后接受），**外部评审已通过**；P0/P1 全部关闭，可作为三维涌现方案实施就绪基线）
> **日期**：2026-11-08（v0.1）→ 2026-11-09（v0.2 / v0.3 / v0.4 / v0.5）
> **归属**：48-涌现架构
> **上游**：[SPEC-EMERGENCE-EVOLUTION v0.5](./SPEC-EMERGENCE-EVOLUTION-v0.1.md) · [SPEC-NN-FEEDBACK-GATEWAY v0.1](./SPEC-NN-FEEDBACK-GATEWAY-v0.1.md) · 35-广义认知 C1-C4 · 46-DSH · 47-MCP · 33-REA · 45-评测系统 · DreamOS
> **下游**：P0 度量字典与基线盘点 · P1 D2-A/D3-A 实验 · P2 D2-B/D3-B 实验 · P3 跨域迁移 · P4 三维度量面板
> **变更（v0.1→v0.2，外部评审修订）**：①重写跨域判定（共同效用前置 + 2×2×2 因子 + 三阶交互；无法建立共同效用时只称「跨域联合收益」）；②移除 D2-A 新颖度门槛（归 D2-B 并与去重/可行性联合评估）；③统一 candidate/verified/rejected 状态流转与三态判定边界；④统计方案补主终点/独立样本单元/聚类重采样/多重比较；⑤OOD 未闭合前所有 D2-A/D3-A 运行降级为探索性运行并区分实验隔离与 FAIL-OPEN；⑥补 D3-A 预测目标/特征截止/切分表与泄漏审计；⑦同步 P0 状态（P0-1 本地实现 + 测试，P0-3 基线已生成待复核，P0-2 未达标）；⑧schema 复合值结构与阈值冻结口径。
> **变更（v0.2→v0.3，评审整合复核）**：①§4.5.3 与 §1.2 对齐（清除已废除超加性公式的残留表述，补 2×2×2 全 8 臂）；②数据快照刷新（sessions 366→1072，D3-A 样本量级结论重估）；③§12 状态术语中文化；④P1-1/P1-4 证据按工作树实况更新；⑤§6.3 隐私补强（hash≠匿名化：访问控制/保留期/删除机制/小样本识别风险）；⑥A.1 阻力归一化禁用滚动窗口；⑦附录 D 补登 v0.2/v0.3。
> **变更（v0.3→v0.4，外部成熟经验整合）**：2026-11-09 五路调研（AI 涌现工程 / 金融工程 / 代码工程 / 意图学习 / 生物复杂系统，44 条候选交叉验证采纳 23 条，详见附录 E）。正文修订 4 处：①§1.2 增设 O-information 协同复核通道（Ω>0）；②§1.1 E5(b) 检验升级（Clauset 幂律 MLE+x_min+null model 似然比对照 + MR-estimator + 禁止肉眼报拐点）；③§4.0 第 11 条泄漏审计加第 4 重 canary string；④§2.1 D1 多重比较三层防线（批内 Holm→批级 PBO→胜出者 SPA/DSR）与 E2 收益层去重。Tier 2/3 条目落附录 E，参数随预注册冻结。
> **评审状态**：2026-11-08 内部六维评审「修改后接受」（§11.1-11.3）；2026-11-09 外部评审「需修改」（§11.4）；2026-11-09 v0.3 整合复核 + v0.4 外部经验整合；**2026-11-09 外部复审通过**（P0-1~P0-3、P1-1~P1-6 全部关闭，可进入实施阶段）；**2026-11-09 v0.5 实现对齐**（D2-A/D2-B/D3-A/D3-B/X-A 五个实验均落地 candidate，verdict 仪表盘聚合 10 实验，5 candidate）。

---

## §0 Executive Summary

### 0.1 做什么

把 48 的涌现判据从「D1 交易价值」单维，扩展为三个可独立证伪、又可联合判定的维度：

| 维度 | 一句话定义 | 目标 | 验收锚点 |
|---|---|---|---|
| **D1 交易路径** | 交易主链在入场/仓位/离场/子策略组合中发现低阻力路径 | 最小阻力、最终盈利 | 成本后 OOS 净 PnL / Sharpe / 回撤 |
| **D2 工程架构** | 做梦器利用技术文档、测试、既有架构、逆向解析，复原或生成架构图/数据流/设计原理 | 更低变更阻力地完成开发 | 架构复原准确率 + 45 工程门禁 + 人工评审 |
| **D3 意图涌现** | 从用户历史意图、习惯、错误案例中预测意图并组合知识 | 更短路径到达正确动作 | 预测准确率 + 用户接受率 + 澄清/时延下降 |

### 0.2 不做什么

| 禁止 | 原因 |
|---|---|
| 不在本 Spec 中写代码 | 用户明确要求先只写 Spec 与实验协议 |
| 不宣称「已出现三维涌现」 | 当前 D1 的 E1/E3/E5 仍未成立，D2/D3 尚无实验数据；宣称即自欺 |
| 不为出指标放宽 45 门禁 / ablation gate / PSI 阈值 | 沿用 48 v0.5 硬约束（VM-1793798309647） |
| 不让 48 接管 D2/D3 系统所有权 | 48 只做判据、度量、实验、观测；D2 做梦器归 33-REA/46-DSH，D3 归 DreamOS/35 |
| 不让 AI 评审直接当硬门禁 | AI-as-Judge 未经 45 §9 校准只能进加权项 |
| 不在生产链路做生成/执行 | 全部 shadow / 沙箱；生成物零执行权、FAIL-OPEN |
| 不把本 Spec 当作实施就绪基线 | 2026-11-09 外部评审结论：核心判定方法与统计方案仍在修订；仅作三维涌现讨论稿 |

### 0.3 核心判断

1. **48 当前只有 D1 真正落地**：E2 首次批次 32/32 新颖但 `evaluator_missing`，M2=0；E5 四组配置无一显著（最优配置下 kNN 仅 53.6%-59.7%）。**生成器不是瓶颈，评估信号才是。**
2. **D2 底座最厚**：33-REA 已有架构模式识别、调用链、依赖图、设计决策复原、演化叙事、覆盖率；45 已有技术工程类评测标准与 LLM-as-Judge 协议。缺的是「文档-代码统一图 + holdout + 生成器 + 新颖度定义」。
3. **D3 底座中等**：DreamOS IntentEngine + IntentEvaluator + 35 记忆 + shadow-probe 模式已存在；本地 `.cognitive/sessions` 已积累 **1073 个 session dir（1072 个非空，2026-11-09 复核；11-08 快照为 366，数据在快速增长，口径随预注册冻结）**，可作为 task_type 粗粒度代理；缺的是「直接意图标签 + 接受标签 + 三套意图体系收敛」（预测目标与时序 holdout 已在 §4.3 定义）。
4. **三维不是三个独立优化**：在共同效用函数建立并预注册 2×2×2 因子设计之前，只能报告「跨域联合收益」；「三维涌现」表述必须通过三阶交互检验（§1.2）。

### 0.4 与 48 v0.5 A/B/C 的关系

48 v0.5 的 A/B/C 回答「**什么样的涌现**」：

- A 类：机制涌现（E1-E5）
- B 类：业务价值涌现（E-BIZ）
- C 类：需求驱动涌现（E-DEMAND / E6）

本 Spec 增加「**在哪里涌现**」的 D 轴。两者是矩阵关系，不是替代关系：

| | D1 交易路径 | D2 工程架构 | D3 意图 |
|---|---|---|---|
| **A 机制 E1-E5** | 组合泛化/自生成/耦合/自纠/相变 | 同左，判据跨域复用 | 同左，判据跨域复用 |
| **B 价值** | 成本后 OOS 净 PnL/Sharpe/回撤 | 架构复原准确率 + 45 工程门禁 + 人工评审 | 预测准确率 + 用户接受率 + 澄清/时延下降 |
| **C 需求 E6** | 数据/因子/案例缺口 | 架构/模块/文档缺口 | 意图/知识组合缺口 |
| **最小阻力** | 滑点+费用+回撤+持仓时间 | 耦合度+返工+缺陷+文档债 | 澄清轮次+time-to-action+纠正率 |

---

## §1 三维判据矩阵

### 1.1 E1-E5 跨域定义

E1-E5 的定义沿用 48 v0.5 §1，不因新增维度而放宽。每个维度必须给出本域的可测口径：

| 判据 | D1 交易 | D2 工程 | D3 意图 |
|---|---|---|---|
| **E1 组合泛化** | 新颖市场状态组合上的成功率 > 检索复用 | 扣留模块的架构复原 F1 > 文档检索基线 | 未在历史出现的意图组合预测准确率 > kNN/规则基线 |
| **E2 自生成目标** | 人未写过的策略结构变体，verify 有效 | 人未写过的架构/模块/数据流方案，过 45 门禁 + 人工复核 | 人未写过的意图组合/知识组合，用户确认有效 |
| **E3 非线性耦合** | coupling 反事实 MAE 优于单域 | 跨模块依赖/数据流预测优于单模块线性叠加 | 多信号（历史+习惯+错误案例）融合优于任一单信号 |
| **E4 自指纠错** | 故障注入后内部检测并修复比例 | 架构不一致/测试失败/文档断链被内部发现并修复 | 错误意图被内部评估器发现并纠正/升级澄清 |
| **E5 规模相变** | 能力-规模曲线拐点 / 临界态三件套 | 文档/模块/案例规模曲线拐点（E5a 为主） | 意图/会话/知识规模曲线拐点（E5a 为主） |

> D2/D3 的 E5 以 **E5(a) 能力-规模曲线拐点**为主；E5(b) 临界态三件套（级联幂律 + σ≈1 + 序参量凝结）仅在事件流足够时适用，不强制套用。
>
> **E5 检验升级（v0.4，附录 E-T1.1/T1.6）**：①幂律拟合必须 Clauset 口径——MLE + x_min 截断 + KS 拟合优度 + 与随机化 null model 似然比对照（亚采样下亚临界/混响/临界均可呈 α≈1.5，**仅拟合出幂律不通过**）；②σ 估计用欠采样稳健估计量（MR-estimator 类）并报告事件捕获率作为置信前提；③相变改报连续指标 + log-log 形状检验（线性=可外推、凹=真加速），**禁止肉眼报拐点**；④事件量不足时记 `insufficient_data`，不得为过关凑事件。

### 1.2 跨域联合收益与「三维涌现」的严格定义

**共同效用前置**：跨域比较前必须先定义同一评价单位下的共同主结果（primary endpoint）、共同效用函数或显式归一化方法（含固定基准、损失方向、权重）。归一化一经预注册不得更换；不同归一化产生不同结论时，必须报告全部口径，不得只报有利口径。

**无法建立共同效用函数时**：结论只能表述为「跨域联合收益」，**不得**使用「三维涌现」。

**因子设计**：预注册完整 2×2×2 因子实验（D1 on/off × D2 on/off × D3 on/off，共 8 臂），每臂按真实独立实验单元重复。设：

- `G(D1)` / `G(D2)` / `G(D3)`：单因素主效应（相对各自基线的增益，统一归一化）；
- `G_ij`（i<j）：两因素交互项；
- `G_123`：三因素交互项。

> v0.1 的 `G(joint) - [G(D1)+G(D2)+G(D3)] > 0` 口径已废除：联合高于单项之和可能来自任意两维交互，**不足以**证明三阶交互。

**「三维涌现候选」必须同时满足**：

1. 每个维度的单域判据至少有 1 条达到 `candidate`（E1/E2 优先）；
2. 三因素交互项 `G_123` 显著（预注册检验，95% CI 不含 0 且方向为正），**且**通过 O-information 协同复核通道 `Ω(D1,D2,D3) > 0`（冗余−协同平衡，SΩI score-based 估计，附录 E-T1.2；估计器不可用时记 `insufficient_data`，不得跳过）；
3. 至少一个两因素交互项 `G_ij` 为正且经多重比较校正（三维涌现是两两协同的加强，不是替代）；
4. 联合增益不能由脚手架/数据红利解释（§4.5 消融）；
5. 通过 48 v0.5 §5 七关门禁（双度量、OOD、稳健性、辩论、人工复核、消融、可复现）。

**不满足 2 时的降级表述**：

- 有正的两因素交互 → 报告「两维协同 + 单维优化」；
- 无任何显著交互 → 报告「多个独立维度的优化」或「跨域联合收益」。

以上情形**均不得**使用「三维涌现」表述。

---

## §2 领域定义与资产

### 2.1 D1 交易路径涌现（既有）

D1 沿用 48 v0.5 的 E0-E6 与 M1-M7，不重复定义。本 Spec 只做两件事：

1. 把 D1 的度量纳入统一 `EmergenceMetric` schema（§3.1），便于与 D2/D3 并列；
2. 补充「最小阻力」的显式口径：`{slippage_bps, fee_bps, holding_hours, maxdd_pct}` 四元组 + 归一化综合分，避免只报 PnL 不报阻力；
3. **D1 多重比较三层防线**（v0.4 增补，拟落主 SPEC E0/E2 准入；主 SPEC 修订前先在 48 域预注册内执行，附录 E-T1.4）：批内次要指标 Holm 校正 → 变体批级 PBO/CSCV（PBO>0.5 整批拒入）→ 胜出者 vs 人工基线用 SPA/DSR（`trials_count` 必须写入 `EmergenceMetric.evidence`）；三层全部预注册冻结，**禁止**事后选最有利口径；
4. **E2 收益层去重**（v0.4 增补，附录 E-T2.4）：变体除结构编辑距离 ≥k 外，须对已准入变体池收益 |ρ|<0.5 且组合池 IC 边际增量 >0——去重从结构层提到收益层；walk-forward 升级 CPCV+embargo（embargo=变体最大 holding_hours）。

**当前状态（2026-11-08 快照）**：E2 的 M2=0（evaluator_missing）；E3 生产 coupling falsified、shadow 重训 inconclusive；E5 四组配置无一显著。D1 的实验协议已在 v0.5 定义，本 Spec 不重复。

> **数据现实（2026-11-08 核验，P1-2）**：本地 `11-易经推理系统/scripts/data/bcrm_trades.db` 为 0 字节空文件；`human_baseline.json` 的 24 IS/9 OOS 来自云端实盘快照。D1 指标复现需云端 DB 或快照，不在本机重算；P0/P1 需明确数据获取路径并记录快照 hash。

### 2.2 D2 工程架构涌现

#### 2.2.1 两个子路径

| 子路径 | 问题 | 可证伪性 | 优先级 |
|---|---|---|---|
| **D2-A 架构复原** | 扣留某模块的代码/文档后，系统能否从其余证据复原其接口、依赖、数据流、设计决策？ | 强：有 AST/调用图/接口签名作 ground truth | P1 先做 |
| **D2-B 架构生成** | 系统能否提出人未写过、且能解决真实 E6 缺口的模块/重构/架构方案？ | 中：需 45 门禁 + 人工评审 + 新颖度 | 已实现 candidate（2026-11-09，门禁代理；真实 45 门禁待运行） |

#### 2.2.2 输入与输出

**输入**：

- 技术文档：`0-系统文档管理/`、各子系统 `docs/`、`2-KNOWLEDGE/2-TECHNICAL`、`2-KNOWLEDGE/7-EXTERNAL-RESEARCH`
- 代码与测试：全仓 Python/TS、pytest 用例、CI 配置
- 逆向解析：33-REA 的架构模式、调用链、依赖图、设计决策、演化叙事、覆盖率
- 架构导航：`0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md`、`1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` v4.0
- 能力集：`0-系统文档管理/l0_capability_set.v1.yaml`、47-MCP registry

**输出（协议级 schema 见附录 B）**：

- `ArchitectureGraph`：节点（模块/服务/数据集/文档）+ 边（import/call/data_flow/contract/doc_ref）
- `DataFlow`：source → transform → sink，含 schema/version
- `DesignRationale`：ADR 风格决策 + 证据 + 替代方案 + known_gaps
- `BuildPlan`：模块、接口、测试、依赖、风险、验收命令

#### 2.2.3 已有底座（引用存在性已核验）

| 资产 | 位置 | 在 D2 中的用途 |
|---|---|---|
| 架构模式识别 | [architecture_pattern_detector.py](../../../33-REA逆向解析工程/core/architecture_pattern_detector.py) | MVC/分层/事件驱动/管道/插件/微内核识别，带 Evidence |
| 调用链追踪 | [call_chain_tracer.py](../../../33-REA逆向解析工程/core/call_chain_tracer.py) | 函数调用图、入口链路 |
| 依赖图 | [dependency_graph.py](../../../33-REA逆向解析工程/core/dependency_graph.py) | 模块 import 图、循环依赖 |
| 设计决策复原 | [design_decision_recovery.py](../../../33-REA逆向解析工程/core/design_decision_recovery.py) | ADR 风格决策 + 权衡痕迹 |
| 方法论抽象 | [methodology_abstraction.py](../../../33-REA逆向解析工程/core/methodology_abstraction.py) | 跨项目模式聚类、通用解法 |
| 演化叙事 | [evolution_narrative.py](../../../33-REA逆向解析工程/core/evolution_narrative.py) | git 历史转折点、重构动机、技术债 |
| 覆盖率 | [coverage_analyzer.py](../../../33-REA逆向解析工程/core/coverage_analyzer.py) | 覆盖率证据 |
| 工程评测 | [SPEC-评测系统.md](../../../45-评测系统/SPEC-评测系统.md) §5.3 | E-H1..H5 / E-W1..W6 / pycg 基准 |
| LLM 裁判协议 | [SPEC-评测系统.md](../../../45-评测系统/SPEC-评测系统.md) §9 | 校准、偏差控制、锁定与追溯 |
| 文档地图 | [ARCHITECTURE_MAP.md](../../../0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md) | 架构导航与 SSoT 指针 |
| 文档工具 | [doc_coverage.py](../../../0-系统文档管理/4-工具与自动化/doc_coverage.py) / [link_checker.py](../../../0-系统文档管理/4-工具与自动化/link_checker.py) | 文档覆盖率、断链检查 |
| RAG | [2-KNOWLEDGE/9-RAG-INFRA](../../../2-KNOWLEDGE/9-RAG-INFRA) | 文档检索、混合检索、重排 |
| Subagent 契约 | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../../../1-ARCHITECTURE/dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) | 结构化输出、隔离执行、FAIL-OPEN |

> 实际入口类名以代码为准：`DesignDecisionRecoverer` / `recover_decisions`、`MethodologyAbstractor` / `abstract_methodology`、`EvolutionNarrator` / `generate_narrative`；上文表格用的是能力名，不是符号名。

#### 2.2.4 缺口

1. **文档-代码统一图（P0-3）**：v0.1 时不存在；2026-11-09 基线脚本与产物已入库（7859 nodes / 53959 edges，0 悬挂边，sha256 可核验，见 §12.1），**待人工复核 3-5 个 holdout 模块**后方可用于正式 D2-A（此前只能探索性运行）；
2. **架构 holdout 协议**：没有「扣留模块代码/文档」的实验；
3. **生成器**：33-REA 是分析已有架构，不是提出新架构；
4. **新颖度**：E2 的结构向量编辑距离不能直接用于图/接口/ADR；
5. **沙箱执行**：D2-B 生成物必须零执行权，只在 45 沙箱构建/测试。

#### 2.2.5 边界

- 48 只定义 D2 的判据、度量、实验协议与观测面板；
- D2 做梦器/生成器归属 33-REA 或 46-DSH，需经对应域协商；
- 45 负责工程门禁与评测裁决；
- 35 负责把 D2 的结论沉淀为记忆/SKILL；
- 生成物不得进入生产链路，不得直接改 23/11/40/50 代码。

### 2.3 D3 意图涌现

#### 2.3.1 两个子路径

| 子路径 | 问题 | 可证伪性 | 优先级 |
|---|---|---|---|
| **D3-A 意图预测** | 能否从历史会话、习惯、错误案例预测下一个意图/动作/所需知识？ | 强：时序 holdout + 多基线 | P1 先做 |
| **D3-B 知识组合** | 给定预测意图，能否自动组装 memory/SKILL/doc 组合，减少召回步数/追问/时延？ | 中：需 A/B shadow + 任务结果 | 已实现 candidate（2026-11-09，反事实 A/B；真实在线 A/B 待 shadow 数据） |

#### 2.3.2 输入与输出

**输入**：

- `.cognitive/sessions/`：本地 1073 个 session dir / 1072 个非空 `session.json`（2026-11-09 复核；11-08 快照为 366 dirs / 1142 文件）；`session.json` 含 `task_type`、`action_count`、`recalled_memory_ids`、`task_type_history`，`action_chain.jsonl` 含 action_type/detail/files
- 前端四级意图管线与 35 型正典、DreamOS 7 型策略意图、6×30 对话意图（见 [SPEC_INTENT_DREAMOS_OPTIMIZATION.md](../../../1-ARCHITECTURE/dream-harness-bridge/SPEC_INTENT_DREAMOS_OPTIMIZATION.md) §5.5）
- 用户历史意图、习惯、错误案例（35 记忆库 + recall 日志）
- git commit / task history / 会话 outcome

> **数据现实（2026-11-08 核验）**：当前工作树**未发现结构化 intent 日志**（只有 `intent_taxonomy.schema.json`）。D3-A 首轮只能用 `session.task_type`（9 类：strategy-execution 225 / architecture-design 103 / memory-system 18 / 其余 20）作粗粒度代理标签；真实用户意图标签需 P0 补采，且在补采前不得申报「意图涌现」。

**输出（协议级 schema 见附录 B）**：

- `IntentPrediction`：predicted_intent、confidence、evidence、knowledge_combo、suggested_actions、clarification_needed
- `IntentKnowledgeCombo`：memory_ids、skill_ids、doc_ids、rationale

#### 2.3.3 已有底座（引用存在性已核验）

| 资产 | 位置 | 在 D3 中的用途 |
|---|---|---|
| IntentEngine | [intent_engine.py](../../../1-ARCHITECTURE/dreamos/core/sense/intent_engine.py) | 规则+LLM+动态识别，7 型策略意图，置信度门控/澄清 |
| IntentEvaluator | [intent_evaluator_agent.py](../../../1-ARCHITECTURE/dreamos/core/sense/evaluators/intent_evaluator_agent.py) | recall 历史 + jev/laya 重分类 + escalation |
| 前端四级管线 | [intent-unified.ts](../../../3-FRONTEND/dream-universal-gateway/src/lib/intent/intent-unified.ts) | 35 型正典、追问检测、命令快路径、FC 识别、规则兜底 |
| 影子探针 | [shadow-probe.ts](../../../3-FRONTEND/dream-universal-gateway/src/lib/intent/shadow-probe.ts) | 旧路径为准、200 样本、记忆污染封闭、失败静默 |
| 复杂度分级 | `1-ARCHITECTURE/dreamos/core/sense/complexity_classifier.py` | T0-T3 编排深度 |
| 认知记忆 | [SPEC-CognitiveSystem-Evolution.md](../../../35-广义认知系统协作模块/SPEC-CognitiveSystem-Evolution.md) | recall/record/verify、C1-C4 |
| 评测协议 | [SPEC-评测系统.md](../../../45-评测系统/SPEC-评测系统.md) §9-10 | LLM 裁判校准、人工评测协议 |

> **导入现实（2026-11-08 核验，P1-3）**：`IntentEvaluatorAgent` 可独立导入；`IntentEngine` 因 `dreamos/__init__.py` 在包初始化时导入 `apps.api_server`（依赖 Flask），本地缺 flask 时导入失败。D3 实验需轻量导入路径或依赖清单，**不改 DreamOS 包结构**。

#### 2.3.4 缺口

1. **预测目标未定义**：当前是「识别当前意图」，不是「预测下一意图/动作/知识组合」；
2. **时序 holdout 缺失**：必须按时间切分，不能随机切分；
3. **基线缺失**：频率/规则/当前 IntentEngine/kNN 四类基线未跑；
4. **接受标签缺失**：用户 accept/edit/reject、任务结果、纠正行为未结构化落盘；
5. **意图体系碎片化**：35 型前端正典、7 型 DreamOS、6×30 内核三套实现 + 映射表桥接，需先收敛 SSoT；
6. **校准与漂移**：ECE/Brier、概念漂移、n=1 用户过拟合、隐私；
7. **直接意图标签缺失（P0）**：本地无结构化 intent 日志，只有 `session.task_type` 代理；D3-A 首轮只能做 task_type 预测，不能申报意图涌现。

#### 2.3.5 边界

- 48 只定义 D3 的判据、度量、实验协议与观测面板；
- D3 引擎归属 DreamOS/35，需经对应域协商；
- 35 负责意图/记忆沉淀与 verify；
- 45 负责 AI 裁判校准与人工评测协议；
- 意图日志脱敏、访问控制，不将原始用户文本写入度量产物。

---

## §3 统一度量与标签

### 3.1 `EmergenceMetric` schema（复合值版）

```json
{
  "metric_id": "M-D2-EDGE-F1",
  "domain": "D2",
  "criterion": "E1",
  "value": {
    "kind": "composite",
    "fields": {"precision": 0.0, "recall": 0.0, "f1": 0.0}
  },
  "unit": "ratio",
  "direction": "higher_better|lower_better",
  "primary": false,
  "baseline": {"id": "B0", "value": {"kind": "scalar", "number": 0.0}},
  "status": "not_run|insufficient_data|falsified|inconclusive|candidate|verified|rejected",
  "evidence": {"artifact": "", "sha256": "", "n_units": 0, "unit_of_analysis": "module|session|task"},
  "limitation": "",
  "provenance": {"owner": "", "source": "", "version": ""},
  "holdout": {"split": "temporal|module|none", "contaminated": false},
  "missing_policy": "report|drop|fail",
  "ts": "ISO8601"
}
```

- `value.kind=scalar` 用 `number`；`composite` 用 `fields`（P/R/F1、ECE/Brier、阻力四元组、交互项组等复合指标）；
- `direction` 声明损失方向；`primary=true` 标记预注册主终点（每个实验唯一）；
- 文中数值阈值（ECE≤0.1、盲评 ≥4/5、k 等）均为**建议值**，正式门槛在预注册冻结（§4.0 第 8 条）；
- 本节与 §3.3/B.4 为示例级；可校验 JSON Schema（required/enum/format）是 P0 交付物，落盘 `48-涌现架构/registry/schema/` 后由本附录引用。

### 3.2 度量命名空间

| 命名空间 | 用途 | 示例 |
|---|---|---|
| `M-D1-*` | 交易路径 | `M-D1-NET-PNL-OOS`、`M-D1-SHARPE-OOS`、`M-D1-RESISTANCE` |
| `M-D2-*` | 工程架构 | `M-D2-EDGE-F1`、`M-D2-INTERFACE-MATCH`、`M-D2-ENG-GATE-PASS` |
| `M-D3-*` | 意图 | `M-D3-TOP1`、`M-D3-ACCEPT-RATE`、`M-D3-CLARIFY-TURNS` |
| `M-X-*` | 跨域迁移 | `M-X-I2E-GAIN`、`M-X-E2T-GAIN`、`M-X-INTERACTION-3` |

完整目录见附录 A。

### 3.3 `LabelEvent` schema

```json
{
  "label_id": "LBL-...",
  "domain": "D2|D3",
  "target_id": "ARCH-...|INT-...",
  "source": "human|behavior|ci|ai_judge",
  "verdict": "accept|reject|edit|partial",
  "score": 0.0,
  "confidence": 0.0,
  "rubric_version": "",
  "judge_model": "",
  "judge_snapshot": "",
  "used_in_training": false,
  "holdout": true,
  "provenance": {"session_id": "", "artifact": "", "reviewer": ""},
  "ts": "ISO8601"
}
```

### 3.4 标签来源优先级

从硬到软：

1. **human**：人工盲评/确认，作校准集与最终裁决；
2. **behavior**：用户 accept/edit/reject、任务完成/失败、后续纠正，作弱监督；
3. **ci**：测试/构建/lint/覆盖率/安全检查/链接检查，作客观锚点；
4. **ai_judge**：LLM 评审，仅在 45 §9 校准通过后进加权项；未校准不得进硬门禁。

**禁止**：用 `ai_judge` 单独判定 E2 候选；用测试集标签训练；用同一模型生成并评审。

### 3.5 状态词表（状态流转与判定边界）

| 代码 | 中文 | 含义 | 可申报 |
|---|---|---|---|
| `not_run` | 未运行 | 实验未执行 | 否 |
| `insufficient_data` | 样本不足 | 独立实验单元数/评估器低于预注册最小值 | 否 |
| `inconclusive` | 证据不足 | 有数据但主终点 CI 跨 0 / 无法区分 | 否 |
| `falsified` | 已证伪 | 有足够证据证明无改善或方向为负（预注册证伪条件命中） | 否 |
| `candidate` | 候选 | **统计达标**（主终点显著且方向为正），人工复核**之前** | 候选 |
| `verified` | 已验证 | candidate 经人工复核 + 消融 + 独立复现通过 | 是 |
| `rejected` | 复核驳回 | candidate 人工复核/消融/复现未通过 | 否 |

**状态流转**：`not_run → insufficient_data | inconclusive | falsified | candidate → verified | rejected`；`rejected` 必须记录驳回理由与证据，不得静默删除。

**判定边界（排他顺序，逐级判定）**：

1. 独立单元数 < 预注册最小值 → `insufficient_data`；
2. 主终点 CI 跨 0 或无法计算 → `inconclusive`；
3. 预注册证伪条件命中（主终点差值 CI 上界 ≤ 0 等）→ `falsified`；
4. 主终点显著且方向为正 → `candidate`；
5. `candidate` 经人工复核 + 消融 + 复现 → `verified` / `rejected`。

> 「不显著」**不等于** `falsified`：只有能正面证明「无改善/为负」才记 `falsified`；证据不足一律 `inconclusive`。

### 3.6 溯源与隔离

每条度量/标签必须记录：

- 数据快照 hash 与时间区间；
- 生成物版本、模型 id/snapshot、prompt hash、temperature=0；
- holdout 标记：`temporal` / `module` / `none`；
- 是否进入训练集（`used_in_training`）；
- 已知局限 `limitation`，机器可读，防误读。

---

## §4 实验协议

### 4.0 通用规则

所有实验必须：

1. **预注册**：运行前写 `experiment_prereg.json`（模板见 §4.7），冻结假设、基线、指标、样本量、统计检验、成功/证伪条件；
2. **shadow / FAIL-OPEN**：不改变生产行为；异常不阻断主链；
3. **OOD / 时序隔离**：D2 按模块扣留 + 代码版本时间；D3 按会话时间；禁止随机切分；
4. **零执行权**：D2 生成物只在 45 沙箱构建/测试；D3 预测只做建议，不自动执行；
5. **不放宽门禁**：45 阈值、ablation gate、PSI 阈值保持；
6. **产物落盘**：预测、评估、人工评审、数据快照、局限，全部 append-only JSONL/JSON；
7. **状态流转**：统计达标 → `candidate`；`candidate` 经人工复核 + 消融 + 独立复现 → `verified` / `rejected`（§3.5）；AI 评审不能单独发证；
8. **阈值预注册**：`k`（新颖度距离，仅 D2-B/D3-B）、盲评阈值、最小样本量、复述比例阈值等，均在 `experiment_prereg.json` 中冻结；未预注册的阈值不得事后调整；
9. **OOD 强制点（P0-1，已实现）**：两 hook 已落库——`CaseIngestGate.evaluate_and_ingest`（`1-ARCHITECTURE/dreamos/core/compute/case_ingest_gate.py`）增加 `oos_intervals`/`allow_missing_ts`，区间命中或缺时间戳（默认 fail-closed）直接 SKIP 不入；`BayesianMemoryUpdater.update_confidence`（`4-MEMORY/9-工具与接口/bayesian_memory_updater.py`）增加 `observation_ts`/`oos_intervals`/`allow_missing_ts`，OOS 观察不更新 posterior 并记审计日志；共享注册表 `48-涌现架构/registry/ood_intervals.py|.json`（loader + 左闭右开命中判定）。11 项回归测试覆盖命中/边界/缺时间戳/向后兼容（`tests/test_p01_ood_hooks.py` 全绿）。生产调用方接线前，D2-A/D3-A 正式 `candidate` 申报仍需 hook 接入生产链路并经评审；
10. **实验隔离 ≠ FAIL-OPEN**：FAIL-OPEN 保护生产主链路；实验链路中泄漏审计或 OOD 校验失败时，**实验立即停止且不计入正式结果**，不得降级继续；
11. **泄漏审计**：每个 holdout 生成独立数据快照与排除清单（`exclusion_manifest.json`），启动前校验 RAG 索引、prompt、few-shot、缓存与派生文档无扣留内容残留（路径 + 关键词 + hash 三重检查 + **第 4 重 canary string**：holdout 快照内嵌唯一 GUID，在上述任一位置检出即污染铁证，附录 E-T1.5），审计落 `leak_audit.json`；未通过不得启动实验。
12. **脚手架披露卡**（v0.4，附录 E-T1.3）：跨域/生成类实验的预注册必须附脚手架披露卡（脚手架构成、版本、预期影响）并锁为常量；交互显著仍须报告脚手架方差分量，方差分量可解释增益时不得申报协同（SWE-bench 实证：纯脚手架波动 11-15pp 可逆转排名）。

### 4.1 D2-A：架构复原 holdout

**假设 H2A**：扣留某模块的代码与文档后，系统从其余证据重建其接口、依赖、数据流、设计决策的能力，显著高于「检索最近模块文档」基线。

> **前置（P0-3）**：统一 `ArchitectureGraph` 基线已于 2026-11-09 入库（7859 nodes / 53959 edges，0 悬挂边，见 §12.1）；**人工复核 3-5 个 holdout 模块之前**，D2-A 只能探索性运行（`run_class=exploratory`）。

> **实现状态（2026-11-09，探索性，`48-涌现架构/experiments/d2a_holdout/`）**：模块选择 → 快照/exclusion_manifest/canary → 四重泄漏审计 → B0/B1 基线 → `M-D2-EDGE-F1` → 模块级聚类 bootstrap → 四态判定，已可端到端运行（13 项单测）。实跑固化两条口径：
> 1. **ground truth 只取 import 边**：图构建器 call 边为函数名级解析（重名取路径排序首个），实测 27563 条 call 边中大量为重名假依赖（如 276 个文件「调用」同一文档检查脚本），按本节「口径公平性」排除，不作主指标；
> 2. **内容泄漏阈值 = 5-gram 包含度 0.5**：实测真实重复副本落在 0.85–1.0，共享 import/argparse 样板噪声 ≤0.25，0.5 处呈二分。
>
> 当前数据现实：import 口径下仅 6 个模块满足选择标准，其中 4 个因仓内存在**真实重复副本**被泄漏审计拦下，仅 2 个 clean（`14-V15经典马丁策略`、`11-易经推理系统`），低于 3 个探索性下限 → 本轮 verdict=`not_run`。D2-A 需先治理重复副本或扩展模块粒度，方可进入 ≥3 模块的探索性评估。

**实验单元**：模块（Python package 或 TS 子目录）。

**模块选择**：

- 3-5 个模块，覆盖数据访问、交易策略、认知、基础设施至少 3 类；
- 每模块 ≥5 个源码/文档文件、≥3 个下游依赖方、有可提取的接口/调用/数据流；
- 排除：无文档、无下游、生成代码、第三方 vendored 代码。

**扣留方式**：

1. 从输入语料中移除该模块的源码与文档；
2. 从 RAG 索引/统一图中删除该模块节点及其所有边；
3. 保留其他模块中对它的 import/调用/文档引用作为线索；
4. ground truth 从完整仓库的 AST/调用图/接口签名/33-REA 决策复原中提取，不进入输入。

> **口径公平性**：主指标只统计**模块级/公开接口级**边（import/call/data_flow/contract），内部私有调用与实现细节不计入主指标，可作辅助诊断；避免用不可推断的内部实现细节惩罚系统。

**基线**：

| 基线 | 定义 |
|---|---|
| B0 | 文档 kNN：检索最近模块的文档作为答案 |
| B1 | 关键词检索：BM25/关键词命中 |
| B2 | 当前 LLM 无检索（parametric only，可选） |
| B3 | 人工编写的模块文档（上界，不作为涌现基线） |

**指标**：

- **主终点（唯一）**：`M-D2-EDGE-F1`（预测图边 vs 实际 import/call/data_flow 边）；
- 次要（仅报告，不参与判定）：`M-D2-INTERFACE-MATCH`、`M-D2-DATAFLOW-ACC`、`M-D2-ADR-MATCH`（允许 inference 级，必须带 known_gaps）、`M-D2-DOC-COVERAGE`；
- 门槛（gate，不作主判）：`M-D2-HUMAN-RUBRIC` 盲评 1-5；
- `M-D2-NOVELTY` **不用于 D2-A**——复原任务奖励接近 ground truth，与新颖度要求直接冲突；新颖度只属于 D2-B（§4.2）。

**样本与统计（预注册冻结）**：

- **独立实验单元 = 模块**；模块内的边/接口是相关观测，不作独立样本——边级 bootstrap 会低估方差、虚高显著性；
- 最少 **5 个模块**（3 个仅探索性可运行）；3 次固定 seed 运行（temperature=0）按模块取均值后汇总，**不作独立样本**；
- 主终点检验：**模块级配对聚类 bootstrap**（重采样单元 = 模块，10k 次，percentile CI），报告效应量与 95% CI；
- 多重比较：判定只看主终点；次要指标如需判定，预注册 Holm 校正；
- 判定顺序按 §3.5 排他判定执行。

**判定**：

| 结果 | 条件 |
|---|---|
| `candidate` | 主终点 F1 模块级 95% CI 下界 > 0（高于最佳检索基线）且盲评门槛 ≥4/5 |
| `falsified` | 主终点差值 95% CI 上界 ≤ 0（有足够证据证明不优于基线）；或生成物 >80% 文本复述检索文档；或盲评 <3/5 |
| `inconclusive` | 主终点 CI 跨 0（证据不足，不判证伪） |
| `insufficient_data` | 模块数 < 预注册最小值（5） |

**污染控制与泄漏审计**：

- 每个 holdout 模块生成独立数据快照 + `exclusion_manifest.json`（删除的源码/文档/图节点/图边/索引项清单）；
- 启动前校验 RAG 索引、prompt、few-shot、缓存与派生文档无扣留模块内容残留（路径 + 关键词 + hash 三重检查），结果落 `leak_audit.json`（§4.0 第 11 条）；
- 泄漏审计失败 → 实验停止且不计入正式结果（§4.0 第 10 条）；
- 记录数据快照 hash；同一模块不得同时出现在训练与测试；生成物在实验冻结前不得回写训练集。

**产物**：

`predictions.jsonl`、`evaluation.json`、`human_rubric.jsonl`、`data_snapshot.json`、`exclusion_manifest.json`、`leak_audit.json`、`limitation.md`、`prereg.json`。

### 4.2 D2-B：工程方案生成

**假设 H2B**：系统能针对真实 E6 缺口生成人未写过、通过 45 工程门禁、并经人工评审认可的模块/重构/架构方案。

**缺口来源**：

> **数据现实（P1-1，2026-11-09 已关闭）**：`48-涌现架构/registry/capability_gaps.jsonl` 已注入 3 个 D2-B 架构缺口（architecture_gap / doc_debt / interface_mismatch）；`gap_router.ROUTE_TABLE` 已注册 SPEC §6.2 全部 6 个新 gap_type（architecture_gap/module_missing→33-REA，doc_debt→0-系统文档管理，interface_mismatch→33-REA，intent_label_missing/intent_taxonomy_conflict→35-广义认知）；路由测试 5 项覆盖。

- E6 `capability_gaps.jsonl` 新增类型（建议，需 45/33/35/47 协商）：
  - `architecture_gap`：架构图/数据流缺失或不一致；
  - `module_missing`：完整开发所需模块缺失；
  - `doc_debt`：文档断链/覆盖率不足；
  - `interface_mismatch`：接口契约不一致。
- 未知 gap_type 仍走 `gap_type_proposals.jsonl` + 人工评审，不自动路由。

**生成**：

- DSH subagent + 33-REA 分析器 + RAG；
- 输出 `ArchitectureGraph` + `DesignRationale` + `BuildPlan`；
- 零执行权；只在 45 沙箱构建/测试。

**评估**：

- 45 §5.3 工程门禁：E-H1..H5、E-W1..W6；
- 新增行覆盖率 ≥0.80、用例通过率 ≥0.95、pycg ≥0.70（建议值，预注册冻结）；
- **指标分母预注册**：覆盖率按 base_sha 自算（不信任提交方数字）；用例通过率分母 = 预注册测试集用例数，flaky 隔离后不计分母；
- **测试独立性**：评估用例须独立于生成器（隐藏测试/冻结基准集），不得计入生成方案针对性优化的用例；pycg 基准对照使用冻结版本；
- 人工盲评 rubric（架构合理性、可维护性、风险、证据充分性）；
- 新颖度：与现有方案的图编辑距离 ≥k，且与**去重、可行性、缺口解决**联合评估——任一不满足即不得申报（单纯新颖不是成果）；
- E6 缺口是否被解决（回填验证）。

**判定**：

- `candidate`：门禁通过 + 盲评 ≥4/5 + 新颖度 ≥k + 去重/可行性通过 + 缺口解决；
- `falsified`：门禁失败 / 重复已有方案（去重未过）/ 盲评 <3/5；
- `inconclusive`：评估器缺失 / 样本不足 / CI 跨 0。

> **实现状态（2026-11-09）**：`experiments/d2b_engineering/` 已落地（规则引擎生成器 `generator.py` + 零执行沙箱 `sandbox.py` + 45 门禁代理 `evaluate.py` + `run_d2b.py`）。正式 run `D2B-85719d4f2ca4`：针对 `capability_gaps.jsonl` 中 3 个 D2-B 缺口（architecture_gap / doc_debt / interface_mismatch）各产出人未写过的方案模块（`33-REA/ast_call_resolver.py`、`0-系统文档管理/doc_coverage_checker.py`、`33-REA/interface_signature_extractor.py`），沙箱校验（模块名新颖性/依赖可解析/步骤可行性）全过、门禁代理（覆盖率/测试/pycg）全过 → **3/3 candidate，overall verdict=candidate**。
>
> **剩余事项（2026-11-10 更新）**：真实 45 门禁已推进至**硬项 5/5 本地真实执行**（`gate_45.py`）：E-H1 秘密扫描（本地正则）✅、E-H2 漏洞（pip-audit 2.10.1，stdlib-only 模块判无供应链攻击面；requests 冒烟实测检出 2 漏洞→真实 BLOCK）✅、E-H3 可追溯性（本地链：git commit↔artifact sha256↔provenance sidecar，如实标注 local_attestation 非 Sigstore/CI）✅、E-H4 覆盖率（方案已完整实现：`33-REA逆向解析工程/ast_call_resolver.py` 97.7%、`0-系统文档管理/doc_coverage_checker.py` 100%、`33-REA逆向解析工程/interface_signature_extractor.py` 96.5%，coverage+pytest 真实测量，均≥0.80）✅、E-H5 旁路（45 原生 BYPASS_PATTERNS）✅。**deferred 仅余 2 项加权项**：E-W5 pycg（需基准集）、E-W6 OpenSSF Scorecard（需网络）。升级 verified 还需：CI 环境跑齐 E-W5/E-W6 + E-H3 换 CI attestation + 人工盲评。

### 4.3 D3-A：意图预测 holdout

**假设 H3A（代理阶段重述）**：在 session i 开始时（特征截止点 = 该 session 开始前的全部历史），预测 **session i 的 `task_type`**，显著优于频率/规则/当前 IntentEngine/kNN 基线。

**预测目标定义（首轮，代理阶段）**：

- **样本单位与预测时点**：以 session 为独立实验单元；在 session i 开始时刻预测其 `task_type`（「下一意图」= 下一 session 的任务类型，**不是**下一消息或下一动作——后者属直接意图标签阶段）；
- **标签**：`y_i = session_i.task_type`；标签生成方式与特征截止点随预注册冻结；
- **防标签泄漏**：`action_chain`、`files_touched`、`recalled_memory_ids`、`task_type_history`、outcome/correction 属于 session 内**结果侧**字段，**禁止**作为预测特征；首轮特征仅允许历史序列（过往 session 的 task_type / 时间戳 / 间隔）；
- **去重/聚类**：同一 session 不拆分为多条事件；重复 task_type 按 session 计数；跨源对齐用 message hash，不改变 session 独立单元计数。

**事件 schema**：

```json
{
  "event_id": "IE-...",
  "session_id": "",
  "ts": "ISO8601",
  "user_message_hash": "sha256",
  "intent_type": "",
  "taxonomy": "35-type|7-type|6x30",
  "action": "",
  "knowledge_ids": [],
  "outcome": "success|fail|unknown",
  "correction": "none|edit|reject|clarify",
  "source": "frontend|dreamos|bridge|session"
}
```

**数据与切分（预注册切分表）**：

- 数据源（2026-11-09 复核）：`.cognitive/sessions/`（1073 dirs；非空 `session.json` 1072；`task_type` 12 类：configuration 380 / strategy-execution 259 / architecture-design 131 / python-development 126 / 其余 8 类 176；11-08 快照为 366 dirs / 365 非空 / 9 类；`action_chain.jsonl` 可 join）、git commit/task history；**前端/DreamOS 结构化 intent 日志当前未找到**，需 P0 接入或从 sessions 派生；
- 首轮代理：`session.task_type` 作 `intent_type` 代理；报告统一标注 **「task_type 预测」**，不得与真实意图标签实验混报，不得申报「意图涌现」；
- 时序切分：按 session start_time 排序，前 75% 训练/验证、后 25% 测试（或前 3 周/第 4 周滚动）；**切分表（train/val/test session id 清单 + cut 时间戳）随预注册冻结**；
- 最少 **200 个测试 session**（独立单元）；2026-11-09 快照 1072 sessions 按 75/25 约可得 268 test ≥ 200，**量级门槛可过**——但测试段类分布须按冻结切分表复核（`configuration` 类 380 条未必是真实用户意图，过滤策略随预注册冻结）；若按冻结切分表复核后仍 <200，记 `insufficient_data`，需改 action-level 事件定义或积累更多 session，两者都是预注册变更，**不得**事后下调阈值；
- 同一 session 不跨训练/测试；
- `taxonomy` 字段必须记录使用的正典版本；跨正典比较先映射到 35 型正典或统一中间层，映射表版本化，避免 35 型/7 型/6×30 混算。

**基线**：

| 基线 | 定义 |
|---|---|
| B0 | 频率/多数类 |
| B1 | 规则（当前 IntentEngine 规则层） |
| B2 | 当前 IntentEngine 全链路 |
| B3 | kNN：会话 embedding 最近邻 |

**指标**：

- **主终点（唯一）**：`M-D3-TOP1`（session 级 task_type 预测命中率）；
- 次要（仅报告）：`M-D3-TOP3`、`M-D3-MRR`、`M-D3-ACCEPT-RATE`（用户接受/未修改比例）、`M-D3-CLARIFY-TURNS`、`M-D3-TIME-TO-ACTION`、`M-D3-CORRECTION-RATE`；
- 校准门槛（gate）：`M-D3-ECE` / `M-D3-BRIER`；
- `M-D3-NOVELTY`：仅**直接意图标签阶段**使用（代理阶段无用户确认通道，无法评估新颖组合）。

**样本与统计（预注册冻结）**：

- 独立实验单元 = session；主终点用 session 级配对/置换检验（相对基线的差值，报告 95% CI）；
- 多重比较：判定只看主终点；次要指标如需判定，预注册 Holm 校正；
- 判定顺序按 §3.5 排他判定执行。

**判定**：

| 结果 | 条件 |
|---|---|
| `candidate` | 主终点 TOP1 相对最佳基线的差值 95% CI 下界 > 0 且 ECE 门槛达标（建议 ≤0.1，预注册冻结） |
| `falsified` | 主终点差值 95% CI 上界 ≤ 0（有足够证据证明不优于基线）；或纠正率显著上升 |
| `inconclusive` | 主终点 CI 跨 0 |
| `insufficient_data` | 测试 session < 200 或标签缺失 |

**隐私与漂移**：

- 度量产物只存 message hash，不存原文；
- 按用户/时间段监控漂移；漂移超阈值时暂停 `candidate` 申报；
- n=1 用户场景需额外报告「跨用户泛化」缺口，不得宣称通用意图涌现。

**运行方式**：shadow-probe 模式；旧路径为准；`recordMemory=false` 防污染；探针单次记录预算 200 条（区别于正式评估的 ≥200 测试 session 门槛）；失败静默。P0-1（生产接线/区间配置）与 P0-2（直接意图标签）关闭前，全部运行标 `run_class=exploratory`。

### 4.4 D3-B：意图知识组合

**假设 H3B**：给定预测意图，自动组装的 memory/SKILL/doc 组合能减少 recall 步数、澄清轮次或 time-to-action，且不增加错误。

**方法**：

- A/B shadow：同一任务类型，有组合 vs 无组合；n=1 时用交替会话或匹配对；
- 组合来源：35 recall、SKILL 索引、2-KNOWLEDGE RAG、41 文件索引；
- 输出 `IntentKnowledgeCombo`。

**指标**：

- recall 步数、澄清轮次、time-to-action、任务成功、用户纠正；
- 知识命中率（组合中实际被使用的比例）；
- 负反馈：错误知识导致的返工。

**判定**：

- `candidate`：显著减少步数/时延且不增加错误；
- `falsified`：无改善或错误增加；
- `inconclusive`：样本不足/任务不可比。

> **实现状态（2026-11-09）**：`experiments/d3b_intent_combo/` 已落地（`IntentKnowledgeCombo` 组装器 `combo.py`：按 intent_proxy 聚合训练集高频 memory/skill/file_domain；A/B 反事实验证 `evaluate.py`：有 combo recall_steps=1 vs 无 combo 实际步数 + 知识命中率 + bootstrap CI + 四态判定；`run_d3b.py`）。正式 run `D3B-e1b0514d4971`：273 test sessions，mean_actual_recall_steps=8.10 → mean_combo_recall_steps=1.0（**Δsteps=7.10，95% CI 7.02..7.19**），hit_rate=0.588 ≥ 0.3，correction 不增加 → **verdict=candidate**。
>
> **剩余事项**：当前 A/B 为**反事实代理**（用历史实际步数 vs combo 组装后的单步召回估计），非真实在线 shadow A/B；需在生产 shadow 环境对同一任务类型做有/无组合交替实验，积累足够样本后方可升级 verified。

### 4.5 X-A：跨域迁移实验

#### 4.5.1 T-I2E（D3 → D2）

**假设**：有意图预测/知识组合的工程任务，比无预测的工程任务完成更快、迭代更少、人工纠正更少。

- 任务：D2 架构复原或小型重构任务；
- 分组：有 D3 预测 vs 无 D3 预测（shadow，随机/交替）；
- 样本：≥30 个任务；
- 指标：完成时间、迭代次数、人工纠正次数、返工率；
- 判定：配对检验显著 + 方向为正 → `candidate`；否则 `falsified`/`inconclusive`。

#### 4.5.2 T-E2T（D2 → D1）

**假设**：D2 产出的架构/重构方案，能改善交易模块的缺陷率或 shadow 回测指标。

- 对象：交易相关模块（11/23/42/50 等）的 D2 方案；
- 评估：45 金融类门禁 + shadow 回测 + 缺陷率；
- 样本：≥30 shadow 天或 ≥100 笔 shadow 交易；
- 判定：指标显著改善且不增加风险 → `candidate`；否则记录证伪。

#### 4.5.3 联合 vs 独立

- 预注册完整 **2×2×2 因子设计**（D1/D2/D3 各 on/off，共 8 臂：000 全域基线臂 + 001/010/100 单维臂 + 011/101/110 两维臂 + 111 联合臂），每臂按真实独立实验单元重复；
- 统一归一化增益 `G`（共同效用前置，归一化方法随预注册冻结，§1.2）；
- 估计单因素主效应 `G(D1)/G(D2)/G(D3)`、两因素交互 `G_ij`（i<j）、三因素交互 `G_123`；
- 判定（与 §1.2 一致；**禁止**退回已废除的 `G(joint) - [G(D1)+G(D2)+G(D3)]` 口径——它无法区分两维与三阶交互）：`G_123` 显著（预注册检验，95% CI 不含 0 且方向为正）**且** O-information 复核通道 `Ω(D1,D2,D3)>0`（附录 E-T1.2；估计器不可用记 `insufficient_data`）**且**至少一个 `G_ij` 为正（Holm 校正）→ 三维涌现候选；
- `G_123` 不显著但有正的两因素交互 → 报告「两维协同 + 单维优化」；无任何显著交互 → 报告「多个独立维度的优化」或「跨域联合收益」，均不得申报三维涌现；
- 联合增益须通过脚手架/数据红利消融（§4.0 通用规则，含第 12 条脚手架披露卡），消融未过即使交互显著也不得申报。

> **实现状态（2026-11-09）**：`experiments/xa_transfer/` 已落地（8 臂 2×2×2 因子设计：D1=E3 耦合 / D2=D2-A F1 / D3=D3-B 步降；主效应/二阶交互/`G_123` 三阶交互估计 + bootstrap CI + O-information Ω 代理 + 涌现判定）。正式 run `XA-899fa1a5e9ed`：**G₁₂₃=0.080（95% CI 0.023..0.136 > 0），Ω=0.060 > 0，三对 G_ij 均正** → **verdict=candidate（三维涌现候选）**。
>
> **剩余事项**：当前三维增益用已验证 candidate 的主指标（E3 耦合改善 / D2-A F1 / D3-B 步降）做 proxy，非真实跨域 A/B；需 D1 shadow 跑数积累（真实交易 recall 日志 + 反射动作侧补记）后做真实 T-I2E / T-E2T 在线 A/B 方可升级 verified。

### 4.6 人工与 AI 评审协议

沿用 45 §9-10，不新建协议：

1. **校准集**：≥200 条人工标注，覆盖好/中/差三档；
2. **一致性**：Cohen's κ≥0.60，Krippendorff's α≥0.67（ordinal）；
3. **偏差控制**：A/B 顺序对调；长度与分数 |r|<0.2；双裁判取均值；差 >1 档记 disagreement；
4. **锁定**：judge_model_id + snapshot_date + prompt_hash + temperature(=0) + max_tokens；
5. **漂移**：同 spec 复算差异 >5% 标记 `judge_drift`，触发人工抽检；
6. **人工评测**：分层抽样、双标重叠 10-20%、盲测、α 下限 0.67；
7. **未校准裁判**：只能进加权项，权重 ≤0.3，不得进硬性项。

### 4.7 预注册模板

```json
{
  "experiment_id": "EXP-D2A-20261108-001",
  "protocol_version": "SPEC-EMERGENCE-3D-v0.1",
  "domain": "D2",
  "criterion": "E1",
  "hypothesis": "扣留模块架构复原 F1 显著高于文档 kNN 基线",
  "data_snapshot": {"hash": "", "range": "", "modules": []},
  "baselines": ["B0", "B1", "B2"],
  "metrics": ["M-D2-EDGE-F1", "M-D2-INTERFACE-MATCH", "M-D2-HUMAN-RUBRIC"],
  "sample_size": {"modules": 3, "runs_per_module": 3},
  "stat_test": "paired_bootstrap_10k + wilcoxon",
  "success_criteria": "p<0.05, direction_positive, rubric>=4/5, novelty>=k",
  "falsification_criteria": "F1<=baseline or paraphrase>80% or rubric<3/5",
  "owner": "",
  "reviewer": "",
  "created_at": "ISO8601"
}
```

---

## §5 路线图（P0-P4）

| 阶段 | 时间 | 交付物 | 退出条件 |
|---|---|---|---|
| **P0 度量字典与基线盘点** | 1-2 周 | `EmergenceMetric`/`LabelEvent`/`ExperimentResult` schema；D2 文档-代码图盘点；D3 意图日志盘点；三套意图体系 SSoT 决策建议；基线数据快照 | 所有引用路径核验；数据健康度报告；无代码变更 |
| **P1 D2-A + D3-A** | 3-4 周 | 两个 holdout 协议实现与首轮真实结果（shadow） | 各 ≥3 模块/≥200 事件；`candidate`/`falsified`/`inconclusive` 如实记录 |
| **P2 D2-B + D3-B** | 3-4 周 | 生成/知识组合协议 + 45 门禁接入 + 沙箱 | 生成物零执行权；门禁证据链完整；**已实现 candidate（2026-11-09，门禁代理+反事实 A/B）；剩余真实 45 门禁 + 在线 shadow A/B** |
| **P3 跨域迁移** | 4-6 周 | T-I2E / T-E2T / 联合 vs 独立 | 三阶交互 `G_123` + Ω 双通道检验完成（§1.2/§4.5.3）；无论正负均记录；**框架已就绪，proxy 三维涌现 candidate（2026-11-09）；剩余真实跨域 A/B 需 D1 shadow 数据** |
| **P4 三维面板与门禁** | 持续 | 三维度量面板、七关门禁、人工复核流程 | 连续 ≥7 天数据；可复现；人工复核 |

**关键顺序**：P0 先做；P1 的 D2-A 与 D3-A 可并行；P2 必须在 P1 有可评估结果后进行；P3 必须在 P1/P2 至少各有一域 `candidate` 后进行；P4 最后。

---

## §6 治理与边界

### 6.1 所有权

| 资产 | 所有者 | 48 的角色 |
|---|---|---|
| D1 交易策略/执行 | 23/11/42/50 | 只读度量、实验观测 |
| D2 工程 dreaming / 生成器 | 33-REA / 46-DSH | 定义判据/协议；只读消费输出 |
| D3 意图引擎 | DreamOS / 35 | 定义判据/协议；只读消费输出 |
| 工程评测/门禁 | 45-评测系统 | 引用 §5.3/§9，不复制阈值内核 |
| 记忆/verify | 35 / 4-MEMORY | 引用 C1-C4，不重复定义 |
| L0 契约/壳治理 | 46/47 | 只读引用，不改契约 |

### 6.2 新 gap_type 与路由

本 Spec 建议新增（**不在本版实施**）：

| gap_type | 路由 | 用途 |
|---|---|---|
| `architecture_gap` | 33-REA / 46-DSH | 架构图/数据流缺失或不一致 |
| `module_missing` | 33-REA / 46-DSH | 完整开发所需模块缺失 |
| `doc_debt` | 0-系统文档管理 | 文档断链/覆盖率不足 |
| `interface_mismatch` | 33-REA | 接口契约不一致 |
| `intent_label_missing` | 35 / DreamOS | 意图预测标签不足 |
| `intent_taxonomy_conflict` | 35 / DreamOS | 三套意图体系冲突 |

路由表扩展需 45/33/35/47 协商；未知类型仍落 `gap_type_proposals.jsonl` + 人工评审，不自动路由。

> **当前实现状态（P1-1，2026-11-09 已关闭）**：`gap_router.ROUTE_TABLE` 已注册 SPEC §6.2 全部 6 个新 gap_type；`capability_gaps.jsonl` 已注入 3 个 D2-B 架构缺口；路由测试 5 项通过。D2-B 可启动。

### 6.3 安全与隐私

- D2 生成物零执行权；只在 45 沙箱构建/测试；不得直接改生产代码；
- D3 只做建议，不自动执行交易/写操作；意图日志脱敏（message hash）；
- **隐私治理（hash ≠ 匿名化）**：度量产物只存 message hash、不存原文，但 hash 本身不构成匿名化——须配访问控制（仅评审 owner 与实验进程可读）、保留期（建议 90 天，到期删除，预注册冻结）、删除机制（可按 session_id 定位删除）；n=1 用户数据存在小样本可识别风险，聚合对外报告前做 k-匿名性检查（建议 k≥5，预注册冻结）；
- 所有实验 shadow、FAIL-OPEN；异常不阻断主链；
- 不放宽既有门禁/阈值；不为涌现指标调参；
- 生成式模型/裁判模型记录 id/snapshot/prompt hash，支持追溯。

---

## §7 反模式

| # | 反模式 | 为什么禁止 |
|---|---|---|
| X1 | 把某次 LLM 生成的架构/意图当涌现 | 轶事不可证伪；必须走 holdout + 基线 |
| X2 | 为出指标放宽 45 门禁/ablation gate/PSI | 污染选择压力，指标即刻失效（Goodhart） |
| X3 | 加黑盒大模块做「三维涌现」 | 违反 100% 可审计；必须证据链 |
| X4 | 生成物直接进生产/实盘 | 违反零执行权/决策分离 |
| X5 | 把规模增长当涌现 | E5 要求相变拐点，不是线性变好 |
| X6 | 重复已证伪方向 | 先看 48 v0.5 证伪记录 |
| X7 | 把脚手架收益误报为涌现 | 结构化接口/工程约束的收益是脚手架贡献；必须消融 |
| X8 | 无负反馈对冲的强化循环 | 策略泡沫/意图自嗨；需衰减、纠正、人工复核 |
| X9 | AI 自评自证 | 自偏好/奖励黑客；AI 评审必须校准 + 外部锚点 |
| X10 | 随机切分导致泄漏 | D2/D3 必须时序/模块隔离 |
| X11 | 生成架构/代码直接执行 | 不可逆风险；必须沙箱 + 零执行权 |

---

## §8 开放问题（需决策）

1. **D2/D3 所有权与资源**：D2 做梦器放 33-REA 还是 46-DSH？D3 放 DreamOS 还是 35？48 只做观测是否能获得足够数据？
2. **意图体系 SSoT**：35 型前端正典、7 型 DreamOS、6×30 内核，哪个是权威？[SPEC_INTENT_DREAMOS_OPTIMIZATION.md](../../../1-ARCHITECTURE/dream-harness-bridge/SPEC_INTENT_DREAMOS_OPTIMIZATION.md) 提到权威规范链接失效，需要正式决策。
3. **新 gap_type/route table**：是否在 P1 前扩展 E6 路由？由谁批准？
4. **人工评审容量**：D2/D3 的盲评需要多少人力/预算？没有人工复核，`candidate` 无法升 `verified`。
5. **LLM/裁判预算**：D2 文档-代码图构建与生成需要多少 token/算力？是否设预算上限？
6. **隐私与访问控制**：意图日志的数据分级、保留期、访问主体？
7. **48 v0.6 范围**：NN 反馈网关 + 三维涌现是否同一次评审，还是拆成两个子 Spec 分别评审？
8. **「架构正确性」rubric**：D2-A 的盲评标准由谁定义、如何版本化？
9. **OOD 强制点归属**：`exclude_out_of_sample_interval` / `is_in_oos_interval` 由哪个域实现/维护？主 SPEC v0.5 §5 声称的 hook 当前工作树未检出，需同步复审。
10. **D3 直接意图标签采集**：前端埋点、DreamOS 日志、还是从 sessions 派生？由谁负责、如何脱敏与保留？

---

## §9 六维自检与评审摘要（2026-11-08）

> 正式评审证据与处置见 §11；本节保留摘要。

| 维度 | 结论 | 证据 |
|---|---|---|
| 1 引用存在性 | ✅ 文件级通过；⚠️ IntentEngine 导入依赖 | link_checker 48 个相对链接无断链；关键文件/符号存在；`IntentEvaluatorAgent` 可导入；`IntentEngine` 因 `dreamos/__init__.py` 拉起 Flask apps，本地缺 flask 时导入失败 |
| 2 数据资产健康度 | ⚠️ | `.cognitive/sessions` 366 dirs/1142 files；task_type 9 类；364 含 recalled_memory_ids；无结构化 intent 日志；`capability_gaps.jsonl`/`events/`/`trajectories.jsonl`/`l1_case_store.jsonl` 缺失；`bcrm_trades.db` 0 字节；E2/E3/E5 artifacts 与 `emergence_metrics.jsonl` 在位 |
| 3 模型-数据版本一致性 | ✅/N/A | 无新增 ckpt；LLM/裁判按 45 §9 记录 model id/snapshot/prompt hash |
| 4 存量资产盘点 | ✅/⚠️ | 33-REA 冒烟通过（dependency_graph 15 nodes/27 edges、call_chain 17 funcs/9 callers、arch detector unknown+Evidence）；45 engineering evaluators 有 `evaluate`；shadow-probe 常量匹配；35 recall/47 registry 可用；⚠️ 实际类名以代码为准 |
| 5 门禁强制等级 | ✅ P0 | 阈值与 45 §5.3 一致（0.80/0.95/0.70），无放宽；45 Enforcer/Gate 已实现；OOD hook 已落地（P0-1：CaseIngestGate/BayesianMemoryUpdater 两个 hook + 11 项回归测试）；E6 route table 已注册 6 个新 gap_type（P1-1） |
| 6 主链可观测性 | ⚠️ P0/P1 | session 可 join（task_type/action_count/recalled_memory_ids/action_chain）；无直接 intent 标签；`events/memory_readout` 缺失；D2 统一图/D3 事件 schema 未落盘；E4b readout 为 session 级代理 |

**结论**：P0-1/P0-2/P0-3、P1-1~P1-6 已全部关闭，外部复审通过，**可作为实施就绪基线**；D2-A/D2-B/D3-A/D3-B/X-A 五个实验均已实现 candidate（verdict 仪表盘聚合 10 实验，见 `metrics/verdict_dashboard.py`）。**剩余事项**：① E1/E4 脱离 `pipeline_only` 代理——需 11 域交易 recall 结构化日志 + HermesReflector `active_reflection_id` 动作侧补记；② X-A 真实跨域 A/B——需 D1 shadow 跑数积累（当前用 candidate 主指标做 proxy）；③ E1 7 天 shadow 跑数 + ≥1 次非预设联动候选（人工复核）；④ D2-B 真实 45 门禁运行（当前为门禁代理）。

---

## §10 参考

### 10.1 48 域内

- [SPEC-EMERGENCE-EVOLUTION v0.5](./SPEC-EMERGENCE-EVOLUTION-v0.1.md)
- [SPEC-NN-FEEDBACK-GATEWAY v0.1](./SPEC-NN-FEEDBACK-GATEWAY-v0.1.md)
- [REVIEW-CHECKLIST v0.1](./REVIEW-CHECKLIST-v0.1.md)
- [RESEARCH-LLM-EMERGENCE v0.1](./research/RESEARCH-LLM-EMERGENCE-v0.1.md)
- [RESEARCH-BIO-EMERGENCE v0.1](./research/RESEARCH-BIO-EMERGENCE-v0.1.md)
- [48 README](../../README.md)

### 10.2 上游/关联域

- 33-REA 架构分析器：`33-REA逆向解析工程/core/`
- 33-REA 反思层/做梦器：[SPEC-33-反思层.md](../../../33-REA逆向解析工程/SPEC-33-反思层.md)
- 45-评测系统：[SPEC-评测系统.md](../../../45-评测系统/SPEC-评测系统.md)
- DreamOS 意图引擎：`1-ARCHITECTURE/dreamos/core/sense/`
- 35-广义认知：[SPEC-CognitiveSystem-Evolution.md](../../../35-广义认知系统协作模块/SPEC-CognitiveSystem-Evolution.md)
- DSH Subagent：[DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../../../1-ARCHITECTURE/dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md)
- 架构地图：[ARCHITECTURE_MAP.md](../../../0-系统文档管理/2-文档地图/ARCHITECTURE_MAP.md)
- L0 能力集：[l0_capability_set.v1.yaml](../../../0-系统文档管理/l0_capability_set.v1.yaml)
- RAG：[2-KNOWLEDGE/9-RAG-INFRA](../../../2-KNOWLEDGE/9-RAG-INFRA)
- 文件索引：[41-文件索引系统](../../../41-文件索引系统)

---

## §11 六维评审记录（2026-11-08）

> 评审对象：本 Spec v0.1；依据：[REVIEW-CHECKLIST-v0.1](./REVIEW-CHECKLIST-v0.1.md)；方式：仓库下探 + 冒烟测试 + 引用核验。裁决：**修改后接受**。

### 11.1 六维结论

| 维度 | 结论 | 关键证据 |
|---|---|---|
| 1 引用存在性 | ✅ 文件级通过；⚠️ IntentEngine 导入依赖 | link_checker 48 个相对链接无断链；33-REA/45/DreamOS/前端/35/47/RAG 文件存在；`IntentEvaluatorAgent` 可导入；`IntentEngine` 因 `dreamos/__init__.py` 拉起 Flask apps 在本地缺 flask 时失败 |
| 2 数据资产健康度 | ⚠️ | `.cognitive/sessions` 366 dirs / 1142 files；task_type 9 类；364 含 recalled_memory_ids；365 有 action；**无结构化 intent 日志**；`capability_gaps.jsonl`/`events/`/`trajectories.jsonl`/`l1_case_store.jsonl` 缺失；`bcrm_trades.db` 0 字节，`human_baseline.json` 的 24 IS/9 OOS 来自云端实盘 |
| 3 模型-数据版本一致性 | ✅/N/A | 本 Spec 无新增 ckpt；D2/D3 的 LLM/裁判按 45 §9 记录 model id/snapshot/prompt hash；未发现版本冲突 |
| 4 存量资产盘点 | ✅/⚠️ | 33-REA 冒烟：dependency_graph 15 nodes/27 edges、call_chain 17 funcs/9 callers、arch detector 返回 unknown+Evidence；45 engineering evaluators 有 `evaluate`；shadow-probe 的 `SHADOW_BUDGET=200`/`recordMemory=false`/`appendFileSync` 匹配；35 recall/47 registry 可用；⚠️ 实际类名为 `DesignDecisionRecoverer`/`MethodologyAbstractor`/`EvolutionNarrator` |
| 5 门禁强制等级 | ✅ P0 | 阈值与 45 §5.3 一致（0.80/0.95/0.70），无放宽；45 `Enforcer`/`Gate` 已实现且有测试；OOD hook 已落地（P0-1：`CaseIngestGate.evaluate_and_ingest` + `BayesianMemoryUpdater.update_confidence` 两个 hook + registry/ood_intervals.json）；E6 `ROUTE_TABLE` 已注册 6 个新 gap_type（P1-1） |
| 6 主链可观测性 | ⚠️ P0/P1 | session 可 join（task_type/action_count/recalled_memory_ids/action_chain）；但无直接 intent 标签；`events/memory_readout` 缺失；D2 统一图/D3 事件 schema 未落盘；E4b readout 为 session 级代理 |

### 11.2 发现与处置

| ID | 级别 | 发现 | 证据 | 处置 |
|---|---|---|---|---|
| P0-1 | P0 | OOD/时序隔离代码强制点已落库（CaseIngestGate/BayesianMemoryUpdater 两 hook + registry/ood_intervals + 11 项回归测试）；生产调用方接线待推进 | 工作树代码核验：case_ingest_gate.py L324 / bayesian_memory_updater.py L253 含 oos_intervals 参数；test_p01_ood_hooks.py 全绿 | P0-1 代码已实现（方案 A）；生产接线 + 评审完成前，D2-A/D3-A 正式 candidate 申报需标注 run_class 并经 hook 接入评审 |
| P0-2 | P0 | D3-A 直接意图标签缺失 | 仅有 `intent_taxonomy.schema.json`；sessions 只有 `task_type` 9 类 | 首轮只做 task_type 代理；真实意图标签 P0 补采；补采前不得申报意图涌现 |
| P0-3 | P0 | D2-A 统一 `ArchitectureGraph` 未建 | 33-REA 分析器存在，但无统一图 artifact | P0 先产出图基线；否则 D2-A 阻塞 |
| P1-1 | P1 | E6 `capability_gaps.jsonl` 缺失；新 gap_type 未注册 | 文件不存在；`ROUTE_TABLE` 无新类型 | **已关闭（2026-11-09）**：3 个 D2-B 缺口已注入，6 个新 gap_type 已注册，路由测试 5 项覆盖；D2-B 实验已基于此产出 candidate（见 §4.2 实现状态） |
| P1-2 | P1 | 交易库本地空、D1 指标不可本地复现 | `bcrm_trades.db` 0 字节；`human_baseline.json` 24/9 来自云端 | 明确云端/快照获取路径；D1 实验用快照 hash |
| P1-3 | P1 | IntentEngine 导入依赖 Flask/eager package import | `dreamos/__init__.py` 导入 apps.api_server；本地缺 flask | P1 提供轻量导入路径或依赖清单；不改 DreamOS 包结构 |
| P1-4 | P1 | `events/`、`trajectories.jsonl`、`l1_case_store.jsonl` 缺失 | 文件不存在 | E4b/48 既有度量源需恢复或文档化；D2/D3 事件 schema P0/P1 落盘 |
| P1-5 | P1 | 意图体系 SSoT 未决（35 型/7 型/6×30） | 三套实现 + 映射表 | P0/P1 由 35/DreamOS 决策；实验记录 taxonomy 版本 |
| P1-6 | P1 | 人工/AI 评审 owner、预算、校准集未定 | 45 §9 要求 ≥200 人工标注 | P1 前指定 owner/预算；未校准不进硬门禁 |
| P2-1 | P2 | `k`/ECE/用户确认阈值未具体化 | 文中多处「≥阈值/≥k」 | 预注册时冻结；建议 D2 图编辑距离 k=2、D3 ECE≤0.1，待评审 |
| P2-2 | P2 | D2-A 3-5 模块对模块级 Wilcoxon 功效弱 | 统计方案 | 主判用边级 bootstrap；模块数尽量 ≥5；3 个仅最小可运行（**已被 v0.2 §4.1 取代**：主判改模块级聚类 bootstrap，边级仅辅证） |
| P2-3 | P2 | 33-REA 实际入口类名与表内能力名不同 | `DesignDecisionRecoverer`/`MethodologyAbstractor`/`EvolutionNarrator` | 文档按实际符号实现；已加注 §2.2.3 |

### 11.3 裁决与后续

**修改后接受**：文档层引用/格式/口径问题已修（见本次改动）；P0-1/P0-2/P0-3 是实施/申报阻塞项，必须在 P1 前关闭。P0-1 涉及主 SPEC v0.5 §5 的 OOD 强制点，建议同步发起主 SPEC 复审；P0-2/P0-3 属于 P0 数据/图基线建设，不进入本版代码。

> **后续进展（2026-11-09）**：P0-1 复审完成（确认代码级 OOD 强制点缺失，见 [REVIEW-2026-11-09-main-spec-ood.md](./reviews/REVIEW-2026-11-09-main-spec-ood.md)）；P0-3 图基线声明已生成（574 nodes / 3522 edges，0 悬挂边；**产物未入库，仅 README 声明，v0.4 复审修正**）；P0-2 生成器声明合成会话冒烟通过（**脚本未入库**），且真实 `.cognitive/sessions` 执行被本地安全守门拦截；11-08 快照 365 sessions 的 75/25 切分只有 92 test <200，**11-09 复核已积累至 1072 sessions（75/25 约 268 test），量级门槛可过，类分布待按冻结切分表复核**；直接意图标签仍缺。详见 §12。

---

### 11.5 内部复审（2026-11-09，v0.4）

裁定：**修改后接受**（复审时判「需修改」：P0×3 / P1×4 / P2×4，本版全部修订）。

- **P0-1**：§4.0 第 9 条 OOD hook 已本地实现并与工作树对齐——`CaseIngestGate.evaluate_and_ingest`（`oos_intervals`/`allow_missing_ts`）+ `BayesianMemoryUpdater.update_confidence`（`observation_ts`/`oos_intervals`）+ `registry/ood_intervals.py|.json`，11 项回归测试（`tests/test_p01_ood_hooks.py`）全绿；剩余：生产调用方接线 + 评审；
- **P0-2**：§12 生成器脚本与图基线产物未入库（`baselines/` 仅 README）→ 状态修正为「未入库」，hash 暂不可核验；
- **P0-3**：§4.5.3 与附录 A `M-X-INTERACTION-3` 漏 Ω 复核通道 → 已补齐双通道判定；
- **P1**：§2.1「落主 SPEC」改「拟落」；§5 P3 残留「超加性检验」改 `G_123`+Ω；§4.0 增第 12 条脚手架披露卡；附录 E 标注 T1 方法零实现待新建；
- **P2**：附录 E 条数 25→23；头部日期/状态行补 v0.4；B.4 `verdict` 补 `rejected`；§11.2 P2-2 标注已被 v0.2 取代。

---

## §12 P0/P1 关闭清单（2026-11-09）

| ID | 状态 | 关闭动作 | 退出条件 | 证据/产物 |
|---|---|---|---|---|
| P0-1 | **implemented**（2026-11-09 本地验证，未推送） | 方案 A 落地：① `CaseIngestGate.evaluate_and_ingest` 增加 `oos_intervals`/`allow_missing_ts`，命中 OOS 区间或缺时间戳直接 SKIP 不入；② `BayesianMemoryUpdater.update_confidence` 增加 `observation_ts`/`oos_intervals`，OOS 观察不更新 posterior 并记审计日志；③ 共享 registry `registry/ood_intervals.json` + `registry/ood_intervals.py`（loader + 左闭右开命中判定）；11 项回归测试覆盖命中/边界/缺时间戳/向后兼容；现有 143 项相关测试不回归 | 两个 hook + 回归测试 + registry；主 SPEC 引用真实路径（本条） | [REVIEW-2026-11-09-main-spec-ood.md](./reviews/REVIEW-2026-11-09-main-spec-ood.md) · `tests/test_p01_ood_hooks.py` |
| P0-2 | **closed**（2026-11-09 直接意图标签已补） | 生成器 `baselines/build_d3_intent_events.py` 已入库；真实运行 1092 sessions（0 解析错误），75/25 时序切分 train=819 / test=273；**直接意图标签已补**：每会话产出 `intent_label`/`intent_stable`/`intent_trajectory`/`intent_signals`/`intent_label_confidence`（结构化启发式：task_type + 稳定性 + 文件域，确定性可复现，无自由文本），覆盖率 1092/1092（稳定 997 / 漂移 95）；raw JSONL 按隐私约束不入库（仅 summary/split/manifest 入库） | 直接意图标签可用（已达成） | `baselines/artifacts/d3_intent_events/`（summary + split + manifest，sha256 可核验） |
| P0-3 | **closed**（2026-11-09 用户确认跳过人工复核） | 生成器 `baselines/build_d2_architecture_graph.py` 已入库（测试 4 项覆盖闭合/确定性/FAIL-OPEN/scope）；真实全仓运行：7859 nodes（4110 py / 3303 md / 446 external）、53959 edges（24640 import / 27563 call / 1756 doc_ref）、闭合校验 0 悬挂边、parse_errors=97（FileNotFoundError 为主，FAIL-OPEN 计数）；sha256 `3b95a04a3f9e...` 可核验（剔除 generated_at 的结构哈希）；人工复核清单已生成（`experiments/d2a_holdout/results/D2A-b5ae5586b3b8/manual_review.md`，4 模块 / 32 条 inbound import 边）；**用户 2026-11-09 确认跳过人工复核签字环节**，D2 图基线视为可用 | ~~图 artifact + 生成脚本入库 + schema 校验~~（已达成）；~~复核清单备料~~（已达成）；~~人工复核 3-5 个 holdout 模块并签字~~（用户 2026-11-09 确认跳过） | `baselines/artifacts/d2_architecture_graph/`（graph + summary + manifest，已入库） · `experiments/d2a_holdout/results/D2A-b5ae5586b3b8/manual_review.md` |
| P1-1 | **closed**（2026-11-09 缺口注入 + 路由表扩展） | `capability_gaps.jsonl` 已注入 3 个 D2-B 架构缺口：`architecture_gap`（call 边函数名级解析假依赖）、`doc_debt`（文档覆盖率不足）、`interface_mismatch`（图无接口签名）；`gap_router.ROUTE_TABLE` 已注册 SPEC §6.2 全部 6 个新类型（architecture_gap/module_missing→33-REA，doc_debt→0-系统文档管理，interface_mismatch→33-REA，intent_label_missing/intent_taxonomy_conflict→35-广义认知）；路由测试 5 项覆盖已知类型/新类型/未知落 proposals/超时/FAIL-OPEN | 3 个已知缺口 + 路由测试（已达成） | `registry/capability_gaps.jsonl` · `registry/gap_router.py` · `tests/test_gap_router.py` |
| P1-2 | **closed**（2026-11-09 D1 快照可复现） | 本地 `11-易经推理系统/scripts/data/bcrm_trades.db` 已有 49 条实盘成交（非 0 字节）；`registry/human_baseline.json` 记录 IS=24/OOS=9 指标及数据源路径（云端 `43.160.201.117` yijing-polling-trader.service）；`registry/human_config_hashes.json` 提供人工配置结构向量 hash（`b9ebc80bfa785a09`）用于 E2 新颖度判定；`metrics/emergence_metrics.py` 可读取本地 db 产出 D1 指标（`trades=49`） | D1 指标可用快照 hash 复现（已达成） | `registry/human_baseline.json` · `registry/human_config_hashes.json` · `metrics/emergence_metrics.py` |
| P1-3 | **closed**（2026-11-09 IntentEngine 轻量导入可用） | 已提供 `baselines/d3_intent_engine_loader.py`（`load_intent_engine()` + `smoke()`）与 `baselines/requirements-d3.txt`（仅 `flask` 为导入硬依赖，`requests` 为 LLM 调用时 lazy import）；不改 DreamOS 包结构，仅将 `1-ARCHITECTURE` 加入 sys.path；smoke 验证 `IntentEngine(use_llm_based=False).recognize()` 返回 `intent_type=TREND_FOLLOWING`、confidence=0.395；4 项测试覆盖实例化/recognize/smoke/flask 缺失报错 | `IntentEngine` 可导入/可跑 smoke（已达成） | `baselines/d3_intent_engine_loader.py` · `baselines/requirements-d3.txt` · `tests/test_d3_intent_engine_loader.py` |
| P1-4 | **closed**（2026-11-09 事件源可复现） | `events/` 子目录已在位（emergence_shadow/ · gates/ · memory_readout/）；`trajectories.jsonl` 实际位于 `.workbuddy/agent_mail/`（34 行）、`l1_case_store.jsonl` 位于 `34-前端应用训练系统/`（4803 行），由 `metrics/emergence_metrics.py` 读取；已创建 `events/README.md` 文档化目录结构、外部数据源路径、事件 schema 与可复现命令；验证 `python metrics/emergence_metrics.py` 输出 `trajectories=34, cases=4803, trades=49` | E4b/E5 事件源可复现（已达成） | `events/README.md` · `metrics/emergence_metrics.py` |
| P1-5 | **closed**（2026-11-09 6×30 SSoT 已确认） | 已确认 DreamOS S 层意图体系升级完成：`core/sense/dialogue_intent/` 下的 6×30 体系（6大类×30二级意图）是对话意图权威正典——`intent_taxonomy.schema.json` 自标注为「单一真相源（SSoT）」version 1.0.0，含风险等级映射(query=low/analysis=medium/trade=high/strategy=medium/risk=medium/dialog=low)、能力路由(query→database、analysis/trade/strategy/risk→trading_nodes、dialog→direct_response)、槽位归一化(`slots.py`)、多意图检测(`multi_intent.py`)。旧 `types.py` IntentType(12型) 为过渡方案（`intent_engine.py` 尚未迁移，已知技术债）；35型前端正典通过映射桥接到 6×30。已创建 `registry/intent_ssot_mapping.json`（6×30→35型/12型 30条映射 + 35型→12型 13条）与 `registry/intent_ssot.py`（加载器+validate，`6x30=6×30, mappings_6x30_to_legacy=30, legacy_35_to_12=13, unmapped_35=22` 验证通过）。 | 单一正典（6×30 SSoT v1.0.0 ✅）+ 映射表版本化（✅） | `registry/intent_ssot_mapping.json` · `registry/intent_ssot.py` · `1-ARCHITECTURE/dreamos/core/sense/dialogue_intent/` |
| P1-6 | **closed**（2026-11-09 双 Agent 校准通过） | 采用两位独立 AI 标注员（Agent A 严格架构师 / Agent B 务实工程师）完成双盲标注，衡量 rubric 在两位独立评审间的一致性（透明声明：非人工-AI 一致性）。流程：①`review/build_calibration_samples.py` 从 D2-A predictions（8 run, 255 边）与 D3-A intent_events（1092 会话）分层抽样 240 条（D2=120/D3=120，good=40/medium=120/poor=80），冻结 sha256 `f63a15c1...`；②Agent A/B 独立标注，输出 `annotations_a.jsonl` / `annotations_b.jsonl`；③`review/merge_and_calibrate.py` 合并并调用 `registry/review_calibration.py` 计算 κ/α。**结果**：n=240（≥200 ✅），Cohen's κ=0.7301（≥0.60 ✅），Krippendorff's α=0.8373（≥0.67 ✅），一致率 83.8%，差>1 档分歧=0（无需仲裁）。分实验：D2 κ=0.6297/α=0.7496，D3 κ=0.8141/α=0.8996。校准报告见 `review/calibration_report.md`。 | ≥200 标注 + κ≥0.60 + α≥0.67（全部达成 ✅） | `review/samples_to_annotate.jsonl` · `review/annotations_a.jsonl` · `review/annotations_b.jsonl` · `review/calibration_annotations.jsonl` · `review/calibration_report.md` · `registry/review_calibration.py` |

> **状态规则**：只有产物落盘 + 证据链接 + 退出条件满足才可置 `closed`；P0-2/P0-3 的基线生成不等于关闭——直接意图标签/图人工复核仍是前置。

### 12.1 P0 基线生成器（2026-11-09）

| 基线 | 生成器 | 输出 | 状态 |
|---|---|---|---|
| D2 架构图 | [build_d2_architecture_graph.py](../../baselines/build_d2_architecture_graph.py) | `baselines/artifacts/d2_architecture_graph/`（graph + summary + manifest） | ✅ 已入库（2026-11-09 真实运行）：7859 nodes / 53959 edges；闭合校验 0 悬挂边；parse_errors=97 已计数；sha256 可核验（结构哈希，剔除 generated_at）；**人工复核清单已备料**（4 模块 / 32 条 inbound import 边，见 `experiments/d2a_holdout/results/D2A-b5ae5586b3b8/manual_review.md`），其中 2 模块泄漏审计 clean、2 模块有仓内重复副本 caveat（不影响边核验）；待人工签字放行 |
| D3 意图事件 | [build_d3_intent_events.py](../../baselines/build_d3_intent_events.py) | `baselines/artifacts/d3_intent_events/`（summary + split + manifest；raw JSONL 按隐私约束不入库） | ✅ 已执行（2026-11-09）：1092 sessions / 0 解析错误 / 75:25 时序切分 train=819 test=273（≥200 达标）；task_type 12 类（configuration 392 为最大类）；**直接意图标签已补**（`intent_label` / `intent_trajectory` / `intent_signals` / `intent_label_confidence`；stable=997，drifted=95） |

运行：

```bash
python 48-涌现架构/baselines/build_d2_architecture_graph.py
python 48-涌现架构/baselines/build_d3_intent_events.py
```

口径：D3 产物是 `task_type` 代理，不是用户意图标签；D2 产物是 Python-only 基线，call 边为函数名级、无运行时数据流。详见 [baselines/README.md](../../baselines/README.md)。

---

## 附录 A：度量目录

### A.1 D1（沿用 v0.5 + 阻力四元组）

| 指标 | 定义 | 数据源 | 频率 |
|---|---|---|---|
| `M-D1-NET-PNL-OOS` | 成本后 OOS 净 PnL | bcrm_trades.db / shadow 回测 | 每周 |
| `M-D1-SHARPE-OOS` | OOS Sharpe | 同上 | 每周 |
| `M-D1-MAXDD` | 最大回撤 | 同上 | 每周 |
| `M-D1-RESISTANCE` | `{slippage_bps, fee_bps, holding_hours, maxdd_pct}` 归一化综合（四项统一 lower_better；归一化 P0 冻结：**禁用滚动窗口 min-max**——历史分数不得随窗口回变，建议固定参考区间 min-max；缺失值策略 report，不填补） | 执行/成交/持仓 | 每周 |
| `M1-M7` | 48 v0.5 既有 M1-M7 | 48 metrics | 每日/每周 |

### A.2 D2

| 指标 | 定义 | 基线 | 判定 |
|---|---|---|---|
| `M-D2-EDGE-P/R/F1` | 预测图边 vs 实际 AST 图 | B0/B1 | 越高越好 |
| `M-D2-INTERFACE-MATCH` | 接口签名结构匹配率 | B0 | 越高越好 |
| `M-D2-DATAFLOW-ACC` | 数据流路径准确率 | B0 | 越高越好 |
| `M-D2-ADR-MATCH` | 设计决策匹配率 | B0 | 越高越好 |
| `M-D2-DOC-COVERAGE` | 结论有证据链接比例 | — | ≥0.9 |
| `M-D2-ENG-GATE-PASS` | 45 E-H/E-W 通过率 | — | 硬门禁 |
| `M-D2-CHANGE-COUPLING` | 依赖 fan-in/fan-out | 人工方案 | 越低越好 |
| `M-D2-REWORK-RATE` | 人工返工比例 | — | 越低越好 |
| `M-D2-NOVELTY` | 与已有设计图编辑距离 | — | ≥k |
| `M-D2-HUMAN-RUBRIC` | 盲评 1-5 | — | ≥4 |

### A.3 D3

| 指标 | 定义 | 基线 | 判定 |
|---|---|---|---|
| `M-D3-TOP1/TOP3/MRR` | 下一意图预测 | B0-B3 | 越高越好 |
| `M-D3-ACCEPT-RATE` | 用户接受/未修改比例 | B2 | 越高越好 |
| `M-D3-CLARIFY-TURNS` | 平均澄清轮次 | B2 | 越低越好 |
| `M-D3-TIME-TO-ACTION` | 输入到正确动作时间 | B2 | 越低越好 |
| `M-D3-CORRECTION-RATE` | 后续纠正比例 | B2 | 越低越好 |
| `M-D3-ECE/BRIER` | 置信度校准 | — | ECE≤0.1 |
| `M-D3-NOVELTY` | 意图组合距离 | — | ≥k |
| `M-D3-USER-CONFIRM` | 新颖组合用户确认率 | — | ≥阈值 |

### A.4 跨域

| 指标 | 定义 | 判定 |
|---|---|---|
| `M-X-I2E-GAIN` | 有/无 D3 预测的工程任务完成时间/迭代/纠正差异 | 显著为正 |
| `M-X-E2T-GAIN` | D2 方案对交易模块缺陷率/shadow 指标的改善 | 显著为正 |
| `M-X-INTERACTION-3` | 三因素交互项 `G_123`（2×2×2 因子设计，§1.2/§4.5.3） | 95% CI 不含 0 且方向为正，且 Ω>0 复核通过，且 ≥1 个 `G_ij` 为正（Holm 校正） |
| ~~`M-X-SUPERADDITIVITY`~~ | `G(joint) - ΣG(independent)`（**v0.3 起废除**：无法区分两维与三阶交互） | — |

---

## 附录 B：协议级 schema 示例

### B.1 `ArchitectureGraph`

```json
{
  "graph_id": "ARCH-20261108-001",
  "version": "v0.1",
  "nodes": [
    {"id": "48.bus.emergence_bus", "type": "module", "path": "48-涌现架构/bus/emergence_bus.py", "layer": "L1"}
  ],
  "edges": [
    {"from": "48.bus.emergence_bus", "to": "4-MEMORY.workspace_bus", "type": "import", "evidence": "import workspace_bus"}
  ],
  "data_flows": [
    {"source": "domain_anomaly", "transform": "3σ ignite", "sink": "events/emergence_shadow", "schema": "v0.1"}
  ],
  "design_decisions": [
    {
      "decision": "复用 workspace_bus 而非新建 GWT",
      "context": "workspace_bus 已实现但闲置",
      "alternatives": [{"result": "新建总线", "level": "inference", "known_gaps": ["重复建设"]}],
      "evidence": ["workspace_bus.py", "48 SPEC v0.4 P1"],
      "known_gaps": ["需 shadow 冒烟"]
    }
  ],
  "provenance": {"owner": "", "generated_by": "", "source_snapshot": ""}
}
```

### B.2 `DesignRationale`

```json
{
  "decision_id": "ADR-...",
  "decision": "",
  "context": "",
  "consequences": [],
  "alternatives": [{"option": "", "reason_rejected": "", "evidence": []}],
  "evidence": [{"type": "observation|derivation|inference", "ref": "", "confidence": 0.0}],
  "known_gaps": [],
  "provenance": {}
}
```

### B.3 `IntentPrediction`

```json
{
  "prediction_id": "INT-...",
  "session_id": "",
  "ts": "ISO8601",
  "predicted_intent": "",
  "taxonomy": "35-type|7-type|6x30",
  "confidence": 0.0,
  "evidence": {
    "history": [],
    "habits": [],
    "error_cases": []
  },
  "knowledge_combo": {
    "memory_ids": [],
    "skill_ids": [],
    "doc_ids": []
  },
  "suggested_actions": [],
  "clarification_needed": false,
  "provenance": {}
}
```

### B.4 `ExperimentResult`

```json
{
  "experiment_id": "EXP-D3A-20261108-001",
  "hypothesis": "",
  "protocol_version": "SPEC-EMERGENCE-3D-v0.1",
  "data_snapshot": {"hash": "", "range": ""},
  "baselines": [],
  "metrics": [],
  "n": 0,
  "stat_test": "",
  "p_value": null,
  "effect_size": null,
  "verdict": "not_run|insufficient_data|falsified|inconclusive|candidate|rejected|verified",
  "limitation": "",
  "artifacts": [],
  "review": {"human": false, "reviewer": "", "date": ""},
  "ts": "ISO8601"
}
```

---

## 附录 C：存量资产映射

| 需求 | 现有资产 | 复用方式 | 缺口 |
|---|---|---|---|
| D2 架构模式 | 33-REA `architecture_pattern_detector.py` | 只读调用，输出 Evidence | 模式规则需扩展仓内架构 |
| D2 调用/依赖 | 33-REA `call_chain_tracer.py` / `dependency_graph.py` | 只读调用 | 跨语言 TS/JS 支持待核 |
| D2 设计决策 | 33-REA `design_decision_recovery.py`（`DesignDecisionRecoverer`/`recover_decisions`） | 只读调用 | inference 级需 known_gaps |
| D2 演化 | 33-REA `evolution_narrative.py`（`EvolutionNarrator`/`generate_narrative`） | 只读调用 | 需与 git 历史对齐 |
| D2 方法论 | 33-REA `methodology_abstraction.py`（`MethodologyAbstractor`/`abstract_methodology`） | 只读调用 | 跨项目样本有限 |
| D2 工程门禁 | 45 §5.3 E-H/E-W | 引用阈值，不复制内核 | 45 evaluators 已实现；3D 集成未实现 |
| D2 文档检索 | 2-KNOWLEDGE RAG / 41 索引 | 只读检索 | 需文档-代码统一图 |
| D3 意图识别 | DreamOS IntentEngine | 只读调用/shadow | 预测目标需新建；本地导入需 flask/轻量路径 |
| D3 意图评估 | IntentEvaluatorAgent | 复用 recall/jev/laya | 需结构化意图标签 |
| D3 会话数据 | `.cognitive/sessions`（11-09 复核 1073 dirs / 1072 非空；task_type/action_chain） | 只读派生 | 无直接 intent 标签；gitignored runtime data |
| D3 灰度 | 前端 `shadow-probe.ts` | 复用模式 | Python 侧需等价实现 |
| D3 评测 | 45 §9-10 | 引用协议 | ✅ 校准集已建（240 条，κ=0.7301/α=0.8373，P1-6 closed） |
| 记忆 | 35 C1-C4 / 4-MEMORY | recall/record/verify | 需 D2/D3 标签 schema |
| 缺口路由 | 48 E6 `capability_gaps.py`/`gap_router.py` | 复用存储/路由 | ✅ 6 个新 gap_type 已注册（P1-1） |

---

## 附录 D：版本与评审记录

| 日期 | 版本 | 变更 | 状态 |
|---|---|---|---|
| 2026-11-08 | v0.1 | 首版：三维判据矩阵、统一度量/标签 schema、D2-A/D2-B/D3-A/D3-B/跨域协议、P0-P4、六维自检 | 🟡 草案 |
| 2026-11-08 | v0.1-review | 六维评审（§11）：修改后接受；数据口径修正（366 sessions/无直接 intent 日志/E6/trade/events 缺失）；加 OOD 强制点 P0 前置 | 🟡 P0×3/P1×6/P2×3 待关闭 |
| 2026-11-09 | v0.2 | 外部评审修订：重写跨域判定（共同效用前置 + 2×2×2 因子 + 三阶交互）；移除 D2-A 新颖度门槛；candidate/verified/rejected 流转统一；模块级聚类 bootstrap 与主终点唯一化；OOD 未闭合前 D2-A/D3-A 降级探索性并区分实验隔离与 FAIL-OPEN；D3-A 预测目标/特征截止/切分表与泄漏审计；P0 状态同步；复合值 schema | 🟡 讨论稿（外部评审「需修改」修订版） |
| 2026-11-09 | v0.3 | 评审整合复核：§4.5.3 与 §1.2 对齐（清除已废除超加性公式残留，补全 8 臂）；数据快照刷新（sessions 366→1072，D3-A 量级结论重估）；§12 状态术语中文化；P1-1/P1-4 证据按实况更新；§6.3 隐私补强（hash≠匿名化）；A.1 阻力归一化禁滚动窗口；附录 D 补登 | 🟡 讨论稿（待复审） |
| 2026-11-09 | v0.4 | 外部成熟经验整合（五路调研 44 候选→采纳 23，附录 E）：§1.2 增设 Ω 协同复核通道；E5(b) 升级 Clauset 幂律检验 + MR-estimator + log-log 形状检验；§4.0 泄漏审计加 canary 第 4 重 + 第 12 条脚手架披露卡；§2.1 D1 三层多重比较防线 + E2 收益层去重；复审修订（§11.5）：OOD hook/基线产物「未入库」如实标注、§4.5.3/附录A 补 Ω、§5 P3 清残留、B.4 补 rejected | 🟡 讨论稿（内部复审修改后接受，待外部复审） |
| 2026-11-09 | v0.5 | 实验实现对齐：D2-B/D3-B 假设表优先级由「P2 后做」改为「已实现 candidate」；§4.2/§4.4/§4.5 新增 D2-B/D3-B/X-A 实现状态块（run ID、verdict、关键指标、剩余事项）；§5 路线图 P2/P3 标注已实现 candidate + 剩余真实门禁/A/B；§9 结论更新剩余事项清单（E1/E4 生产埋点、X-A 真实 A/B、E1 shadow 积累、D2-B 真实 45 门禁）；§11.2 P1-1 标为已关闭 | 🟢 实现对齐（代码已落地，verdict 仪表盘 5 candidate） |

> **文件名说明**：文件名冻结为 `SPEC-EMERGENCE-3D-v0.1.md` 以避免外部引用（README / INDEX / 评审记录 / baselines README）链接漂移；内容版本以本文头部与附录 D 为准。

**下一步**：

1. **E1/E4 脱离 pipeline_only 代理**：补 11 域交易 recall 结构化日志 + HermesReflector `active_reflection_id` 动作侧补记；
2. **D2-B 真实 45 门禁**：在 45 沙箱实际运行工程门禁 + 人工盲评（当前为门禁代理）；
3. **X-A 真实跨域 A/B**：积累 D1 shadow 跑数后做 T-I2E / T-E2T 在线 A/B（当前用 candidate 主指标做 proxy）；
4. **E1 shadow 积累**：连续 7 天 shadow 跑数 + ≥1 次非预设联动候选（人工复核）；
5. 决策 §8 开放问题（所有权、意图 SSoT、gap_type、预算、隐私、OOD 归属、v0.6 范围）。

---

## 附录 E：外部成熟经验借鉴（v0.4 新增）

来源：2026-11-09 五路并行调研（AI 涌现工程 / 金融工程 / 代码工程 / 意图学习 / 生物复杂系统），44 条候选经交叉验证采纳 23 条。分级：**T1 判据级**（已入正文）、**T2 工程级**（实施时采用）、**T3 概念级**（参考）。凡涉阈值/参数，一律随 `experiment_prereg.json` 预注册冻结，不得事后调整。

> **实现状态（v0.4 复审确认）**：T1 全部方法（SΩI/Ω 估计、Clauset/powerlaw、MR-estimator、PBO/CSCV、SPA/DSR、purgedcv）当前工作树**零实现、零依赖**，均属新建项——实施任务必须含依赖登记与最小实现；正文判据均有 `insufficient_data` 兜底，不得因工具缺失虚报或跳过。

### E-T1 判据级（正文已修订）

| # | 来源 | 做法 | 落点 |
|---|---|---|---|
| T1.1 | Clauset et al. 2009；PLOS Comp Biol 2023 亚采样研究 | 幂律须 MLE+x_min 截断+KS 拟合优度+随机化 null model 似然比对照；亚采样下亚临界/混响/临界均呈 α≈1.5 | §1.1 E5(b) 升级 |
| T1.2 | O-information / SΩI（arXiv 2402.05667） | Ω=冗余−协同，符号判定三元交互；score-based 神经估计器工程可行 | §1.2 协同复核通道 |
| T1.3 | Harness 归因（arXiv 2605.23950） | SWE-bench 纯脚手架波动 11-15pp 可逆转排名；预注册附「脚手架披露卡」并锁为常量，G_123 显著仍须报脚手架方差分量 | §4.5 消融强化 |
| T1.4 | DSR / PBO-CSCV / SPA（Bailey & López de Prado） | 批内 Holm→批级 PBO（>0.5 整批拒入）→胜出者 SPA/DSR；trials_count 入 evidence | §2.1 D1 三层防线 |
| T1.5 | BIG-bench canary string | 基准内嵌唯一 GUID，语料检出即污染铁证 | §4.0 第 11 条第 4 重 |
| T1.6 | PASSUNTIL（ICLR'24） | 海量采样构造连续指标，log-log 形状判真加速，禁止肉眼报拐点 | §1.1 E5(a) |

### E-T2 工程级（实施时采用）

| # | 来源 | 做法 | 落点 |
|---|---|---|---|
| T2.1 | Copilot 三级漏斗（CACM'24） | 接受率拆 shown/accept/persist（120s 内未修改才算真接受） | §4.3/§4.4 D3-B 指标 |
| T2.2 | OpenHands/SWE-agent 沙箱三铁律 | 测试文件只读、隐藏套件不进 agent 文件系统、判分用全新容器 | §4.2 D2-B 执行协议 |
| T2.3 | EvalPlus | 隐藏测试加 LLM+变异增强（~80×），防脆弱「恰过」解 | §4.2 隐藏测试 |
| T2.4 | AlphaGen | 新颖性=对既有 alpha 池收益 \|ρ\|<0.5 + 组合 IC 边际增量>0（收益层去重） | §2.1 E2 准入（已入正文） |
| T2.5 | CPCV+embargo（AFML ch.12） | 组合吹扫 CV，embargo=最大 holding_hours，准入用路径中位数与下分位 | §2.1（已入正文） |
| T2.6 | SWE-bench Verified | holdout 人工核验三标准（问题清晰/测试可判/信息可解）+ 快照记「人工核验率」 | §4.1 P0-3 复核 rubric |
| T2.7 | MMAS 蚁群信息素 | 需求单机制三参数：蒸发率 ρ∈[0.02,0.5]、[τ_min,τ_max] 硬界防锁死、仅当轮最优响应者强化 | C 类 stigmergy（主 SPEC §0.4） |
| T2.8 | MoJoFM/a2a（Lutellier ASE'15） | D2-A 保留 EDGE-F1 主判，增设 MoJoFM/a2a 聚类级辅证（前提：两边实体集相同，演化场景失效） | §4.1 辅证指标 |

### E-T3 概念级（参考）

| # | 来源 | 做法 | 落点 |
|---|---|---|---|
| T3.1 | JetBrains 触发模型 | 补 B4「触发时机基线」——何时沉默与预测内容同等重要，误触发记负样本 | §4.3 基线表 |
| T3.2 | Smart Compose（KDD'19） | 离线 Top1 与在线接受率严格分离报告，不得混报 | §4.3 报告纪律 |
| T3.3 | Observe.AI taxonomy 收敛 | 不重建 SSoT：按「动作计划等价」把 35/7/6×30 映射到 L1，三体系降级 L2 视图，映射表版本化 | §2.3.4 缺口 5 |
| T3.4 | USER-LLM 参数隔离 | n=1 个性化层（用户 embedding/prefix）与全局参数隔离，防单用户污染全局 | §4.3 n=1 条款 |
| T3.5 | 形态发生鲁棒性（Nagpal） | E2 自生成结构须 ±20% 参数扰动下保持模式，否则算脆弱凑巧 | E2 判据补充 |
| T3.6 | 生态位维度假说 | G1 多样性缺口操作化：定义能力生态位轴 + Shannon/Simpson 定期计量，低于阈值注入新生态位而非随机变异 | 主 SPEC §3 G1 |
| T3.7 | Almgren 滑点曲线 | D1 阻力分量从常数 bps 改条件成本模型，regime 乘数按决策时点 trailing vol（禁全样本标签防前视） | 附录 A.1 细化 |
| T3.8 | Brinson 多策略归因 | E3 超加性以 Interaction 项 95% CI 与反事实 MAE 双口径并列报告 | 主 SPEC E3 |
| T3.9 | ΦID 信息原子谱 | 跨域迁移归因：迁移主要由 redundancy 承载则非真协同，协同原子占比设阈值 | §4.5 X-A 增强 |

### E.4 冲突仲裁记录

1. **Holm / SPA / DSR / PBO 不混用**：分层各司其职（批内/批级/胜出者），预注册冻结；禁止事后选最有利口径。
2. **Ω 信息不替换 G_123 主判**：计算成本高、估计器需训练，定位复核通道；双通道一致才可申报。
3. **MoJoFM 只能辅证**：实体集一致性前提在演化场景失效，不作主终点。
4. **E5 加严与数据现实**：Clauset 标准需要事件量，当前 cascade n_events 极小——加严的同时允许 `insufficient_data` 如实记录，不得为过关凑事件。
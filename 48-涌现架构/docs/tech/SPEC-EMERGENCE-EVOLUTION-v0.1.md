# SPEC-EMERGENCE-EVOLUTION v0.5

> 日期：2026-11-05（v0.1 初稿 → v0.2 调研回填+E-BIZ → v0.3 正反方辩论评审后修订 → v0.4 架构×数据流双维深度评审 → v0.5 六维实证评审封口）
> 来源：用户提问"系统能否出现智能涌现效应"+ 两线调研 + 用户"涌现什么"方向修正 + v0.3 评审裁决（25/30，修改后接受）+ v0.4 双维评审（P0×5 + P1×7）
> 状态：🟢 v0.6 落地中——E0a/E0b/E4a/E4b/E1/E2/E3/E5/E6 全部至少落盘（2026-11-07）：E1 shadow 探针 runner 已部署 systemd 常驻（300s 周期）+ 积累达标自动放行开关（每日 06:30 timer）；E2 评估器升级多源可插拔（v2_multisrc）；E3 滚动复测 e3_candidate_weak（Q2/Q3 显著正，Q4 不显著）；E5 强原语复测 inconclusive 方向转正；E4b 动作侧 active_reflection_id 补齐；E6 需求单 4 张已发
> 变更（v0.5→v0.6，实验进度对齐 2026-11-06/07）：E1 补 shadow 探针 runner（bus/run_shadow_probe.py，systemd yijing-emergence-shadow-probe）+ 积累达标自动放行（registry/accumulation_gate.py，systemd timer 每日 06:30，E1 判据=7 自然日+M1 动作≥1，E4b cascade 判据=点火事件≥20）；E2 评估器多源升级（backtest_evaluator.py v2_multisrc：kline_csv/json_ts/json_closes/memory 四种可插拔源规格，不局限 11 域）；E3 滚动复测（e3_coupling/rolling_retest.py，季度切窗：Q2 +3.0%/Q3 +2.9% 显著正，Q4 -0.5% 不显著 → e3_candidate_weak 如实降级）；E5 强原语复测（e5_cbr_holdout/e5_strong_primitives.py：6 维状态含 quality_score + median 分位标签，+1.34pp p=0.72 inconclusive 方向转正；next_state 全空已如实标注）；E4b 动作侧补记 active_reflection_id（cognitive_session.py 6 处，精确 join 锚点就绪）；18 标的 K 线核验通过（4×6101 行 + 14×2101 行）
> 变更（v0.4→v0.5，六维实证评审）：K 线回填标记完成（btc_1h_ts.json fetched 11-04，5022 根至 11-05）；ckpt 日期修正（10-06 → 实际 11-03，重训前置降级为常规步骤）；E0b 估时回调 5-7 → 3-4 天；登记第三轮评审记录（修改后接受）
> 上游：35-广义认知 C1-C4（SPEC-CognitiveSystem-Evolution v0.2）、46-DSH、47-MCP、44-三端协作架构、4-MEMORY workspace_bus.py、19-数据访问层
> 下游：Phase E0b-E6 实施任务、48/experiments 实验记录、48/metrics 度量快照
> 变更（v0.3→v0.4，架构×数据流双维评审）：
>  **P0 封口（5 项）**：①E3 regime 数字以 artifact 重核（bull 2760/chop 1534/bear 728）+ 补 head 重训前置；②ablation gate 引用从"不存在"改为 §4 E2 明确新建；③OOD 隔离加代码级强制点（案例库+verify 黑名单参数）；④E0 前置补 polling_trader 决策回放器 + K 线回填；⑤readout 断链加 recall 落盘事件
>  **P1 关键修（7 项）**：E1 从"最小实现"改为复用既有 workspace_bus.py + shadow envelope；L0-I 契约申请改为 44 域或删除；E2 边界声明补 33-REA；E0 状态从"未开工"改为"E0a 已落盘/E0b 待前置修补"；E4a 云端可读复用 deploy/git-sync.sh；M2 明确两做梦器 schema 统一；M4 反思→修复 join 链路补映射

---

## §0 Executive Summary

### 0.1 做什么

评估 dreambuddy-v2（四层闭环自进化交易架构 + 五系统四层认知架构）是否具备**智能涌现**条件，并给出创造条件（enablement，不是 engineering）的实施路径。核心动作：把"涌现"从哲学词变成**可证伪的度量 + 可复现的实验**。

### 0.2 不做什么

| 禁止 | 原因 |
|---|---|
| 不宣称"已涌现" | 当前无任何判据满足，宣称即自欺 |
| 不为涌现放宽既有门禁 | ablation gate / PSI 阈值保持（VM-1793798309647 硬约束） |
| 不在生产链路做实验 | 全部 shadow 模式，FAIL-OPEN |
| 不加"为了涌现而涌现"的新模块 | 只接现有机制（GWT bus / 做梦器 / coupling head） |
| 不用单点轶事当证据 | 涌现证据 = 统计上可复现的度量，不是"某次看起来很聪明" |

### 0.3 判定原则

**涌现不是设计出来的，是创造条件让它发生的。** 本 SPEC 的所有 Phase 都是"创造条件 + 布设度量"，不是"实现涌现"。

### 0.4 涌现什么（北极星定义，用户决策 2026-11-05）

涌现能力不会凭空而来，必须锚定价值目标。本系统追求**三类**涌现：

**A 类·架构机制涌现（E1-E5 判据，§1）**：系统层面表现出组件不具备的整体能力（组合泛化/自生成目标/非线性耦合/自纠错/规模相变）。这是**机制层**判据，回答"系统是否在涌现"。

**B 类·业务价值涌现（E-BIZ）**：系统**自主利用全部数据资产、子交易系统与模块化能力，自动发现并验证最佳策略实践**——入场、仓位管理、离场、子策略选择与组合——使交易结果优于所有人工编写策略。这是**价值层**判据，回答"涌现有没有用"。

**C 类·需求驱动涌现（E-DEMAND，用户 2026-11-05 提出）**：交易主链在涌现过程中**发现能力缺口并反向驱动系统自主扩能**——例：BDSM 基本面缺某币种信息 → 数据采集中心被驱动采集；回测发现某因子有利但样本不足 → 驱动因子搜索/数据补充；CBR 某域案例稀疏 → 驱动 evolution-case-ingest 定向补案例。这是**进化层**判据，回答"系统的能力边界能否被主链需求自主外推"。

C 类可证伪判据（四条同时满足才算达成）：
1. 主链路运行中产生**结构化缺口信号**（数据缺失/因子不足/案例稀疏/域耦合无数据支撑）
2. 缺口被**自动路由**到正确能力域（19 数据采集 / 因子工程 / case-ingest / wind 数据），非人工指派
3. 能力补齐后主链指标（覆盖率/回测表现/信号质量）**统计显著改善**
4. 全程可审计 + FAIL-OPEN（能力域无响应时主链降级不崩溃）

C 类的自然原型：**stigmergy**（BIO §2.1 蚁群信息素间接通信）——主链在共享环境里留下"需求单"（信息素），能力域自主响应，无需中心调度。已有雏形：`evolution-case-ingest`（按需补案例）、`data-troubleshoot`（数据缺口排查链）。

**三类关系**：A 类是"是否在涌现"的判据基础；**B 类是价值北极星**；**C 类是进化引擎**——B 类在求最优时撞上能力边界，C 类把边界外推，推完 B 类继续向更优爬升。A 类全部度量服务于 B/C；为机制好看而不通向 B/C 的涌现指标不算数。

---

## §1 涌现可操作判据（E1-E5）

不满足判据 = 没涌现。判据设计原则：每条都可被实验证实或证伪。

| # | 判据 | 定义（可测口径） | 证伪条件 |
|---|---|---|---|
| E1 | **组合泛化** | 系统解决"训练/案例中从未以该组合出现"的问题；度量：新颖组合输入下的成功率 vs 单组件基线 | 新颖组合上成功率 ≤ 检索最近邻复用 |
| E2 | **自生成目标** | 系统提出人未写入 SPEC/配置的策略或假设，且事后 verify 有效；**"人未写过"操作化定义（v0.3 评审封口）**：生成物的结构向量（开关位掩码+执行顺序编码+阈值分箱）不在人工配置 hash 集内，且与最近人工配置的编辑距离 ≥k（k=2，写入 48/registry 人工配置基线文件）；度量：`verify 成功 且 满足上述距离条件的产物数 / 总生成数` | 该比率恒为 0；或人工配置基线文件缺失（此时判据悬置，不得申报） |
| E3 | **非线性耦合** | 整体预测优于任何单模块线性叠加；度量：反事实输入下 coupling 模型 MAE vs 单域 baseline | 反事实 MAE ≥ baseline（当前 β 原型已证伪一次） |
| E4 | **自指纠错** | 系统发现自身错误并自我修正；度量：故障注入后被内部机制（非人工）检测并修复的比例 | 注入故障全部需人工介入 |
| E5 | **规模相变**（双口径） | (a) 能力-规模曲线出现非光滑拐点（记忆数/案例数/窗口数轴）；(b) 临界态三件套**同时**出现：级联尺寸分布近幂律 + 分支系数 σ≈1 + 序参量凝结信号（与 §7.2 BIO 结论对齐；三缺一则 E5(b) 悬置不得申报） | 曲线全段光滑可外推；或三件套任一不成立 |

### 1.1 当前系统打分（2026-11-05 快照）

| 判据 | 状态 | 依据 |
|---|---|---|
| E1 | 🟡 弱种子 | CBR/KNN 是检索复用，**不是组合生成**；evolution-case-ingest 只在三场景（washout/washout_reversal/pump_dump_reversal） |
| E2 | 🟡 种子未开 | 做梦器 V(π,T) 路径寻优存在，但只在人写的策略空间内搜索 |
| E3 | 🟡 起步即受挫 | DomainCouplingHead 已训出 coupling（15 对域），但 β 原型报告：签名特征中位改善 -0.68%，方向为负；regime 数字以 artifact 重核（**v0.4 修正**：`btc_1h_ts.json` fetched 2026-11-04，bull 2760/chop 1534/bear 728，n=5022）；coupling ckpt 实际 mtime 2026-11-03（v0.5 实证修正，原记 10-06 有误）仍早于修复日 → head 需重训后才能重测（v0.4 前置步骤，v0.5 降级为常规步骤） |
| E4 | ✅ 部分具备 | hermes 反思 + debate 正反方 + FAIL-OPEN + dream-acceptance-verify 五维验收在跑；但反思产物进主决策链的比例未度量 |
| E5 | ❌ 无度量 | 无能力-规模曲线追踪 |

**结论：0/5 满足，1/5 部分具备。系统是"有涌现潜力的结构化自进化系统"，不是"涌现中的系统"。**

---

## §2 已有涌现种子盘点（真实资产，非设想）

| # | 资产 | 位置 | 对应判据 | 距可用差距 |
|---|---|---|---|---|
| S1 | GWT Workspace Bus | 真实实现已存在：`4-MEMORY/9-工具与接口/workspace_bus.py`（10月12日，pub/sub+ignite+FAIL-OPEN，**从未被生产 import**） | E1/E5 | **已实现但闲置**——v0.4 修订：E1 改为接线复用而非从零实现；mcp_shells `agent_mail_shadow.py`+`shadow_hook.py` 可直接承载 shadow 广播 |
| S2 | 做梦器 V(π,T) 路径寻优 | REA 做梦器 | E2 | 只在人写策略空间内，需升级为结构变体生成 |
| S3 | 认知记忆贝叶斯蒸馏（C→B→A→S） | 4-MEMORY | E5 前提 | 单向压缩，缺反向"蒸馏出新假设" |
| S4 | DomainCouplingHead（15 对域耦合） | 23 四层闭环，ckpt `23/data/neural_sde_v1_dim64.pt`（实际 mtime 2026-11-03，v0.5 实证修正） | E3 | **v0.4 补充**：ckpt 早于 regime artifact（11-04）→ E3 前置步骤=head 用修复后数据重训；regime 数字以 artifact 为准（bull 2760/chop 1534/bear 728，非原文 4074/2832/1349） |
| S5 | debate 正反方 + 6 维裁判 | dream-* SKILL | E4 | 仅在辩论闭环，未进交易决策主链 |
| S6 | hermes 反思 + L4 自迭代 | dream-self-iteration-workflow | E4 | 反思→SKILL 生成链路存在，触发率未度量 |
| S7 | MoE 3 experts + Cross-Attention | 23 四层闭环 | E3 | expert 特化程度未度量 |

---

## §3 关键缺口分析

### G1 多样性压力不足（首要缺口）

涌现需要大量"不同解"竞争。当前：18 标的 × 固定策略开关组合；做梦器在人写空间寻优；CBR 三场景案例库。**没有出乎意料的解能被生成，涌现无从谈起**。

### G2 缺非对称带宽广播/竞争

模块间基本点对点调用。涌现需要"一个域的异常被所有域低成本感知并竞争响应"。GWT bus 正是为此设计但未落地。

### G3 缺涌现度量面板

没有能力-规模曲线、E2 比率、广播联动率等指标的持续追踪。**没有度量面板的涌现永远是哲学讨论。**

### G4 选择压力目标是人工指定的

fitness = 人工权重（MAE/PSI/pnl 七维奖励）。自然界的涌现 fitness 是环境自适应的。这是深层缺口，Phase 内只做缓解（多目标 + 反事实），不解决。

---

## §4 实施路径（Phase E0-E6）

> 原则：每个 Phase 都是"接现有机制 + 布度量"，不新建大模块；全部 shadow 先行。

### Phase E0 — 人工策略池基线（v0.3 新增，v0.4 重估工期）

- **状态快照（v0.4 重认）**：E0a 已落盘——`48/registry/human_config_hashes.json`（含云端实盘配置结构向量 schema+id）、`struct_vector.py`（编辑距离 k=2）；**E0b（OOS 基线运行）仅剩回放器缺口（K 线已回填，v0.5 实证），估时从 5-7 天回调至 3-4 天**
- **前置补丁（v0.4 发现）**：
  1. **K 线回填至当前**：~~本地 1H 止于 2026-07~08 月~~ **v0.5 实证：已回填**——`23/data/btc_1h_ts.json`（fetched_at 2026-11-04）5022 根 1H K 线，最后 bar 2026-11-05，数据新鲜连续；18 标的回填状态待 E0b 开工时逐标的核验
  2. **polling_trader 决策回放器（新建 shadow 模块）**：现有 11/ 下全部回测（evolution_backtest.py、bcrm2/walk_forward+portfolio、pentagon）均为子系统回测，无一回放 polling_trader 实盘完整决策链——需新建轻量 replay 模块（shadow 性质，不触发实盘交易）
- 内容（不变）：盘点当前全部人工编写策略/开关组合，在统一 walk-forward OOS 区间跑基线，产出 `48/registry/human_baseline.json`（每条：配置 hash、结构向量、OOS PnL/夏普/回撤、区间）
- **度量 M0**：基线覆盖率（人工策略池中完成 OOS 评测的比例）
- 验收：基线文件落盘 + 覆盖率 100% + 区间满足 §5 OOD 隔离纪律（v0.4 P0#3 强制：入库黑名单参数）
- **没有 E0，E-BIZ 与 E2 判据永久不可判定——E0 是全部后续 Phase 的前置**

### Phase E1 — 广播总线接线复用（估 2 天，v0.4 重订：不再从零实现）

- **落地状态（2026-11-05）**：🟢 基础设施已落盘——`bus/emergence_bus.py`（3σ 点火 + 接线复用 `workspace_bus.py` + envelope 落盘 `events/emergence_shadow/bus_*.jsonl`，开关默认关）+ `bus/shadow_subscribers.py`（rea/eval/data 兴趣规则：rea↔coupling / eval↔psi / data↔数据质量；watchlist 新入列+优先级升级=动作下限）+ `bus/m1_linkage.py` + `bus/anomaly_probe.py`（coupling 矩阵 3σ 探测，首跑 0 异常如实记录）；11 测试全绿；真实演示 PSI z=4.2 → eval 消费+动作、rea 消费无动作、data 自身不计消费，M1=0.5。剩余：shadow 跑 7 天 M1 落盘 + ≥1 次非预设联动候选（人工复核）；PSI 实时探测待 drift_detector 历史序列接口接入

- **v0.4 关键修订**：原"最小实现"改**接线复用**——GWT bus 真实实现已存在：`4-MEMORY/9-工具与接口/workspace_bus.py`（pub/sub+ignite+FAIL-OPEN，**从未被生产 import**），shadow 广播通道复用 mcp_shells `agent_mail_shadow.py` envelope→JSONL + `shadow_hook.py`/`shadow_driver.py`。**删去**"向 47 提交 L0-I 契约扩展申请"（v0.4 判定：L0-I 定义在 44 域、47 全文无此词、shadow 落盘本不需要契约——阻塞是自我强加）
- 内容：任一域 PSI 突刺 / coupling 异常 → 事件广播到 rea/eval/data 三域 → 记录非目标域的响应；**接线点**：生产 import `workspace_bus.py`，shadow 期直接落盘 envelope JSONL 到 `events/emergence_shadow/*.jsonl`
- **设计要点（BIO 条件 #5）**：(a) 广播前必须有竞争/点火阈值（建议取 3σ 偏离），不能什么都广播；(b) 广播内容必须**改变接收模块行为**，否则总线只是消息队列，不算 GWT
- **度量 M1**：广播事件被非目标域消费并产生动作的比例；**动作下限**（v0.3 封口，v0.4 保留）：仅记日志/仅 ACK 不算动作，必须改变接收模块后续输出
- 验收：shadow 跑 7 天，M1 落盘，出现 ≥1 次非预设联动记为候选事件（人工复核）

### Phase E2 — 做梦器升级为假设生成器（估 1 周，v0.4 补 ablation gate + 边界协议）

- **落地状态（2026-11-05）**：🟡 设施落盘 + 首次真实批次完成——`experiments/e2_hypothesis/variant_generator.py`（策略结构变体：开关位翻转/阈值分箱平移/标的集增删，确定性 seed；schema 校验；编辑距离≥k「人未写过」判读；正负反馈配平 keep_ratio 确定性丢弃并双向计数）+ `ablation_gate.py`（**新建**决策级准入最小实现：过拟合退化 + 分片稳定性双判据 + 最小样本 + 不优于基线即拒；阈值权属 45，本地护栏不放宽）+ `batch_schema.py`（统一两做梦器「生成批→verify」envelope，space 标注 + M2 统计）+ `run_e2.py`（主流程 + E6 需求单去重）。21 测试全绿（48 域全套 72/72）
- **首次真实批次（如实记录）**：基于 live 人工配置生成 32/32 结构变体全部通过 schema 校验且全部满足编辑距离≥2（n_novel=32）；**verify_status=evaluator_missing**——45/11 域尚无 config 级回测评估器（输入结构变体 → 输出 IS/OOS/分片指标），gate 全部如实不准入，**M2=0.0**，不伪造；已发 E6 需求单 `backtest_evaluator_missing`（created_by=e2_hypothesis，路由 45-评测系统，同类型 open 单不重复发单）
- **边界遵守**：只读引用 33-REA `core/reflection/dreaming.py`（编排空间 V 寻优，未改造）与 4-MEMORY `dreaming_engine.py`（记忆卫生）；E2 生成物零执行权，仅落批次 JSON 供评估器与人工复核
- **已知缺口**：§1 E2 结构向量含「执行顺序编码」，但 `human_config_hashes.json` 基线 schema 无该字段——本轮按现有 5 字段口径实现，执行顺序编码待 E0 基线 schema 扩展后补齐（判据不虚报）
- 内容：做梦器 shadow 模式生成 N 个**策略结构变体**（开关组合/执行顺序/阈值的结构化扰动，非参数微调），过 ablation gate + V 函数筛选
- **v0.4 关键补充**：
  - **ablation gate 落地（P0#2）**：全仓 grep 无实现——E2 前置步骤=**新建 ablation gate 最小实现**（过拟合+稳定性双判据，阈值定义权属 45-评测系统，v0.4 明确：gate 不复用 45 现有 backtest.py 统计内核，而是封装为决策级准入）
  - **做梦器边界声明（P1）**：`§8` 边界补 33-REA 域；改造 `33-REA逆向解析工程/core/reflection/dreaming.py` 属越界，需经 REA 域协商；同时仓内另有 `4-MEMORY/9-工具与接口/dreaming_engine.py`（记忆卫生）——**E2 需统一两做梦器的"生成批→verify"schema**（P1 M2）
- 硬约束：生成物必须过 STRATEGY_CONFIG_SCHEMA 校验；不优于基线即丢弃；零执行权
- **"人未写过"判读**（v0.3 封口，v0.4 保留）：按 §1 E2 操作化定义，对照 `48/registry/human_config_hashes.json`；verify 结论须经**人工复核**确认
- **正负反馈配平**：做梦器变异（正反馈）必须与记忆衰减/置信降级（负反馈）显式配平，防策略泡沫自我强化
- **度量 M2**（E2 判据）：`verify 成功 且 满足编辑距离≥k 的产物数 / 总生成数`
- 验收：M2 比率可追踪；比率从 0 变非 0 且经人工复核 = E2 硬证据候选

### Phase E3 — coupling 反事实验证（估 4 天，v0.4 补 head 重训前置）

- **落地状态（2026-11-05）**：🟡 设施落盘 + 首次真实评估完成——`experiments/e3_coupling/retrain_head_shadow.py`（120 步 shadow 重训：phaseC_jsonl_150samples target + real_btc_1h_36factors 输入 + regime 32/32/32 分层，final_loss 0.013 单调收敛；**生产 static JSON/ckpt 零触碰**，产物全落 48 域 artifacts/）+ `coupling_counterfactual.py`（对角 ridge 严格抽项 + 固定耦合系数防拟合吸收 + 符号翻转置换检验 10k 次 + 显式方向检查 + insufficient_data 联动 E6 需求单）；14 测试全绿；M3 已接入 `metrics/emergence_metrics.py`
- **首次真实评估结果（如实记录）**：①生产 static JSON coupling → **falsified**（p=0.0029 显著但方向负，中位改善 -16.6%——β 原型方向为负第二次实证）；②E3 shadow 重训 coupling → **inconclusive**（方向扳正 +5.38%，p=0.055 距 0.05 阈值一步——重训把方向从负扳正，但 150 对样本中 76% 为 static_fill 合成数据，功效不足）。按验收口径：当前不申报 E3 候选，不重复证伪结论，待真实域状态时间序列积累后重跑
- **v0.4 前置补丁（P0#1，v0.5 修正日期）**：ckpt `neural_sde_v1_dim64.pt` 实际 mtime 2026-11-03（原记 10-06 有误）仍早于 regime artifact（2026-11-04）一天，head 是用旧数据训的——**E3 先补 head 重训**（用 `btc_1h_ts.json` 重核后 regime：bull 2760/chop 1534/bear 728，n=5022），不重训则"训练好 head + 修复后数据"组合不成立 ✅ 已完成（shadow）
- 内容：重训后 DomainCouplingHead 对"trajectories 中从未出现的域状态组合"推理，与后续真实窗口对比
- **度量 M3**（E3 判据）：反事实预测 MAE vs 单域 baseline，置换检验 p<0.05 **且方向为正**
- 注意：F2 口径需补方向检查（β 报告暴露的缺陷，p=0.005 但方向为负也通过）✅ 已内置（方向为负且显著 → falsified，有 β 教训回归测试）
- **数据回填评估（2026-11-06）**：❌ 现有数据**不可回填**——全仓域状态样本仅 236 行且**只有 4 个唯一时间戳**（全部落在 2026-11-03 10:28~12:46 单批导出；`domain_discovery_training_real.jsonl` 85 行同一时刻、psi 仅 3 个唯一值 0/0.44/1.0，属批量模板快照而非时序）。E3 判据要求「下一窗口」预测，必须有时间有序的连续域状态序列，现状无窗口可 roll。`shadow_rl_samples` 的 `state` 是**市场状态**（R_up/R_down/R_smooth/R_flow/R_reflexivity）不是**域状态**（cognition/rea/search/semantic/data/eval 六域），不可替代
- **已发 E6 缺口单（2026-11-06）**：`domain_state_series_missing`（路由 4-MEMORY，去重：同类型 open/claimed 不重复发）。触发条件扩展：当 `coupling_source="static_json"`（生产静态耦合 + 76% 合成样本）时**即使 verdict=falsified 也发单**——结论建立在合成先验上，仍需真实时序复核。补齐后 E3 可从 falsified/inconclusive 转为可判定
- 验收：M3 显著为正 → E3 候选；为负 → 记录证伪，head 结构迭代；**样本功效不足 → inconclusive 如实记录 + E6 数据需求单**

### Phase E4 — 涌现度量面板（拆期：骨架 1 天 + 埋点 3-4 天，v0.4 补 readout 落盘）

- **E4a 骨架（1 天）**：`48-涌现架构/metrics/emergence_metrics.json`，每日 timer 落盘已有数据可算的字段；**v0.4 补（P1 数据源）**：timer 复用 launchd 先例（项目已有 `com.dreambuddy.etl-worker.plist`）；"云端可读"复用 `deploy/git-sync.sh` 周期性推送（全库无独立 metrics 上云通道，git-sync 最安全）
- **E4b 埋点（3-4 天）**：
  - `readout_rate`（**v0.4 重勘 P0#5**）：原"记忆只写不读"不准确——主链 `polling_trader.py` L17011 `_inject_cognitive_recall` 已消费，L10163 平仓后 verify 更新 boost；**真正断链**是 recall 无持久化日志——召回→决策改变→结果无 joinable 记录。**修复**：recall 事件（memory_ids + 后续动作）落盘到 `events/memory_readout/*.jsonl`，readout_rate 统计"写→召回→改变行动"全链比例
  - `cascade_sigma`（跨模块事件级联追踪）：E1 上线后启用，M1 复用 workspace_bus 事件日志
  - `e4_self_correction_rate`（hermes 反思→实际修复链路）：**v0.4 补（P1 M4）**：HermesReflector 需落盘 `reflection_id` + 后续修复动作映射，反思→修复 join 链路补映射表
- 验收：E4a 连续 7 天有数据且云端可读；E4b 埋点链路有单测覆盖

- **落地状态（2026-11-05）**：🟡 三埋点设施落盘 + 首次真实数据跑通，两项代理退化已如实标注、级联样本不足——`metrics/e4b_readout.py`（recall/action 事件 append-only JSONL，event_id 幂等；`backfill_from_sessions` 从 `.cognitive/sessions` 零侵入回填；readout_rate 口径=动作 ts 严格晚于 recall 且 changed_decision）+ `metrics/e4b_cascade.py`（复用 `events/emergence_shadow/bus_*.jsonl` + `resp_*.jsonl`，σ=总消费/被点火，级联尺寸分布 + log-log 幂律斜率 + σ∈[0.8,1.25] 临界带）+ `metrics/e4b_reflection.py`（`suggestions.md` 生成时间 × 同 session 72h 内修复动作时序 join）；13 测试全绿（48 域全套 85/85）；三字段已接入 `emergence_metrics.collect()`
- **首次真实结果（如实记录）**：①readout 回填 884 session → 884 recall / 884 action（1768 事件，二次跑 n_appended=0 幂等），rate=**1.0** 但 `evidence_grade=pipeline_only`——会话域 recall 在会话起始、动作必然随后，率必然趋近 1，属**退化代理**，仅验证管道，不构成 E4 证据；②cascade `n_events=1`、σ=2.0、幂律斜率 null → `status=insufficient_data`（E1 shadow 事件仅 1 条，需 7 天积累）；③reflection 882 条建议 / 849 条同 session 72h 内有修复动作 = **0.9626**，同为 `pipeline_only` 退化代理
- **已升级为 E6 缺口（不申报 E4）**：`trading_recall_log_missing`（路由 11-易经推理系统，polling_trader `_inject_cognitive_recall` 仅文本日志无结构化 memory_ids）+ `reflection_log_missing`（路由 35-广义认知，HermesReflector 未落盘 reflection_id→修复映射），补齐后可把两项代理升级为真实度量
- **边界遵守**：只读消费 `.cognitive/sessions` 与 `events/emergence_shadow/`，未改动 11/35/46 域代码

### Phase E5 — CBR holdout 原语组合泛化实验（估 2 天，LLM §6.5 / SCAN 式）

- **落地状态（2026-11-05）**：🟡 设施落盘 + 首次真实评估完成——`experiments/e5_cbr_holdout/cbr_holdout.py`（SCAN 式：5 市场原语中位数分箱 → cell 组合整体扣留 + 逐 eligible cell 池化评估；组合法=逐原语贡献 logistic 线性组合，基线=kNN 检索复用；配对符号翻转置换检验 10k 次 + 显式方向检查 + 同态误差辅助指标 + insufficient_data 联动 E6 需求单 gap_type=case_sparse）；11 测试全绿（含 SCAN 性质 toy 检验：训练未见 (1,1,0,0) 组合时组合法 5/5 泛化、kNN 0/5）；M6 已接入 `metrics/emergence_metrics.py`
- **首次真实评估结果（如实记录）**：162 回测案例（washout 69 + pump_dump 93，统一 5 原语 schema，entry_price 剔除）、8 eligible cell、n_eval=150 → **inconclusive**：组合 0.66 vs 检索 0.66 池化打平（improvement=0.0, p=1.0；逐 cell 互有胜负，如 cell[0,1,1,1,0] 组合 0.625 vs 检索 0.375，cell[1,1,0,1,0] 反之），同态误差 0.067（表征弱同态）。按验收口径：当前不申报 E1 候选，也不记证伪——数据现实制约：生产 evolution_cases/ 仅 1 案例（远低于 min_cases=30），实验只能用回测导出薄特征案例（5 原语、confidence 三特征高度相关），原语多样性不足以让组合法发挥结构优势；待真实闭环案例积累后重跑
- **shadow_rl 回填（2026-11-06，样本与原语双扩容）**：新增 `load_shadow_rl_cases` 适配器，改接 23 域 `gene_data/shadow_rl_samples.jsonl`（42.17 万行 / 16.59 万唯一 5 维市场状态向量）。口径：只取入场决策（long/light_long/short，过滤 85% 的 WAIT），原语换成 `R_up/R_down/R_smooth/R_flow/R_reflexivity` 五个**独立**市场状态维度 + `is_short` 第 6 维（`assign_cells` 参数化 `n_continuous`）。关键数据现实：reward 92.9% 为 0（未平仓占位），保留会让任何模型都预测负类、准确率虚高到 95% → **`drop_zero=True` 丢弃后用 reward>0 作标签**，有效样本 2857 条、正例 48.2%（自然平衡）；分层采样 + eligible cell 均匀抽样 8 个控制 O(n²) 成本
- **两轮真实结果（如实记录，2026-11-06）**：2857 案例 / 30 eligible cell / 评估 8 cell / n_eval=498，同态误差 **0.015**（表征同态成立，相似状态→相似结果，检索天然占优）
  - **第一轮·线性 logistic**：组合法 45.2% vs kNN 53.6%（improvement=-8.4pp，p=0.0071）→ **falsified**
  - **第二轮·非线性 MLP（单隐层 tanh，16 单元，已排除「组合器能力不足」混淆项）**：组合法 50.2% vs kNN 53.6%（improvement=-3.4pp，p=0.237）→ **inconclusive**（差距从 -8.4pp 收窄到 -3.4pp，但未超越检索且不显著）
  - **判读**：两轮均未出现「组合优于检索」，E1 判据**不成立**；但更深层事实是**该原语集对标签预测力本身弱**——kNN 也仅 53.6%（近随机），MLP 仅 50.2%。故当前结论是「在此原语/标签口径下 E1 不可判定」，不是「E1 永久不可满足」。下一步应换更强原语（多步 horizon / 相对收益分位）或换标签口径，而非继续调组合器容量
  - M6 已优先读取该结果（`e5_holdout_shadow_rl_result.json`），`limitation` 字段机器可读防误读
- 内容：把某类市场原语（如某 regime 形态）从 CBR 案例库**整体扣留**，测试系统能否用其余案例**组合**出对该新形态的正确响应
- 辅助指标：同态误差——结构相似的行情应激活相似的案例/因子组合，作为 CBR 表征质量连续监控
- **度量 M6**（E1 判据金标准）：holdout 形态上组合响应成功率 vs 最近邻检索复用基线
- 验收：组合 > 检索基线且统计显著 → E1 候选；≤ 基线 → 记录证伪

### Phase E6 — 需求驱动闭环（capability-pull loop，C 类主战场，估 3-4 天）

- **落地状态（2026-11-05）**：🟢 基础设施已落盘——`registry/capability_gaps.py`（需求单存储+状态机）+ `gap_router.py`（5 类映射+48h 告警/7 天过期）+ `gap_backfill_verify.py`（Wilcoxon 前后 14 天）；`tests/` 15 用例全绿，L1 验收（3 缺口全链路）通过，真实冒烟首单闭环。**口径实证修正**：回填验证数据源 all_trades.jsonl（更新止 2026-10-13）→ bcrm_trades.db（trades 表 exit_time+pnl_pct，与 E0b 基线同源）。剩余：信号源自动接入（需 11/19/23 域协商，FAIL-OPEN 挂载）+ L2 真实运行自发证据
- 内容：主链缺口 → 需求单 → 自动路由 → 能力补齐 → 回填验证
  1. **缺口信号源盘点**：BDSM 基本面缺币种数据 / 回测发现因子有利但样本不足 / CBR 某域案例稀疏 / coupling head 发现域耦合但无数据支撑
  2. **需求单 schema**（stigmergy 信息素）：`{gap_type, evidence, expected_value, target_domain_hint, created_by, status}`，落共享存储即完成"广播"；**v0.4 定**：存储路径= `48/registry/capability_gaps.jsonl`（原二选一，现明确）
  3. **路由器**：gap_type → 能力域映射表（19 数据采集 / 因子工程 / evolution-case-ingest / wind 数据），失败 FAIL-OPEN；未知 gap_type 落 `48/registry/gap_type_proposals.jsonl` + 人工评审；超 48h 未认领告警，超 7 天 expired
  4. **回填验证**（**v0.4 补 P1 M7 口径**）：能力补齐后对比主链指标前后变化——**主链指标已存在**：`11-易经推理系统/.workbuddy/memory_l4/stats/all_trades.jsonl` + `daily_summary_*.json`（更新至 2026-10-13），直接作前后对比基准；gap 解决后跑 Wilcoxon signed-rank 检验对比补齐前后 14 天 PnL 序列
- **度量 M7**（C 类判据）：`gap_resolved_rate`、`time_to_capability`、`主链指标改善显著性`
- **验收分两级**：L1 链路验证（构造 3 个已知可解缺口）/ L2 涌现证据（真实运行自发产生）

### 依赖与顺序（v0.4 更新）

**E0 最先行**（人工策略池基线——E-BIZ 判据③与 E2 口径的共同前置，没有它北极星不可判定；**v0.4 补**：E0 前置修补=K 线回填 + polling_trader 回放器）→ E4a 骨架（1 天）→ E6 / E1 / E3 / E5 可并行（**v0.4 删**：E1 受 47 契约申请节奏约束——已改为复用 workspace_bus+shadow envelope，无外部阻塞）→ E4b 埋点（依赖 E1/E6 事件流）→ E2 改造量最大放最后。
（BIO 线"GWT bus 优先级最高"不冲突：bus 前需先有度量判定"广播是否改变接收者行为"。）

---

## §5 度量与验收总则

| 度量 | 对应判据 | 数据源 | 频率 |
|---|---|---|---|
| M1 广播联动率 | E1 | bus 事件日志 | 每日 |
| M2 自生成比率 | E2 | 做梦器生成 + verify 记录 | 每次生成批 |
| M3 反事实 MAE 增益 | E3 | coupling head 推理 + 真实窗口 | 每周 |
| M4 自纠比例 | E4 | hermes 反思 → 实际修复链路 | 每日 |
| M5 能力-规模曲线 | E5 | metrics 历史 + 记忆/案例计数 | 每日 |
| M7 需求闭环率 | C 类 | 需求单存储 + 主链指标前后对比 | 每需求单 |

> C 类（E-DEMAND）无独立 E 编号判据行——其判据即 §0.4 四条（结构化缺口信号/自动路由/主链指标显著改善/FAIL-OPEN），M7 为其度量载体。

**涌现宣称门禁**（七关全过才可宣称）：对应判据度量显著 + 连续 ≥7 天 + 可复现 + 辩论正反方评审 + **消融归因**（涌现声明 = 总收益 − 脚手架贡献 − 数据红利；**v0.3 落地**：对照实验设计=冻结脚手架（固定接口与数据流、仅自适应部分自由进化）vs 全量运行的双跑对比，随 E2/E6 首个候选事件执行，无对照实验结果则该关自动不通过）+ **OOD walk-forward 隔离**（**v0.4 P0#3 强制点**：案例库入库接口 `evolution-case-ingest` 加 `exclude_out_of_sample_interval` 参数强制拒绝黑名单区间行情；记忆 verify→贝叶斯升级路径 `bayesian_memory_updater.py` 加 `is_in_oos_interval` hook——无强制点则门禁只是自律口号，验收时会被判定为 P0 缺陷）+ **人工/外部复核**（关键宣称的最终判定由人工作出，系统度量只提供证据包，不自评发证）。另设两道上轨护栏：**双度量**（任何能力指标同时报非连续 0/1 与连续口径，两条曲线同向才可申报，Schaeffer 判据 #1）与**稳健性压测**（行情微噪声/案例乱序/发言轮换下决策输出高方差者否决，判据 #7）。单点轶事不算数。

---

## §6 反模式（禁止）

| # | 反模式 | 为什么禁止 |
|---|---|---|
| X1 | 把"某次输出看起来聪明"当涌现 | 轶事不可证伪；必须走度量 |
| X2 | 为出涌现指标而放宽 gate/阈值 | 污染选择压力，指标即刻失效（古德哈特定律）；**v0.4 补充**：全仓 grep 无 ablation gate 实现——E2 前置步骤=新建 gate，阈值定义权属 45-评测系统 |
| X3 | 涌现名义下加黑盒大模块 | 违反 100% 可审计原则（DOMAIN-DISCOVERY X7 同构） |
| X4 | 生产链路直接跑生成策略 | 违反零执行权/REA 决策分离硬约束 |
| X5 | 把规模增长当涌现 | E5 要求的是**相变拐点**，不是线性变好 |
| X6 | 重复调研已证伪方向 | 签名特征已被 β 原型证伪（VM-1793798309647），换方向前先看证伪记录 |
| X7 | 把脚手架收益误报为涌现 | 结构化接口/工程约束的收益是脚手架贡献；MetaGPT 教训（LLM §5.5）：误归因是最常见工程误判 |
| X8 | 无负反馈对冲的强化循环 | 群体智能中导致锁死；交易系统中=策略泡沫自我强化（BIO §6.1 安全阀） |

---

## §7 调研结论（✅ 已回填 v0.2，2026-11-05）

两份报告（全文各 4200/4500 字 + 60+ 来源）：
[RESEARCH-LLM-EMERGENCE-v0.1.md](./research/RESEARCH-LLM-EMERGENCE-v0.1.md) / [RESEARCH-BIO-EMERGENCE-v0.1.md](./research/RESEARCH-BIO-EMERGENCE-v0.1.md)

### 7.1 LLM 线（涌现大辩论 → 工程启示）

- **大辩论共识**：Wei 2022（涌现存在）vs Schaeffer 2023（海市蜃楼：29 个度量 25 个无涌现）→ 后续共识"度量敏感是事实，但非全是假象"——induction head 相变、grokking 有机制级证据
- **核心教训**：涌现极少是"等出来的奇迹"，而是**平滑积累 + 回路组装 + 度量诚实 + 解锁工程**四者齐备时才被合法观测
- **反面教材**：Sparks of AGI（不可复现+利益相关）、数据污染伪造涌现（arXiv:2407.07890）、CAMEL 式多 agent 角色扮演的涌现幻觉（收益来自脚手架非自发智能）
- **已吸收进 SPEC**：双度量+OOD+稳健性三关（§5 门禁）、消融归因（§5）、grokking 长窗口纪律（§4 E2）、记忆读出率（§4 E4 `readout_rate`）、CBR holdout 原语（§4 E5）、walk-forward 防污染（§5）

### 7.2 生物学线（12 项必要条件 → 本系统映射）

- **已具备**（5/12）：多样性组件、选择压力（辩论对抗）、受控漂变（做梦器）、积木雏形（SKILL=积木库/做梦器=重组引擎）、部分聚集链（记忆→簇→SKILL）
- **最关键缺口**：全局广播机制（GWT bus，规划中正对应）+ 临界态监测调控（级联幂律 + σ≈1）
- **可证伪涌现检测器**（BIO §6.1）：级联幂律+σ≈1、整合度代理量（Φ 仅作工程指标，IIT 作为意识理论 2023-2025 遭 124 位学者质疑）、序参量凝结信号——三者同时出现才可宣称系统级涌现
- **安全阀**：正反馈必须有负反馈对冲，否则=策略泡沫自我强化（已吸收为 §6 X8、§4 E2 配平条款）
- **时间尺度分离警示**：反思/进化周期相对交易周期是否足够"慢"需量化——过快蒸馏=过拟合噪声

### 7.3 两线交叉印证（独立得出，高置信）

度量怀疑论 ×2；GWT bus 最重要缺口 ×2；多样性压力 ×2；古德哈特防护 ×2。

### 7.4 评审记录

**第一轮（v0.3，2026-11-05）**：正反方辩论 + 裁判 6 维评分
- 流程：debate-pro-side 正方论证 / debate-con-side Devil's Advocate 反方攻击（8 条）/ debate-adjudication-methodology 终裁
- 评分：**25/30**（逻辑有效性 3/5 最低，其余 4-5）→ 裁决：**修改后接受**，无概念性死罪
- 反方有效攻击（已修 v0.3）：E2 判据定义性循环（→操作化封口）、消融归因空转（→对照实验双跑落地）、E6 静默黑洞（→超时告警+注册流程）、E-BIZ 无基线（→新增 Phase E0）、E5(b) 与 §7.2 自相矛盾（→对齐三件套）、M1/M7 确认偏误（→动作下限+验收分级）、E4 工期低估（→拆期 E4a/E4b）
- 驳回：E6 查表=人工指派（强版本）、E6 驱动 19 违反边界声明

**第二轮（v0.4，2026-11-05）**：架构×数据流双维深度评审（Devil's Advocate）
- 流程：两路独立 Explore 并行检索 + 代码级证据核查 + 裁判抽查 3 关键 artifact
- 裁决：**修改后接受（第二轮），但发现比上轮更硬的 5 项 P0 直接阻断**
- **P0（5 项，已全部封口入 v0.4）**：
  1. E3 前置数据被 artifact 证伪（regime 数字 2760/1534/728 vs SPEC 4074/2832/1349；ckpt 先于修复日）→ E3 补 head 重训前置
  2. §6 X2 守卫的 ablation gate 代码不存在（全仓 grep 仅 48 域自引）→ E2 前置新建 gate
  3. OOD 隔离无强制点（案例库+verify 无黑名单 hook，门禁=自律口号）→ §5 加代码级强制点
  4. E0 主链无回放器 + K 线停滞近 4 个月（现有回测全是子系统；1H K 线止于 07-08 月）→ E0 前置补回放器+K 线回填
  5. readout 断链（记忆已被主链消费但无持久化召回日志，无 joinable 链路）→ E4 补 recall 落盘事件
- **第三轮评审（2026-11-05，六维实证核验，REVIEW-CHECKLIST-v0.1 首跑）**：裁决**修改后接受**——P0×5 中四项实证确认有效，一项（K 线停滞）已被现实追平（数据已回填）；新发现 P1×1（SPEC 状态行过时）+ P2×1（ckpt 日期表述有误），均已修入 v0.5；六维清单有效性经首轮执行验证（捕获 2 处文档-现实偏差）；结论：SPEC 达到可开工状态，剩余真实阻塞仅决策回放器一项
- **P1（已封口 7 项）**：E1 重复建设（bus 已闲置实现）→ 改复用；L0-I 契约受理方错位 → 删错契约；E2 越界 33-REA → §8 补边界；E0 状态误报 → 如实标注；E4a 云端可读无机制 → 复用 git-sync；M2 两做梦器 schema 未统一 → 补统一；M4 反思→修复无 join → 补映射

---

## §8 边界声明（v0.4 扩域）

- C1-C4 认知四层定义权在 35；L0 契约/壳治理权在 46/47；交易策略进化在 23；做梦器（V(π,T) 寻优）在 33-REA（**v0.4 补**：改造 `dreaming.py` 属越界，需经 REA 域协商）；K 线数据采集在 19-数据访问层；GWT bus 真实实现归属 4-MEMORY（`workspace_bus.py`，48 域只接线不复用所有权）
- 本域只做：涌现判据、度量、实验、假设生成机制的**设计与观测**；对既有域代码的引用=只读调研，改写需协商
- 本域不做：改写既有域的 schema/阈值/门禁；生产链路变更；放宽既有既定时（ablation gate / PSI 阈值保持，VM-1793798309647 硬约束）

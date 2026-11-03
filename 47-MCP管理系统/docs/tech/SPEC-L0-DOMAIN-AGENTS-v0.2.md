# SPEC-L0-DOMAIN-AGENTS — L0 域内 agent 化演进蓝图

> **版本**: v0.2 ｜ **日期**: 2026-11-02 ｜ **状态**: 📋 设计草案，待 M1-M4 壳落地后启动
> **v0.2 变更**: 按 2026-11-02 传统金融 AI Agent 训练架构对齐评估报告（下文简称 §评估）补充训练算法层（GRPO/PSI/Beta verify/AlphaPareto/EvolveR）、新增 Phase 0 基座补全、新增 §5.1 H1-H8 硬约束、新增 §6 算力预算。v0.1 六域三档定级 + 壳/agent 分工边界 + Phase A-E 阶段框架不变
> **上游**: [TECH-L0-MCP v0.1](./TECH-L0-MCP-v0.1.md)（壳实现手册）· [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（壳契约）· [评估报告](../../../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-传统金融AI-Agent训练架构对齐评估.md)（训练架构对齐）
> **依赖前置**: SPEC-L0-MCP-PACKAGING v0.3（M1④ 基线测量 → M2-M4 壳上线）
> **定位**: **壳是协议门、agent 是门后自治推理**——两者分离、异步推进
> **依据**: REA 33 已成熟范式（做梦器+反思+PoE+AI Audit+认知集成）；认知 4-MEMORY 已 agent 化（贝叶斯 verify+预测误差门控+蒸馏）
> **约束**: 单人维护、FAIL-OPEN、云端 4C16G、壳与 agent 分离（壳零感知 agent 实现）、写治理红线不突破、**不引入神经网络权重微调**

---

## 1. 命题

### 1.1 Agent 训练 = 三件可拆解的事（§评估 §1.1）

"Agent 变聪明"聚焦为**训练三维度**：

| 训练维度 | 回答什么 | 我们已有的 | 需要补什么 |
|---|---|---|---|
| **学习范式**（Algorithm） | Agent 用什么算法从经验里"学"？ | ✅ 贝叶斯置信度更新 + EWMA 衰减 + 幂律遗忘 + PoE 证据链 | ⚠️ 缺 GRPO 轻量 RL 进化 + Thompson Sampling regime gate |
| **数据底座**（Infrastructure） | Agent "从哪里学"、"学完存哪"？ | ✅ Replay Buffer + 贝叶斯在线学习 S 层 + CUSUM/EWMA 漂移检测 + DynamicDistillEngine | ⚠️ 缺 PSI 漂移监控（小团队友好型，20 行代码）+ Beta 分布完整 verify |
| **治理约束**（Governance） | Agent "学歪了"谁来拦？ | ✅ Mandate 写门控 + FAIL-OPEN + trace_id 全链路 | ⚠️ 缺贝叶斯 VaR 验收（实盘风控域）+ AlphaPareto 六维奖励多目标权衡 |

### 1.2 MCP 壳完成了什么、没完成什么

MCP 壳（本 PLAN M1-M4）**只解决了"对外接口标准化"**：
- ✅ 协议转换（stdio JSON-RPC 2.0）+ 统一信封（10 字段）+ scope 声明 + Mandate 拦截（写治理）+ FAIL-OPEN + trace_id 全链路

**没有解决"域内自治推理能力"**——agent 在壳后自然生长，壳零感知 agent 内部训练/推理/决策。

REA 33 展示了成熟范式：壳只暴露 `rea_analyze / rea_trace / rea_compare` 三个输入输出门，门后是做梦器假设探索 + PoE 证据链 + 反思自批判 + AI Audit + 认知集成——**壳零感知 agent 实现，agent 在壳后自然生长**。

### 1.3 核心约束（H2 已记录）

**不引入神经网络权重微调** — 贝叶斯在线学习 / GRPO 轻量 RL（冻结 LLM 权重，只调策略输出格式）/ 统计检验 / 策略格式调优，是训练算法的**唯一合法区**。SPEC v0.5 明确"不引入深度学习、不修改核心算法逻辑"，本 SPEC 与之对齐。

---

## 2. 壳/agent 分工边界（硬约束）

| 层 | 做什么 | 不做什么 | 约束 |
|---|---|---|---|
| **MCP 壳**（协议层） | 协议转换（stdio JSON-RPC 2.0）+ 统一信封映射 + scope 声明 + Mandate 拦截（写治理）+ FAIL-OPEN + 观测性 trace_id 透传 | 业务逻辑、算法、推理、任何自治行为 | 壳内零业务逻辑，纯转换；所有业务体透传到 envelope.data |
| **域内 agent**（实现层） | 自治推理（贝叶斯/PoE/假设探索/反思）+ 自批判 + 主动沉淀广义认知 + **训练算法迭代**（GRPO/PSI/Beta verify/AlphaPareto/EvolveR）+ 参数调优 | 协议、I/O、传输 | agent 是私有实现，可迭代；壳对 agent 内部**零感知**，只知道"调用 xxx 工具返回 envelope" |

**关键设计**：壳的 `envelope.data` 是 agent 输出的"契约边界"——agent 内部怎么跑（贝叶斯/PoE/做梦器/GRPO/PSI），壳不关心；壳只负责把 agent 的输出用统一信封包好对外暴露。

```
[IDE / DSH / 外部系统]
        │
        │  MCP stdio JSON-RPC
        ▼
┌ MCP 壳 ───────────────────┐
│ (协议转换 + 信封 + scope) │ ← M1-M4 要搭的
└──────────┬────────────────┘
           │ envelope.data（契约边界）
           ▼
┌ 域内 agent ──────────────┐
│ 贝叶斯 / PoE / 做梦器    │ ← 本 SPEC 要设计的
│ 反思 / 自批判 / 沉淀     │
│ GRPO RL / PSI drift      │ ← v0.2 新增训练算法层
│ AlphaPareto / EvolveR    │
└──────────────────────────┘
```

---

## 3. 六域评估（三档定级 + 训练算法细节）

### 3.1 ✅ Recommended（必长 agent，壳搭好即启动）

#### 档一：认知 4-MEMORY — ⭐⭐⭐⭐⭐（**已经是 agent，补训练算法层**）

**现状**：贝叶斯置信度升级（verify）+ 预测误差门控（FOK/JOL harness）+ 蒸馏（DynamicDistillEngine / ConsolidationEngine）+ PoE Evidence Ledger + ReflectionNode 反思回环 + Alpha Decay Gate。**已经在做 agent，只是没叫 "Agent 训练"**。

**壳落地后 agent 增量**（v0.2 新增训练算法细节）：

| 增量 | 训练算法 | 说明 | 壳侧改动 |
|---|---|---|---|
| PSI 漂移监控 | Population Stability Index（§评估 §4.1，20 行 Python） | 分布直方图对比 vs CUSUM，PSI < 0.1 稳定 / 0.1-0.25 轻微 / > 0.25 严重 | 壳只加 `params.enable_psi_drift=true` 透传 |
| Beta 分布完整 verify | verify 从"二项式更新"升级为"Beta(α, β) 完整维护" | 支持部分成功/部分失败（如"10 次调用 7 次成功 3 次超时"） | 零改 |
| 贝叶斯门控参数外部化 | verify 置信度更新阈值 / 蒸馏触发置信度 / 幂律遗忘衰减率 | 壳 params 透传 | 零改 |
| GRPO 轻量 RL 进化（v0.2 新增） | Alpha-R1 GRPO + 市场客观反馈（verify success/failure + 数据漂移 + PoE known_gaps 惩罚） | 冻结 LLM 权重，只调策略输出格式（JSON 字段 reorder / known_gaps 调整） | 零改；agent 内部 loop 每次 record/verify 后跑一轮 |
| EvolveR 自蒸馏闭环（v0.2 新增） | 高评分 PoE 结论 → 蒸馏成"策略原则" → 存入记忆库 → 下次做梦器检索 | 直接复用 DynamicDistillEngine + 记忆库 + recall 三件套 | 零改；调 cognitive record |
| 主动 recall 优化 | 根据调用方角色（researcher/engineer/verifier）调 recall 策略 + PSI 漂移调整排序 | 壳 role scope 声明 → agent 消费 | 壳 role scope 声明 |

**GRPO 奖励函数定义**（AlphaPareto 六维；维度与权重唯一事实源 = TRAIN-BASE v0.1 §3.3，本文只引用不重复定义）：

| 维度 | 分量 | 初版权重（影子期校准见 TRAIN-BASE §6.5） |
|---|---|---|
| 1 | P_verify_success（TB2 Beta mean） | 0.25 |
| 2 | P_recall_hit | 0.20 |
| 3 | psi_stability = 1 − PSI | 0.20 |
| 4 | citation_diversity | 0.15 |
| 5 | process_reward（B2 新增） | 0.12 |
| 6 | transition_smoothness（B2 新增） | 0.08 |

六维权重和 = 1.0；实现以 `training_reward.py`（计划新增）为准，本文不维护第二份权重。PSI 三档与 H5 贝叶斯 VaR 阈值同样纳入 TRAIN-BASE §6.5 校准表。

**PSI 实现（20 行 Python，§评估 §4.1）**：
```python
def psi(expected: list[float], actual: list[float], bins=10) -> float:
    exp_hist = np.histogram(expected, bins=bins, density=True)[0]
    act_hist = np.histogram(actual, bins=bins, density=True)[0]
    exp_hist = np.clip(exp_hist / exp_hist.sum(), 1e-6, None)
    act_hist = np.clip(act_hist / act_hist.sum(), 1e-6, None)
    return float(np.sum((act_hist - exp_hist) * np.log(act_hist / exp_hist)))
# psi < 0.1: 稳定 ｜ 0.1-0.25: 轻微漂移 ｜ > 0.25: 严重漂移
```

**壳零感知**：所有算法迭代在 `4-MEMORY/9-工具与接口/` 内部（`drift_detector.py` 新增 + `cognitive_interfaces.py` 修改 + agent 内部 GRPO loop），壳 `cognitive_mcp_server.py` 的 return 行零改动（信封已包好）。

#### 档二：REA 33 — ⭐⭐⭐⭐⭐（**已成熟 agent，补 regime gate + 自蒸馏**）

**现状**：做梦器（investigation_workflow）+ 反思引擎（core/reflection/）+ PoE（Evidence-First，每条结论带 provenance+confidence+known_gaps）+ AI Audit（ai_audit.py，对 agent 推理过程的外部质量评审）+ 认知集成（cognitive_integration.py）。

**壳落地后 agent 增量**（v0.2 新增训练算法细节）：

| 增量 | 训练算法 | 说明 | 壳侧改动 |
|---|---|---|---|
| Thompson Sampling regime gate（v0.2 新增） |美林时钟四段 = 四个 arm，Thompson Sampling 维持 Beta 分布、regime shift 时重置先验 | 贝叶斯 RL 最简单形式，不用 POMDP 变分推断（§评估 §2.2） | 零改；agent 内部 regime gate |
| AI Audit 自动触发（v0.2 细化） | 逆向完成后自动跑 ai_audit，产出质量评分 → 评分 < 7 触发反思重跑 | SPEC B5 改名"契约评测 vs 业务评测"的业务侧实现 | 壳新增 `submit_*` → `poll_*` 两段式（SPEC §3.2 规划） |
| EvolveR 自蒸馏（v0.2 细化） | AI Audit 高评分结论 → 蒸馏成"策略原则" → 存入 4-MEMORY → 下次做梦器检索 | 自蒸馏 → 原则库 → 在线检索 → RL policy evolution 闭环 | 零改；调 cognitive record |
| 做梦器参数外部化 | 假设数 / 迭代轮次 / PoE 阈值 | 壳 params 透传 | 壳 params 透传 |
| 反思频率自动调优 | 根据逆向类型（架构/追踪/对比）自动选反思策略 + PSI 漂移调整反思强度 | PSI 漂移大 → 反思更严格 | 零改 |

**壳零感知**：`mcp_shells/l0_rea/server.py` 只包 `dsh_nodes.py` 的三个函数，agent 行为在 REA 内部迭代。

#### 档三：评测 45 — ⭐⭐⭐⭐（**待 agent 化，v0.2 补 PSI OOD + 贝叶斯 VaR + AlphaPareto**）

**现状**：SPEC B5 改名"契约评测 vs 业务评测"——契约评测是"跑 benchmark → 报分数"，业务评测需要"跑评测 → 发现漂移 → 定位根因 → 建议 retrain"。后者就是 agent 能力。

**壳落地后 agent 增量**（v0.2 新增训练算法细节）：

| 增量 | 训练算法 | 说明 | 壳侧改动 |
|---|---|---|---|
| PSI OOD 漂移检测（v0.2 新增） | 评测输入集 vs 历史基线的 PSI 值 → PSI > 0.25 触发自动 retrain 建议 | 全域复用 `drift_detector.py`（认知域已有） | 壳薄包，agent 在壳内 |
| AlphaPareto 六维奖励（v0.2 新增） | `Reward = (P_verify_success, P_recall_hit, psi_stability, citation_diversity)` | 沿 Pareto 前沿优化，无需手动权重（§评估 §2.3） | 零改 |
| 贝叶斯 VaR 回测（v0.2 新增） | verify 置信度分布 → Agent 决策 VaR → 置信度 < 0.3 拦截、< 0.5 降为建议 | SR 11-7 对齐（§评估 §2.5） | 零改；agent 内部验收 gate |
| OOD 漂移自动告警 | 测试集分布偏移 → 主动通知沉淀 | PSI 接入后自然实现 | 零改 |
| verify 闭环 | 评测 verdict → cognitive verify（质量评分高 → 升级记忆） | SPEC ALIGNMENT §七 | 调 cognitive verify |

**壳零感知**：壳 `l0_eval/server.py` 只 gateway/runner 薄包，agent 行为在 45 内部迭代。

### 3.2 ⚠️ Caution（可长 agent，但红线必须先画）

#### 档四：语义 39 — ⭐⭐⭐（**write 红线必守**）

**现状**：已区分读写工具（`distill_aliases`/`training_feed` 写 + `query_entity`/`semantic_lookup` 读）。

**壳落地后 agent 增量**（**写路径必须 Mandate 授权**）：

| 增量 | 训练算法 | 说明 | 红线 |
|---|---|---|---|
| 别名蒸馏自举（active learning） | agent 自动提议新别名 → 人类标注确认 → 入库 | 训练算法：主动学习 + 低置信度优先采样 | 自动写严禁，`distill_aliases` 需 Mandate |
| PSI 实体解析质量监控（v0.2 新增） | PSI 漂移检测 → 漂移 > 0.25 告警 | 复用 `drift_detector.py` | 只读 OK |
| 主动知识对齐 | 发现新实体 → 主动触发 2-KNOWLEDGE 入库 | 跨域协同 | 跨域写，Mandate |

**壳侧必须做**：`distill_aliases`/`training_feed` 工具在 registry 标 `requires_mandate: true`，壳内 Mandate 拦截 + 幂等外部 ID。

#### 档五：数据 18/19/20/21 — ⭐⭐（**实盘红线必守，只长只读 agent**）

**现状**：C5 收编已把数据直连收进 port；19-DAL 四后端 + sink 双写。

**壳落地后 agent 增量**（**只读 OK，写严禁**）：

| 增量 | 训练算法 | 说明 | 红线 |
|---|---|---|---|
| PSI 数据质量漂移监控（v0.2 新增） | 数据质量漂移 → 自动告警 | 复用 `drift_detector.py` | 只读分析 OK，严禁自动修复 |
| 采集调度优化建议 | 根据历史成功率 + PSI 漂移调采集间隔 | 建议 OK，执行需人工 | 建议 OK |
| 与认知 recall 联动 | 数据异常 → 主动 recall 历史处理经验 | 跨域协同 | 只读 OK |

**严禁**：任何自动修复/补全/写回数据仓库的 agent 行为（触 11/yijing/v15 实盘风控红线）。

### 3.3 🚫 Forbidden（不该长 agent）

#### 档六：检索 41+Chroma — ⭐（**门面不该加 agent**）

**理由**：
- unified_search 本质是"路由门面"（C7 三后端分发，min-max 归一化 + 去重 + 分层返回）
- 加 agent 会让检索路径变不可预测（实时系统最怕延迟抖动 + 结果不确定）
- REA/认知的 agent 结论**走检索沉淀**（结论存知识库 → 检索可命中），但检索本身不应是 agent

**壳侧该做什么**：壳只做 scope 声明 + 延迟 SLO 保证（SPEC §3.8 D4：P50 不劣化），不做任何 agent 化改动。

---

## 4. 实施路线（v0.2 新增 Phase 0 基座补全）

### 4.1 总体路线图

```
现在 ──────────── M1 壳基础 ───── M2 数据/评测壳 ───── M3 REA/认知双模 ───── M4 库管 ────── bcrm2 切流
  │                                                                                        │
  │  MCP 壳 M1-M4 并行推进（当前主线）                                                      │  bcrm2 切流后
  │  ① registry → ② 能力集 → ③ 信封 → ④ 基线 → ⑤ B3 DAL → ⑥ 数据壳 → ⑦ 评测壳 → ⑧ REA壳 → ⑨ 双模 → ⑩ shadow → ⑪ 库管 → ⑫ bulk-read
  │                                                                                        │
  │  ┌─────────────────────────────────────────────────────────────────────────────┐       │
  │  │  Phase 0 训练基座补全（壳搭建期间并行推进，1-2 周）                            │       │
  │  │  ─────────────────────────────────────────────────────────────────────────── │       │
  │  │  PSI drift_detector.py（20 行，全域复用）                                      │       │
  │  │  Beta 分布 verify 升级（`cognitive_interfaces.py`）                            │       │
  │  │  AlphaPareto 六维奖励定义（认知/评测共用）                                     │       │
  │  │  GRPO 轻量 RL loop 原型（冻结权重，只调输出格式）                              │       │
  │  │  Thompson Sampling regime gate 原型                                           │       │
  │  └─────────────────────────────────────────────────────────────────────────────┘       │
  │                                                                                        │
  │  ────── 以下为壳完成后启动 ──────                                                       │
  │                                                                                        │
  │  Phase A：认知 agent 参数外部化 + GRPO + Beta verify                                  │
  │  Phase B：REA agent AI Audit 自动触发 + Thompson Sampling + EvolveR                   │
  │  Phase C：评测 agent OOD + PSI + AlphaPareto + 贝叶斯 VaR + verify 闭环                │
  │  Phase D：语义 agent（Mandate 写门控 + PSI 漂移监控）                                  │
  │  Phase E：数据 agent（只 read-only + PSI 漂移接入）                                    │
  │  ⛔  检索 agent：禁止                                                                  │
```

### 4.2 Phase 0 基座补全（v0.2 新增，壳搭建期间并行）

| 任务 | 位置 | 代码量 | 算力 | 前置 |
|---|---|---|---|---|
| PSI drift_detector.py | `4-MEMORY/9-工具与接口/` 新增 | ~50 行 | 零 GPU，O(N) 毫秒级 | 无 |
| Beta 分布 verify 升级 | `cognitive_interfaces.py` 修改 | ~80 行 | 零 GPU，O(1) 纳秒级 | 无 |
| AlphaPareto 六维奖励定义 | agent 内部常量文件 | ~20 行 | 零 GPU，O(1) | 无 |
| GRPO 轻量 RL loop 原型 | agent 内部 loop | ~150 行 | 零 GPU，冻结权重，秒级/轮 | Beta verify + AlphaPareto |
| Thompson Sampling regime gate 原型 | `40-周期神经网络` 接入 | ~60 行 | 零 GPU，O(K) 微秒级 | PSI drift_detector |

### 4.3 Phase A-E 依赖壳层能力

| Phase | 依赖壳层能力 | M1-M4 哪个任务已提供 |
|---|---|---|
| A 认知 agent 参数化 + GRPO | shell 级参数透传 + envelope.data 业务体透传 | M1③ 信封已支持 |
| B REA agent AI Audit + EvolveR | MCP 壳可触发异步子流程（job 完成事件） | M1③ + M3⑧ REA 壳 |
| C 评测 agent OOD + VaR + 闭环 | 评测 verdict → cognitive verify 链 + Mandate 授权 | M1② 能力集 verifier 角色 + M2⑦ 评测壳 |
| D 语义 agent 自举 | Mandate 写门控 + 幂等外部 ID | M1① registry 已标 requires_mandate + M3 写治理 |
| E 数据 agent 分析 | 数据壳只读工具面稳定 | M2⑥ 数据壳（只读先行） |

### 4.4 Phase B Dream-RSI V 函数 alpha 分量（2026-11-03 三问评估补）

> 来源：三问评估 "通信层不能只优化结构指标，必须有实盘价值维度"
> 与 TRAIN-BASE TB3 第七维 `pnl_delta_score` 对齐，REA 做梦器 V(π, T) 同步升级

**原 V 函数**（只含结构指标）：
```
V(π, T) = hypervolume(质量-成本点集, λ=0.1) - 0.1 × 并行度惩罚
         + 0.1 × cross_domain_refs 加成
```

**升级后 V 函数**（结构 + alpha 双分量）：
```
V_new(π, T) = V(π, T)                                          # 原有结构指标（保持不变）
             + α × mean([
                 h.prediction.expected_delta.pnl_delta_pct
                 for h in T.hypotheses
                 if h.status == "validated"
               ])
```

**参数**：
- α 默认 0.1（小权重，防止 alpha 分量覆盖结构优化——结构稳定性是通信层的基础，不能牺牲）
- 只有 status="validated" 的 P4 验证回执 hypothesis 才吸收进 Dream-RSI
- status="partially_valid" → 0.5 权重吸收；status="rejected" → 不吸收
- **无 P4 回执时**（沙箱未启动）：V_new = V（退化兼容，零影响）

**与 COMM-SHADOW 闭环**：AgentMail observe() 消费 L1 DomainCouplingHead 推理的 cross_domain_coupling → 生成 P3 叠加印证假设 → 跨域组合验证沙箱跑反事实评估 → P4 验证回执 → 被 REA 做梦器吸收 → Dream-RSI 选最优策略 → 域内 agent 执行

---

## 5. 治理与验收

### 5.1 Agent 训练硬约束 H1-H8（v0.2 新增，已记录 B 级认知 VM-1793614210293-5a6aa862）

| # | 约束 | 类型 | 验证点 |
|---|---|---|---|
| **H1** | 训练算法迭代**必须**在壳后域内实现，壳 `envelope.data` schema **零变化**，壳**零感知** agent 内部训练行为 | 硬 | agent 迭代期间 `mcp_shells/` diff = 0 |
| **H2** | **不得**引入神经网络权重微调 — 贝叶斯在线学习 / GRPO 轻量 RL（冻结 LLM 权重）/ 统计检验 / 策略格式调优是训练算法**唯一合法区** | 硬 | agent 代码扫描无 `.train()` / `.backward()` / 梯度下降 |
| **H3** | 每次训练迭代**必须**产出 `trace_id` + `receipt_hash` + PoE evidence，可事后审计 | 硬 | 每次 GRPO/PSI/Beta verify 产出 receipt_hash 落 CognitiveLoopEntry |
| **H4** | GRPO RL loop **默认** FAIL-OPEN，单轮迭代失败**不得**阻塞主流程，策略输出格式自动回退上一稳定版本（**agent 内部 loop 降级，壳层不受此影响；壳层主功能禁止 FAIL-OPEN 由 PACKAGING B1 约束**） | 硬 | agent GRPO loop try/except + 上一版本 checkpoint 自动回退 |
| **H5** | 实盘风控域（11/yijing/v15/止损）agent 训练输出**必须**过贝叶斯 VaR 验收 — 置信度 < 0.3 **自动拦截**、< 0.5 **降为建议** | 硬 | 贝叶斯 VaR 回测 gate 硬编码，不可运行时关闭 |
| **H6** | 数据域 agent 训练**只允许** read-only 输出 — 任何自动修复/补全/写回数据仓库行为**禁止** | 硬 | 数据壳只读工具面硬门禁，`requires_mandate=true` 写工具不暴露给 agent |
| **H7** | 语义域 agent 训练写路径**必须**过 Mandate 授权 — `distill_aliases` / `training_feed` 等 `requires_mandate=true` 是硬门禁 | 硬 | registry schema 静态校验 + 壳运行时 Mandate 拦截双门禁 |
| **H8** | PSI 漂移监控阈值**硬编码** — < 0.1 稳定 / 0.1-0.25 轻微漂移 / > 0.25 严重漂移，**不得**运行时动态调 | 硬 | `drift_detector.py` 阈值硬编码，无 env override |
| **H9** | AgentMail 跨域通信升级**必须**先过影子验证（COMM-SHADOW SPEC）— 影子 S1: **绝不触发** agent 实际行为；影子 S2: trace_id **必须**前缀 `shadow-`；影子 S3: 影子模式**零资源开销**（不新增 DB/进程/网络连接） | 硬 | COMM-SHADOW observe() 代码静态分析 + 影子报告生成逻辑审查 + 资源监控 |

### 5.2 一般治理项

| 治理项 | 规则 |
|---|---|
| agent 行为可观测 | agent 每次推理决策必须 trace_id 透传 + 结构化日志落 event_emitter |
| agent 写治理 | 所有 agent 写路径必须 `shell.requires_mandate=true` + Mandate 授权 + 幂等 external_id |
| agent 迭代零回归 | agent 算法迭代 → envelope.data schema 零变化（壳契约稳定，H1） |
| agent 不可绕过壳 | 严禁 agent 直接 import port adapter（壳是唯一出口） |
| agent 红线突破 = 回滚 | 实盘风控域任何 agent 行为（数据自动写、交易自动决策）= 硬门禁 |

### 5.3 验收标准（含 v0.2 新增训练算法验收）

| 阶段 | 验收项 | 判据 |
|---|---|---|
| **Phase 0** | PSI 实现 + Beta verify + AlphaPareto + GRPO 原型 | ✅ PSI 单测覆盖（稳定/轻微漂移/严重漂移三档）✅ verify Beta 分布更新单测 ✅ GRPO loop 一次迭代 P50 < 50ms |
| **Phase A** | 认知 verify 闭环 + PSI + GRPO | 同类事件 recall 命中率 ↑ 15%（A8 校验）；PSI > 0.25 自动告警 |
| **Phase B** | REA AI Audit + EvolveR | AI Audit 自动评分，评分 < 7 触发反思重跑，重跑后评分 ≥ 7/10 |
| **Phase C** | 评测 PSI + VaR + verify 闭环 | PSI > 0.25 告警 → 建议 retrain → 人工确认 → 漂移消除比例 ≥ 80%；贝叶斯 VaR 置信度 < 0.3 拦截率 100% |
| **Phase D** | 语义 Mandate + PSI | 别名蒸馏人类确认通过率 ≥ 60%；PSI > 0.25 告警 P50 < 10min |
| **Phase E** | 数据 PSI + 只读 | 数据质量漂移告警 P50 < 10min；零自动修复行为 |
| **跨阶段** | agent 迭代壳零改 | agent 算法迭代期间 envelope schema 零变化（diff 只在壳后，H1） |

---

## 6. 算力预算（v0.2 新增，单服务器零 GPU 全环节可跑）

**约束**：云端 4C16G + macOS M3 本地，**零 GPU**（除非后续购置）

| 训练环节 | 算力需求 | 实现方式 | 代码位置 |
|---|---|---|---|
| PSI 漂移监控 | O(N) 直方图对比，毫秒级 | Python 原生 numpy，零依赖 | `4-MEMORY/9-工具与接口/drift_detector.py` |
| Beta 分布 verify 升级 | O(1) 分布更新，纳秒级 | `math.beta_inv` 函数，零依赖 | `cognitive_interfaces.py` |
| AlphaPareto 六维奖励 | O(1) 向量计算 | Python 原生 tuple | agent 内部常量文件 |
| GRPO 轻量 RL loop | O(K) K=策略数 × 迭代次数，秒级 | 冻结 LLM 权重，只调策略输出格式（JSON 字段 reorder / known_gaps 调整） | agent 内部 loop |
| 贝叶斯 VaR 回测 | O(N) verify 历史 × 正态分布 CDF | `scipy.stats.norm.cdf`，秒级 | 45 验收 gate |
| Thompson Sampling | O(K) Beta 分布采样，微秒级 | `random.betavariate`，零依赖 | 40-周期神经网络接入 |
| EvolveR 自蒸馏 | 等价 DynamicDistillEngine ✅ 已落地 | 现有蒸馏引擎 | `cognitive_loop_entry.py` |

**结论**：零 GPU、单 CPU 4C16G 全环节可跑。所有训练算法都是"贝叶斯 + 统计检验 + 策略格式调优"，不涉及梯度下降/神经网络权重更新。

> **代码落点状态（P6 复核，2026-11-03）**：`drift_detector.py` / `training_reward.py` / `regime_gate.py` / `grpo_evolution.py` 均为**计划新增**——实测 `4-MEMORY/9-工具与接口/` 下仅存在 `cognitive_loop_entry.py` / `cognitive_interfaces.py`。本 v0.2 只定义契约，不代表已落地。

---

## 7. 附录：agent 化 vs MCP 壳 职责分离矩阵（v0.2 更新）

| 维度 | MCP 壳 | 域内 agent |
|---|---|---|
| 协议 | ✅ JSON-RPC 2.0 | ❌ 不涉及 |
| 信封 | ✅ 统一信封映射 | ❌ 不感知，只产业务体 |
| scope 声明 | ✅ registry scope | ❌ 不感知 |
| Mandate 拦截 | ✅ 写治理 | ❌ 依赖壳拦截后才能写 |
| FAIL-OPEN | ✅ 壳层降级策略 | ✅ agent 内部有自己的降级策略 |
| 贝叶斯推理 | ❌ | ✅ verify Beta 分布更新 |
| PoE 证据链 | ❌ | ✅ Evidence-First |
| 做梦器假设探索 | ❌ | ✅ REA investigation_workflow |
| 反思自批判 | ❌ | ✅ REA reflection + L4 ReflectionNode |
| PSI 漂移监控 | ❌ | ✅ drift_detector.py（v0.2 引入，计划新增） |
| GRPO 轻量 RL 进化 | ❌ | ✅ 冻结权重，调策略格式（v0.2 新增） |
| Thompson Sampling regime gate | ❌ | ✅ 美林时钟四段 arm（v0.2 新增） |
| AlphaPareto 六维奖励 | ❌ | ✅ verify_success / recall_hit / psi_stability / citation_diversity / process_reward / transition_smoothness（v0.2 新增） |
| EvolveR 自蒸馏闭环 | ❌ | ✅ 蒸馏 → 原则库 → 检索 → RL 进化（v0.2 新增） |
| 贝叶斯 VaR 回测 | ❌ | ✅ SR 11-7 对齐（v0.2 新增） |
| 主动沉淀广义认知 | ❌ | ✅ REA cognitive_integration |
| 观测 trace_id | ✅ 透传 | ✅ 消费+生成 |
| 写路径治理 | ✅ Mandate + 幂等 | ✅ 必须先过壳，否则严禁 |

---

## 附录 B：参考论文（v0.2 新增，来自 §评估）

| 编号 | 论文 | 我们的映射 |
|---|---|---|
| 1 | Alpha-R1 (arXiv 2512.23515) GRPO + 市场反馈 RLHF | GRPO 奖励函数接 verify 评分 |
| 2 | EvolveR (arXiv 2510.16079) 自蒸馏→原则库→检索→RL | 直接映射记忆库 + 蒸馏引擎 |
| 3 | AlphaPareto (arXiv 2609.34188) 六维向量奖励 + MAP | 六维奖励定义 |
| 4 | ADTS（**arXiv 编号待验证**）Thompson Sampling regime gate | 美林时钟四段 arm |
| 5 | DeepSeek Super-agent (dsh-superagent-prototype) | 架构对标 |
| 6 | ACT-R 激活-延迟-效用 | recall 排序升级参考 |
| 7 | Friston 预测编码自由能原理 | 预测误差门控理论基础 |
| 8 | EU AI Act 2026.8 | 合规框架 |
| 9 | MAS SAFR Agent 运行时治理 | Safeguard + Filter + Audit + Recourse 四件套 |
| 10 | SR 11-7 贝叶斯 VaR 回测 | 实盘风控验收 |

> **引用核验声明（P4 修订，2026-11-03）**：1-3 的 arXiv 编号已本地联网复核并更正（原 2507/2505/2504 有误）；SR 11-7 为美联储监管指引（非论文）；4 的 ADTS 未检索到对应论文，标注待验证；其余条目为内部评估报告引用，未逐条核对。

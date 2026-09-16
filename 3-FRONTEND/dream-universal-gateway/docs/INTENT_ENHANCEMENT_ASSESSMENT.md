# 意图识别管线增强 — 三方向分层评估报告

> 版本: v1.0 | 日期: 2026-08-29 | 所属: Dream Universal Gateway
> 调研方法: D-Z-E 三链（D 调研 → Z 规划 → E 执行）
> 前置提案: PROP-20260828B（统一意图引擎 FC 化）、PROP-20260829C（边界与门禁，已批准）
> 评估对象: ① 知识库接入（knowledge-rag）② 认知系统接入（cognitive-adapter）③ 本地训练模型

---

## 1. 概述与现状基线

本报告评估意图识别管线（`recognizeIntentUnified` 单入口）的三个增强方向，输出四维评估矩阵（成本/收益/风险/优先级）与分层路线图（P0 快赢 → P1 验证 → P2 长期）。

### 1.1 管线现状（5 级）

| 级 | 层 | 机制 | 文件 |
|:---:|:---|:---|:---|
| ⓪ | 追问检测 | `detectFollowUp` 零 LLM | fallback-engine.ts L224 |
| ① | 命令快路径 | `matchCommandFastpath` 零 LLM | command-fastpath.ts L43 |
| ② | FC 结构化识别 | `callLLM` + FC_TOOL（35 canonical） | intent-unified.ts |
| ③ | 规则引擎兜底 | 硬编码规则 + intent-memory 经验库 | fallback-engine.ts |
| ④ | 默认兜底 | simple_qa 0.4 | fallback-engine.ts |

### 1.2 识别基线（intent-scenario-eval.ts，26 场景，2026-08-29）

| 指标 | 值 |
|:---|:---|
| 严格命中率 | 84.6%（22/26） |
| 宽容命中率 | 96.2%（25/26） |
| 崩溃数 | 0 |
| 实体提取 | 100% |
| 已知缺口 | ① S17/S18（`/行情` `/分析` 漏判）② S26（「继续」追问漏判） |

**关键事实：两个缺口均在「零 LLM 层」，与「训练模型」（针对 FC LLM 层）是正交优化目标。**

---

## 2. 三方向四维评估矩阵

### 2.1 方向① 知识库接入（knowledge-rag.ts，784 行，已就绪未接入）

| 维度 | 评估 |
|:---|:---|
| 成本 | 开发**低**（模块已就绪，接线 1-2 处）；运行**中**（DeepSeek embeddings 增量缓存，非每请求） |
| 收益 | 识别阶段 **≈0**（RAG 服务「回答」非「路由」）；下游分析增强**高**（deep_analysis/scenario_sim 知识支撑） |
| 风险 | 低-中：embedding 失败有 n-gram 回退不阻塞；知识片段进 prompt 需防注入 |
| 优先级 | **P2**（与识别解耦，独立推进） |

**结论**：RAG 的核心价值在「回答/分析」阶段，不在「意图分类」阶段。接入点应在识别之后的下游，而非识别内部。对准确率无贡献，对分析质量有贡献。

### 2.2 方向② 认知系统接入（cognitive-adapter.ts，593 行，已就绪未接入）

| 维度 | 评估 |
|:---|:---|
| 成本 | 开发**低-中**（模块就绪，但关键词检索需升级为可用消歧信号）；运行**零 token**（纯本地文件） |
| 收益 | **中**：模糊意图消歧（历史案例注入 FC prompt 提置信度）；需与 intent-memory 划清边界（两套机制） |
| 风险 | **低**：纯本地零依赖；主风险 = prompt 膨胀致 FC 输出漂移 |
| 优先级 | **P1**（模糊场景跑 eval 对比后决定去留） |

**结论**：唯一对「识别精度」有正向价值的接入方向（模糊消歧），但需先验证净收益。注意：`intent-memory.ts` 的 `recordRecognition` 已独立承担「意图经验」记录，与认知系统是两套机制，接入时必须划清边界，避免重复注入。

### 2.3 方向③ 本地训练模型（无实体，全新方向）

| 维度 | 评估 |
|:---|:---|
| 成本 | 开发**高**（TF-IDF+朴素贝叶斯/逻辑回归 + 训练集/评估集 + 上线开关）；运行**负成本**（省 FC LLM：~2s+~95token → 毫秒+零 token） |
| 收益 | **高**：高频意图本地推断，33 意图对高频可达 LLM 90%+；但边缘/对抗鲁棒性弱于 LLM |
| 风险 | **高**：冷启动数据不足、分类器漂移、对抗样本鲁棒性下降；须 hybrid（本地推断 + 置信度阈值 + LLM 兜底） |
| 优先级 | **P2 长期**（先跑通 intent-memory 数据闭环再训练） |

**结论**：唯一能同时优化「成本 + 延迟」的方向，但重投入、高风险。可行路线符合项目「零重型依赖、纯 TS」哲学（knowledge-rag 明示不用 numpy/faiss）：TF-IDF + 朴素贝叶斯轻量分类器跑在 Node 运行时。训练数据源已存在（intent-memory 累积识别样本），但需冷启动 + 质量清洗。

---

## 3. 优先级结论（一句话）

> **先修零 LLM 层的两个缺口（精度，廉价），再验证认知消歧（净收益），最后上训练模型（成本）+ 知识库（下游增强）。**

| 优先级 | 方向 | 目标 | 性质 |
|:---:|:---|:---|:---|
| **P0** | 缺口修复（零 LLM 层） | 精度 84.6% → ~92% | 精度 |
| **P1** | 认知系统接入 | 模糊意图消歧 | 精度 |
| **P2** | 训练模型 | 成本 + 延迟 | 成本/延迟 |
| **P2** | 知识库接入 | 下游分析增强 | 回答质量 |

---

## 4. 分层路线图

### P0 快赢（1-2 天，零模型零 token）

两个缺口均为**一行修复**，且路由层（`COMMAND_ROUTE_MAP`）早已就绪。详见配套提案 `PROP-20260829E`。

| 缺口 | 文件 | 修复 | 预期效果 |
|:---|:---|:---|:---|
| ① S17/S18 | command-fastpath.ts L13 | CMD_RE 扩展 CJK 支持 | `/行情` `/分析` 命中快路径 |
| ② S26 | fallback-engine.ts L228 | followUpWords 补「继续」等 | 「继续」追问延续上轮意图 |

**验收**：重跑 `npx tsx scripts/intent-scenario-eval.ts`，严格命中率 84.6% → 预期 ~92%。

### P1 验证（1 周，轻量）

- 方向② 接入：FC call 前调 `retrieveMemoryContext` 注入（仅模糊意图），跑 eval 对比
- 数据闭环：确认 intent-memory 记录质量，为 P2 训练集铺路
- **验收**：模糊场景（S19/S20）准确率或置信度有净提升才保留；无净收益则回退

### P2 长期（2-4 周，重投入）

- 方向③ 训练模型：TF-IDF + 朴素贝叶斯 hybrid（本地推断 + 置信度 <0.7 回退 FC LLM）
- 方向① 知识库：`buildRAGContext` 注入 deep_analysis 响应（下游增强，与识别解耦）

---

## 5. 源码锚点

| 模块 | 路径 | 关键导出 |
|:---|:---|:---|
| 统一入口 | `src/lib/intent/intent-unified.ts` | `recognizeIntentUnified` |
| 命令快路径 | `src/lib/intent/command-fastpath.ts` | `matchCommandFastpath`（CMD_RE L13 / CN_COMMANDS L16） |
| 规则引擎 | `src/lib/intent/fallback-engine.ts` | `detectFollowUp`（followUpWords L228） |
| 路由 | `src/lib/intent/smart-router.ts` | `COMMAND_ROUTE_MAP`（已含 `/行情` `/分析`，L249/252） |
| 知识库 | `src/lib/knowledge-rag.ts` | `retrieveRelevantChunks` / `buildRAGContext` |
| 认知适配 | `src/lib/cognitive-adapter.ts` | `retrieveMemoryContext` / `formatMemoryContext` |
| 评估脚本 | `scripts/intent-scenario-eval.ts` | 26 场景基准 |

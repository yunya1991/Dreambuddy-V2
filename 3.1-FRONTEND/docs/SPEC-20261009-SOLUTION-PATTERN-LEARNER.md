# SPEC-20261009 — 解题模式学习器（SolutionPatternLearner）

> **版本**: v0.4.1
> **日期**: 2026-10-09
> **作者**: Trae + User
> **状态**: Draft（评审通过 → 转入 implementation）
> **方法论**: recall → 三轮调研 → SPEC v0.1 → 全链路蒸馏深化 → SPEC v0.2 → 同行评审(4角色+7模式) → SPEC v0.3
> **v0.2 变更**: Case Bank → TDR；新增 5 个层专属训练器；新增 Baseline 采集 + 评估层
> **v0.3 变更**: ①session_memory 四元组对齐实际格式(intent,actions,outcome,learned)；②删除不可验证引用(iCLP/STAR)改用 VQ-VAE 原论文；③VQ-VAE 轻量方案论证(k-means+++EMA公式)；④复现/超越标准改可度量指标(语义一致率)；⑤各层桶满阈值差异化；⑥验收阈值降级为待验证目标；⑦增加 TDR 容量规划；⑧修复质量闸门矛盾
> **v0.4 变更**: 新增§11交叉验证层——集成矛盾论+Transformer架构的域无关交叉验证框架，从"模仿"升级为"矛盾感知自进化"
> **v0.4.1 变更**: 同行评审勘误7项——Major:①Granger→TDR方法论降级声明(代理非等价);②_dimToLayers标注初始映射+校准方法;③V22降级为探索性指标+Cohen'sκ标注协议。Minor:④KL散度阈值设定方法;⑤V24未覆盖样本处理策略;⑥层权重floor/ceiling约束[0.5,2.0];⑦交叉验证层超越度量指标(重训练解决率vs基线)

---

## 0. Executive Summary

### 0.1 核心命题

前端应用系统从 Trae Code 工作过程的认知沉淀中**学习解题模式**，通过专门的算法模型（SolutionPatternLearner, SPL）进行**实时增量训练**，最终实现对前端全链路的**训练蒸馏**——让每一层（S层意图识别 / DSH执行 / C层反射决策 / G层图结构 / LLM兜底）都能独立训练，达到"复现"甚至"超越" Trae Code 能力。

**v0.1 → v0.2 核心进化**：

| 维度 | v0.1 (Case Bank) | v0.2 (全链路蒸馏) |
|------|------------------|------------------|
| 定位 | 案例检索辅助器 | 中央训练数据仓库 + 5个层专属训练器 |
| Case Bank | 检索相似案例注入上下文 | 升级为 TDR，按层标注分发训练数据 |
| 目标 | 辅助路径B执行更准 | 各层独立训练，复现并超越 Trae Code |
| 训练对象 | 无（只检索不训练） | S层/C层/G层/DSH/LLM兜底 各有专属训练循环 |

**与现有 ImitationCounter 的关系**：ImitationCounter 是频率驱动（同类 query 重复 3 次→触发沉淀），SPL 是模式驱动 + 全链路训练。SPL 不替代 ImitationCounter，而是作为其上层增强——频率计数保留作为兜底，SPL 提供更精准的模式匹配和分层训练。

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | 使用频繁，需要实时训练而非批量离线 | 用户确认 |
| F2 | 要有专门的算法模型 | 用户确认 |
| F3 | 采用方案 2（CBR 式解题模式学习）| 用户确认 |
| F4 | 复用已有四系统基础设施（认知/RAG/索引/SKILL）| 架构约束 |
| F5 | Trae Code 沉淀目前前端不可访问（B 类沉淀未打通）| 调研发现 |
| F6 | **全链路训练蒸馏：S层+DreamOS(C/G层)+DSH+子节点能力，实现复现甚至超越 Trae Code** | 用户确认 (v0.2) |

### 0.3 范围边界

- ✓ SPL 算法模型设计（TDR + VQ-VAE编码 + 漂移检测 + 5个层专属训练器）
- ✓ Trae Code 记忆桥接（session_memory/topics/project_memory → TDR）
- ✓ 5个层专属 TrainingLoop（S层/DSH/C层/G层/LLM兜底）
- ✓ Baseline 采集系统（Trae Code 输出基线）
- ✓ 评估层（各层 vs Trae Code baseline，复现/超越标准）
- ✓ 与 CognitiveContextBuilder 集成（TDR 检索作为第 5 系统接入）
- ✓ 路径 B 模仿增强（文档检索 → 案例检索 + 文档检索）
- ✓ 交叉验证层（CrossValidationGate for SPL：过去TDR vs 现在query → 一致/分歧/质变 → 自进化闭环）
- ✓ SPL 解题范式维度分类（code-driven / AI-driven / hybrid / lookup / research）
- ✓ 质变→重训练 闭环连接器（质变事件触发 TDR 重训练 + 新基线建立）
- ✗ 不修改 ImitationCounter 既有逻辑（SPL 作为上层调用，计数器保留兜底）
- ✗ 不修改认知系统 4-MEMORY 后端（只通过 cognitive-client.ts 接入层访问）
- ✗ 不做 LLM 权重微调（SPL 是非参数化 CBR + 轻量在线学习 + 规则蒸馏，不动 LLM 权重）

---

## 1. 调研结论（事实清单）

### 1.1 前端链路现状

| 组件 | 路径 | 现状 |
|------|------|------|
| 意图识别 | `src/types/index.ts` L34-L80 | IntentType/RoutingDecision 已定义 |
| 编排执行 | `src/lib/skill-orchestration-executor.ts` | 完整链路：CTX build → SkillSelector → DSH → C-Drive → Summary |
| 认知上下文 | `src/lib/cognitive-context-builder.ts` | 四系统并行（recall+RAG+索引+SKILL），2s 超时，FAIL-OPEN |
| 认知客户端 | `src/lib/cognitive-client.ts` | 子进程调 cognitive_adapter.py，10s 超时 |
| 模仿计数 | `src/lib/imitation-counter.ts` | 归一化 pattern + 计数 + 阈值 3 → skill-creator |
| 路径 B | skill-orchestration-executor.ts L223-L333 | 文档检索 → LLM 转计划 → DSH 执行 → 计数 |
| 路径 C | skill-orchestration-executor.ts L335+ | 联网兜底 dream-research-workflow |
| 用户记忆 | `src/lib/user-memory-client.ts` | 物理隔离 user_memory.db，存偏好/笔记 |
| C层反射 | DreamOS C层 `reflector.py` | 5种决策规则化（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/TERMINATE），无 ML |
| G层图存储 | DreamOS G层 `graph_store/` | 快照式 ckpt_*.json + BAC 三层压缩，静态存储 |

### 1.2 Trae Code 沉淀格式（B 类，前端未打通）

> **v0.3 修正**：经实际文件验证（`~/.trae-cn/memory/projects/` 下的 session_memory_*.jsonl），确认实际字段为 6 个：`intent, actions, outcome, learned, message_summary_time, message_id`。v0.2 声称的 `analysis, solution, token_usage, latency` 字段 **不存在于实际数据中**，v0.3 已全部对齐。

| 文件 | 格式 | 实际字段 | 可训练的层 |
|------|------|----------|------------|
| session_memory_*.jsonl | JSON Lines | `intent`(string), `actions`(string[]), `outcome`(string), `learned`(string[]), `message_summary_time`(string), `message_id`(string) | S层(intent→分类) / DSH(actions序列) / C层(ctx→outcome) / LLM(learned→模式) |
| topics.md | Markdown | [session_id: xxx | topic_summary_time] + 摘要 | G层(决策→图结构) |
| project_memory.md | Markdown | 结构化规则/约束/决策 | G层(规则→图) / C层(约束→决策) |
| user_profile.md | Markdown | 沟通偏好/背景/技术栈/工作流 | user_memory.db（不自动提升为VM） |

**实际数据样例**：
```json
{"intent":"整体上检查下项目架构逻辑","actions":["检查项目架构逻辑","修复架构中的严重问题","修复架构中的中等问题","修复架构中的轻微问题","进行架构验证测试"],"outcome":"项目架构检查与修复完成，核心架构已修复并通过验证","learned":["架构层次自洽","BCRMEngine.infer()包含七个步骤","修复了8项问题","6项验证测试全部通过"],"message_summary_time":"2026-07-06 00:25:08","message_id":"6a4a82041788dd06ff269942"}
```

**缺失字段影响**：`token_usage` 和 `latency` 不存在 → "超越"标准中 Token/延迟相关指标改用替代度量（见 Section 4.5）

### 1.3 认知系统存储

| 组件 | 路径 | 格式 | 向量化 |
|------|------|------|--------|
| cognitive_memory.db | `4-MEMORY/data/` | SQLite: memories 表（content/vector/quality_level/confidence/tags） | n-gram + md5 哈希投影 |
| RAG 知识库 | `2-KNOWLEDGE/9-RAG-INFRA/` | ChromaDB: dreambuddy_knowledge 集合 | bge-small-zh-v1.5, 512 维, cosine |
| memory_bridge | `2-KNOWLEDGE/9-RAG-INFRA/bridge/memory_bridge.py` | RAG 检索结果 → cognitive_memory.db (C 级) | 双向桥接 |

### 1.4 算法调研结论

| 方向 | 选型 | 来源 | 选型理由 |
|------|------|------|----------|
| CBR 在线学习 | Memento 架构（非参数 Case Bank + Soft Q-Learning）| arXiv:2508.16153 (UCL+华为, 2025.08) **已验证** | 无需梯度更新 LLM，低成本低延迟，与 CBR 天然契合 |
| 解题模式编码 | VQ-VAE 离散 codebook | van den Oord et al., "Neural Discrete Representation Learning", NeurIPS 2017 **经典论文** | 四元组→离散码本，紧凑可索引，比纯 embedding 更可复用 |
| 模仿+反思 | Agent-R MCTS 纠错 | arXiv:2501.11425 (复旦+字节, 2025.01) **已验证** | 失败轨迹→修正样本，及时反思而非终态修正 |
| 在线增量 | 漂移检测 + EMA 更新 | KL 散度 + 指数移动平均（标准技术）| 检测分布漂移触发，非每轮训练，避免计算浪费 |
| 分层训练蒸馏 | 全链路蒸馏（各层独立训练 + Baseline 对标）| 本 SPEC 原创 | Trae Code 记忆→运行时系统学习是空白领域，需自建 |

> **v0.3 修正**：v0.2 引用的 arXiv:2512.24014 (iCLP) 和 STAR (rotation-augmented quantization) 经 Web 搜索**不可验证**，已删除。VQ-VAE 改引用 van den Oord 原论文（NeurIPS 2017，经典高引）。Online-LoRA 改为标准 KL 散度 + EMA 技术。

---

## 2. 架构总览

```
┌───────────────────────────────────────────────────────────────────────┐
│                        Trae Code 工作过程                               │
│  session_memory.jsonl  /  topics.md  /  project_memory.md              │
└───────────────────────────┬───────────────────────────────────────────┘
                            │ ① 文件监听 + 四元组提取 + Baseline 采集
                            ▼
┌───────────────────────────────────────────────────────────────────────┐
│              Trae Memory Bridge（新增 TS 模块）                          │
│  - 文件 watcher 监听 ~/.trae-cn/memory/ 变更                            │
│  - 四元组提取：problem / analysis / solution / result                  │
│  - 质量闸门：B+ 级才入 TDR（C 级入 RAG 知识库）                          │
│  - Baseline 采集：记录 Trae Code 在相同输入下的输出作为参照             │
└───────────────────────────┬───────────────────────────────────────────┘
                            │ ② 分层标注 + 编码入库
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│         中央训练数据仓库 (TDR) — Case Bank 升级版                        │
│         Training Data Repository                                        │
│                                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐              │
│  │  Case Bank   │  │ VQ-VAE      │  │ Drift Detector  │              │
│  │  + 分层标注   │  │ Encoder     │  │ (Online-LoRA    │              │
│  │              │  │ (codebook)  │  │  inspired)      │              │
│  │ layer_tag:   │  │             │  │                 │              │
│  │  S/DSH/C/    │  │ 四元组→     │  │ 分布漂移→       │              │
│  │  LLM/G       │  │ codebook    │  │ 触发增量训练     │              │
│  │              │  │ 索引向量     │  │                 │              │
│  │ + baseline   │  │             │  │                 │              │
│  └──────┬───────┘  └─────────────┘  └─────────────────┘              │
│         │                                                              │
│         │ ③ 按层分发训练数据                                              │
└─────────┼────────────────────────────────────────────────────────────┘
          │
    ┌─────┴─────┬──────────┬──────────┬──────────┬──────────┐
    ▼           ▼          ▼          ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│S层训练 │ │DSH训练 │ │C层训练 │ │G层训练 │ │LLM兜底 │
│Loop    │ │Loop    │ │Loop    │ │Loop    │ │训练Loop│
│        │ │        │ │        │ │        │ │        │
│规则权重│ │路径优化│ │反射决策│ │图结构  │ │Prompt │
│+Transf │ │+序列学习│ │+CBR   │ │学习    │ │模式学习│
│微调    │ │        │ │+规则蒸馏│ │        │ │        │
└───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────┘
    │          │          │          │          │
    └──────────┴──────────┴────┬─────┴──────────┘
                                │ ④ 各层独立评估
                                ▼
                    ┌──────────────────────┐
                    │   评估层 (Eval)        │
                    │   各层 vs Baseline     │
                    │                        │
                    │ 复现: 一致率 ≥ 阈值     │
                    │ 超越: 质量 > Baseline  │
                    │   且延迟/Token 更优     │
                    └──────────┬─────────────┘
                               │ ⑤ 达标 → 该层"复现"
                               │   超越 → 该层"超越"
                               ▼
                    ┌──────────────────────┐
                    │ CognitiveContextBuilder│
                    │ (第5系统: TDR检索)     │
                    └──────────┬─────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ SkillOrchestrationExec│
                    │ 路径B增强: 案例注入   │
                    └──────────┬─────────────┘
                               │
                          ⑥ 执行结果
                          回写 TDR
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Reflection Engine     │
                    │ (MCTS 纠错) [异步]    │
                    └──────────────────────┘
```

---

## 3. 算法模型设计（SolutionPatternLearner）

### 3.1 中央训练数据仓库 (TDR) — Case Bank 升级版

**数据结构**（v0.2 新增 `layer_tag` 和 `baseline` 字段）：

```typescript
interface SolutionCase {
  id: string;                    // case-{timestamp}-{hash}
  // v0.3: 四元组对齐实际 session_memory 格式
  intent: string;                 // 用户意图（session_memory.intent）
  actions: string[];              // 执行动作序列（session_memory.actions）
  outcome_text: string;           // 执行结果描述（session_memory.outcome）
  learned: string[];              // 学到的经验（session_memory.learned）
  message_id: string;             // 原始消息ID（session_memory.message_id）
  message_summary_time: string;    // 摘要时间（session_memory.message_summary_time）

  // 执行结果分类（从 outcome_text 推断）
  outcome: 'success' | 'failure' | 'partial' | 'unknown';

  // 向量化
  codebook_index: number[];       // VQ-VAE codebook 索引序列（4个：intent/actions/outcome/learned）
  embedding: number[];            // 语义向量（bge-small-zh 512 维）

  // v0.2 新增：分层标注
  layer_tags: LayerTag[];         // 该案例可供给哪些层训练
  baseline_output: BaselineOutput; // Trae Code 在相同输入下的输出基线

  // 元数据
  quality: 'S' | 'A' | 'B' | 'C';
  confidence: number;             // 0-1，贝叶斯置信度
  tags: string[];
  source: string;                  // session_id / trae-code / manual
  created_at: number;
  last_retrieved_at: number;
  replay_count: number;            // 被检索复用次数
  verify_count: number;           // 验证次数
}

// v0.2 新增
interface LayerTag {
  layer: 'S' | 'DSH' | 'C' | 'G' | 'LLM';
  training_data: unknown;          // 该层专属训练数据（格式由各层TrainingLoop定义）
  bucket_count: number;            // 该层训练桶当前条数
  bucket_threshold: number;        // 该层触发阈值（v0.3: 各层不同）
}

// v0.3 修正：Baseline 对齐实际 session_memory 字段
interface BaselineOutput {
  trae_intent: string;             // session_memory.intent（一定存在）
  trae_actions: string[];           // session_memory.actions（一定存在）
  trae_outcome: string;             // session_memory.outcome（一定存在）
  trae_learned: string[];           // session_memory.learned（一定存在）
  // 以下字段不存在于 session_memory，仅运行时采集时可用
  trae_token_usage?: number;        // 运行时采集（可选）
  trae_latency_ms?: number;          // 运行时采集（可选）
}
```

**存储**：
- 物理存储：SQLite `solution_case_bank.db`（独立于 cognitive_memory.db，物理隔离）
- 向量索引：复用 ChromaDB（新建 `solution_cases` 集合）
- 前端访问：新增 `case-bank-client.ts`（复刻 cognitive-client.ts 子进程模式）

**与认知系统的关系**：
- TDR 是认知系统的**结构化扩展层**，不写 cognitive_memory.db
- 案例提取时同步调 `record()` 在认知系统留痕（C 级），便于 recall 命中
- 案例验证后调 `verify()` 升级置信度，与贝叶斯闭环对齐

### 3.2 VQ-VAE 编码器（SolutionEncoder）

**目标**：将 `(intent, actions, outcome, learned)` 四元组编码为离散 codebook 索引向量，用于快速相似度检索。

**设计**（轻量级，无 GPU 依赖）：

```
四元组文本 → bge-small-zh 512 维 embedding → 量化器 → codebook 索引序列
```

**量化器设计**：
- codebook 大小：256 个码字（初始，可扩展到 1024）
- 码字维度：512（与 bge-small-zh 对齐）
- 初始化策略：**k-means++ 初始化**（首批 100 条数据聚类后初始化 codebook）
- 量化方式：最近邻分配 + **EMA 更新**（无梯度回传）

**EMA 更新公式**（v0.3 新增论证）：
```
对每个新样本 x，找到最近码字 c_i：
  c_i ← α * c_i + (1 - α) * x        // α = 0.99（衰减率）
  usage_count[i] += 1

无梯度可行性论证：
  - VQ-VAE 原论文使用 straight-through estimator + commitment loss（需梯度）
  - 本 SPEC 采用 EMA 更新（非梯度），类似 Product Quantization (PQ) 的训练方式
  - PQ (Jégou et al., 2011) 已证明 EMA 更新可产生有效 codebook
  - 本系统不训练编码器/解码器（不做重建），只做检索量化，EMA 足够
```

- 输出：每个四元组 → 4 个 codebook 索引（intent/actions/outcome/learned 各一个）

**相似度计算**：
- 主：codebook 索引序列的 Jaccard 相似度（O(n)，快速）
- 辅：embedding 余弦相似度（仅对 top-K 候选精排）

**为什么不用纯 embedding**：
- codebook 索引天然支持倒排索引，检索 O(1)
- 离散码本支持 case 的精确匹配和模式聚类
- 比 512 维向量比较快 10x

**codebook 塌缩防护**：
- 码字使用率低于阈值（默认 1/256）→ 重置为最近未分配样本
- 退化方案：如果 EMA 更新后 codebook 质量（检索 hit rate < 30%）→ 回退到纯 bge embedding + LSH 索引

### 3.3 Case Retriever（案例检索器）

**Soft Q-Learning 检索策略**（Memento 架构）：

```typescript
interface RetrievalResult {
  cases: SolutionCase[];
  scores: number[];               // Soft Q 值
  retrieval_mode: 'exact' | 'semantic' | 'fallback';
}

// Soft Q 计算
case_score = α * jaccard_similarity    // codebook 匹配度
           + β * cosine_similarity      // 语义相似度
           + γ * quality_weight         // 质量权重（S>A>B>C）
           + δ * success_rate           // 历史成功率
           - λ * age_penalty;           // 时间衰减
```

**参数初始值**：α=0.3, β=0.3, γ=0.2, δ=0.15, λ=0.05

**参数调优方法**（v0.3 新增）：
- 初始值基于 Memento 论文（arXiv:2508.16153）推荐范围
- 调优信号：每次 case verify 后，如果检索 top-1 的 outcome 与新 query outcome 不一致 → α/β 权重调整
- 调优频率：每 100 次检索后检查一次调优信号
- 调优幅度：每次调整 ±0.05，不超过 [0.05, 0.50] 范围
- 冷启动：前 200 次检索不调优（积累足够 verify 数据后才开始）

**检索流程**：
1. 新 query → VQ-VAE 编码 → codebook 索引
2. 倒排索引查候选（Jaccard > 0.3）→ 精排（cosine + quality + success）
3. top-K=5 案例返回
4. 如果无候选 → `retrieval_mode='fallback'` → 走原路径 B

### 3.4 Reflection Engine（反思引擎）

**Agent-R 式 MCTS 纠错**（异步离线执行，不阻塞主链路）：

**触发条件**：
- 案例执行结果为 `failure` 或 `partial`
- 同类 pattern 连续失败 ≥ 2 次

**纠错流程**：
1. 提取失败轨迹：problem → analysis → solution → result(fail)
2. MCTS 搜索修正路径：从失败点开始，尝试 N 条替代路径
3. 拼接正确路径：找到成功终态 → 反向推导修正方案
4. 生成修正案例 → 入 TDR（标记 `corrected_from: 原案例id`）

**异步执行**：
- 通过 `setImmediate` + `queue` 异步处理
- 主链路不等待反思完成
- 反思完成后写入 TDR，下次同类 query 自动命中

### 3.5 Drift Detector（分布漂移检测器）

**Online-LoRA 启发的漂移检测**：

```typescript
interface DriftState {
  window_size: number;            // 滑动窗口（默认 50 条）
  baseline_distribution: Map<string, number>;  // codebook 索引频率基线
  current_distribution: Map<string, number>;
  drift_score: number;            // KL 散度
  drift_detected: boolean;
}
```

**检测逻辑**：
1. 维护 codebook 索引频率的滑动窗口分布
2. 计算当前窗口与基线的 KL 散度
3. KL 散度 > 阈值（默认 0.15）→ 触发增量训练

**增量训练动作**（漂移触发时）：
1. 重置 codebook：用最近 window_size 条数据重新聚类码字
2. 更新检索参数：用 verify 历史重新调优 α/β/γ/δ/λ
3. 记录漂移事件：`record(content="[SPL漂移] KL=xxx, 触发重聚类")`

**非每轮训练**：漂移检测确保只在分布变化时触发训练，避免高频场景下的计算浪费。

---

## 4. 全链路训练蒸馏（v0.2 新增核心）

### 4.1 设计理念

SPL v0.2 的终极目标不是"辅助执行"，而是**训练前端全链路的每一层**，使其独立达到"复现"甚至"超越" Trae Code 的能力。

**训练蒸馏链路**：
```
Trae Code 沉淀 → TDR（分层标注）→ 各层 TrainingLoop → 各层独立评估 → 复现/超越
```

**"复现"定义**：各层在相同输入下，输出与 Trae Code Baseline 的一致率 ≥ 该层阈值
**"超越"定义**：各层在相同输入下，输出质量 ≥ Trae Code Baseline，且延迟/Token 消耗更低

### 4.2 五个层专属训练器

#### 4.2.1 S层 — IntentTrainingLoop

| 维度 | 设计 |
|------|------|
| **训练数据** | session_memory 中 `(message, intent)` pairs |
| **数据提取** | `layer_tag: 'S'`，`training_data = { message, intent_type, entities }` |
| **训练目标** | 规则识别器权重增量 + Transformer 微调 → 35型分类 + 实体抽取 |
| **训练方法** | ① 规则权重增量（TF-IDF + 频率统计）② DynamicRecognizer 权重更新 ③ 可选 Transformer 轻量微调 |
| **触发节奏** | 桶满 100 条触发（v0.3: S层需覆盖35型，30条不足） |
| **复现目标** | intent 一致率 ≥ 80%（待验证） |
| **依赖** | **独立可训练**，无下游依赖 |
| **现有基础** | SPEC-20261004 已有训练闭环设计，可直接对接 TDR 数据源 |
| **新增文件** | `src/lib/solution-pattern-learner/s-intent-training-loop.ts` |

#### 4.2.2 DSH — ExecutionPathTrainingLoop

| 维度 | 设计 |
|------|------|
| **训练数据** | session_memory 中 `actions` 序列 + `outcome` |
| **数据提取** | `layer_tag: 'DSH'`，`training_data = { task, node_sequence, outcome }` |
| **训练目标** | 学习最优节点选择 + 执行顺序（35个模块配置 + 11个本地实现） |
| **训练方法** | ① 序列模式挖掘（频繁项集→路径模板）② 成功率加权（outcome=success 的路径权重↑）③ 路径模板蒸馏为规则 |
| **触发节奏** | 桶满 50 条触发（v0.3: DSH 路径模式比 S 层简单，50 条足够） |
| **复现目标** | actions 编辑距离比 ≤ 0.3（待验证） |
| **超越目标** | actions 更简洁（序列更短或同长度更优） |
| **依赖** | **S层先训**（意图准确才能选对节点） |
| **现有基础** | `dsh-execution-engine.ts` 已有 node_id→module 映射表 |
| **新增文件** | `src/lib/solution-pattern-learner/dsh-path-training-loop.ts` |

#### 4.2.3 C层 — ReflectionTrainingLoop

| 维度 | 设计 |
|------|------|
| **训练数据** | `(context, action, outcome)` 三元组 → 5种反射决策 |
| **数据提取** | `layer_tag: 'C'`，`training_data = { context_summary, action_taken, outcome, expected_decision }` |
| **训练目标** | CBR case-based + 规则蒸馏 → CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE |
| **训练方法** | ① CBR 案例检索（复用 Case Retriever）② 决策规则蒸馏（频繁模式→规则）③ MCTS 纠错（失败→修正决策） |
| **触发节奏** | 桶满 50 条触发（v0.3: C层 5 种决策需足够样本） |
| **复现目标** | 决策一致率 ≥ 75%（待验证） |
| **超越目标** | 失败恢复率 > Trae Code（MCTS 纠错加持） |
| **依赖** | **S层 + DSH 先训**（反射需要上下文和执行结果） |
| **现有基础** | DreamOS C层 `reflector.py` 已有 5种决策规则化 |
| **新增文件** | `src/lib/solution-pattern-learner/c-reflection-training-loop.ts` |

#### 4.2.4 G层 — GraphStructureTrainingLoop

| 维度 | 设计 |
|------|------|
| **训练数据** | topics.md 决策 + project_memory.md 规则 |
| **数据提取** | `layer_tag: 'G'`，`training_data = { decisions, rules, graph_structure }` |
| **训练目标** | 自动知识图谱构建 + BAC 三层压缩 |
| **训练方法** | ① 决策→图节点映射 ② 规则→图边映射 ③ 压缩模式学习（频繁子图→模板） |
| **触发节奏** | 桶满 30 条触发（v0.3: G层决策数据相对稀疏，30 条足够） |
| **复现目标** | 图覆盖率 ≥ 70%（待验证） |
| **超越目标** | 压缩率 > Trae Code，自动演化 |
| **依赖** | **独立可训练**（与 S层并行） |
| **现有基础** | DreamOS G层 `graph_store/` 已有快照+压缩框架 |
| **新增文件** | `src/lib/solution-pattern-learner/g-graph-training-loop.ts` |

#### 4.2.5 LLM兜底 — PromptOptimizationLoop

| 维度 | 设计 |
|------|------|
| **训练数据** | session_memory 中 `learned` (经验数组) + `outcome` |
| **数据提取** | `layer_tag: 'LLM'`，`training_data = { intent, learned, outcome, prompt_pattern }` |
| **训练目标** | 学习 Trae Code 的 prompt 模式 + 上下文注入策略 |
| **训练方法** | ① Prompt 模式聚类（频繁模板→最优模板）② 上下文注入优化（哪些信息最有效）③ Token 效率优化（精简 prompt） |
| **触发节奏** | 桶满 30 条触发（v0.3: LLM 模式聚类需要少量样本） |
| **复现目标** | 输出与 trae_learned 语义相似度 ≥ 0.7（待验证） |
| **超越目标** | learned 覆盖率 > Trae Code |
| **依赖** | **C层先训**（何时走兜底由 C层决策） |
| **现有基础** | DSH LLM fallback 已有 `document_context` 注入机制 |
| **新增文件** | `src/lib/solution-pattern-learner/llm-prompt-training-loop.ts` |

### 4.3 训练依赖顺序

```
① S层 + G层 (并行，独立可训)
     ↓
② DSH 执行路径
     ↓
③ C层 反射决策
     ↓
④ LLM兜底优化
     ↓
⑤ 全链路联调评估
```

**设计理由**：
- S层和 G层无下游依赖，可并行训练
- DSH 需要 S层的意图识别结果来选择节点
- C层需要 S层上下文 + DSH 执行结果做反射决策
- LLM兜底需要 C层决策来确定何时走兜底

### 4.4 Baseline 采集系统

**目标**：建立"Trae Code 在相同输入下的输出基线"，作为"复现/超越"的参照系。

**采集方式**（v0.3 修正）：
- Trae Memory Bridge 从 session_memory 提取 Trae Code 的实际输出作为 Baseline
- 4 个**确定性字段**（一定存在）：`trae_intent, trae_actions, trae_outcome, trae_learned`
- 2 个**可选字段**（运行时采集）：`trae_token_usage, trae_latency_ms` — 需增加 Trae Code 执行 hook 才能采集

**Baseline 字段映射**（v0.3 对齐实际 session_memory 格式）：

| Baseline 字段 | 来源 | 对标层 | 确定性 |
|---------------|------|--------|--------|
| `trae_intent` | session_memory.intent | S层 | 一定存在 |
| `trae_actions` | session_memory.actions | DSH | 一定存在 |
| `trae_outcome` | session_memory.outcome | C层 | 一定存在 |
| `trae_learned` | session_memory.learned | LLM兜底 | 一定存在 |
| `trae_token_usage` | **运行时采集**（需 hook） | 全局 | 可选 |
| `trae_latency_ms` | **运行时采集**（需 hook） | 全局 | 可选 |

> **v0.3 说明**：v0.2 声称的 `trae_decision, trae_analysis, trae_solution` 字段在 session_memory 中**不存在**，已删除。C层 Baseline 改用 `trae_outcome` 推断决策类型。

### 4.5 评估层（v0.3: 改用可度量指标）

**各层独立评估**（v0.3: 阈值降级为"待验证目标"，需 pilot 实验确认）：

| 层 | "复现"目标（待验证） | "超越"目标（待验证） | 评估方法 |
|----|-----------|-----------|----------|
| S层 | intent 分类与 trae_intent 一致率 ≥ 80% | 一致率 > trae + 覆盖更多场景 | eval 集对照 trae_intent |
| DSH | actions 序列与 trae_actions 的编辑距离比 ≤ 0.3 | actions 更简洁（序列更短或相同长度更优） | Levenshtein 距离 + 序列长度比 |
| C层 | 反射决策与 trae_outcome 推断决策一致率 ≥ 75% | 失败恢复率 > trae（MCTS 纠错） | 决策对照 + 失败恢复率 |
| LLM | 输出与 trae_learned 语义相似度 ≥ 0.7 | learned 覆盖率 > trae | bge embedding cosine + 覆盖率统计 |
| G层 | 图节点覆盖 trae 决策 ≥ 70% | 压缩率 > trae | 图覆盖率 + 压缩比 |

> **v0.3 变更**：
> - "复现"阈值从 90%/85% 降级为 80%/75%（**待验证目标**，需 pilot 实验调整）
> - "超越"标准删除 Token 相关指标（session_memory 无 token_usage 字段），改用语义一致率/编辑距离等可度量指标
> - 若需 Token 对比，需增加 Trae Code 运行时 hook 采集（P2 阶段可选实现）

**评估流程**：
1. 各层训练后，用 eval 集评估
2. 对照 Baseline 计算语义一致率/编辑距离/覆盖率
3. 达标 → 该层"复现"成功
4. 超越 Baseline → 该层"超越"成功
5. 评估结果调 `verify()` 更新认知系统置信度

**全链路联调**（第⑤步）：
- 所有层"复现"后，端到端测试
- 相同输入 → 前端全链路输出 vs Trae Code 输出
- 端到端语义一致率 ≥ 70% → 全链路"复现"
- 端到端质量 > Trae Code → 全链路"超越"

---

## 5. 数据管线设计

### 5.1 Trae Memory Bridge（Trae 记忆桥接器）

**新增文件**：`3.1-FRONTEND/src/lib/trae-memory-bridge.ts`

**核心流程**：

```
① 文件监听
   chokidar.watch('~/.trae-cn/memory/projects/*/**/*.jsonl')
   chokidar.watch('~/.trae-cn/memory/projects/*/project_memory.md')
   chokidar.watch('~/.trae-cn/memory/projects/*/topics.md')
   chokidar.watch('~/.trae-cn/memory/user_profile.md')

② 变更解析
   session_memory.jsonl → 逐行解析 → 提取 intent/actions/outcome/learned
   topics.md → Markdown 解析 → 提取 session 摘要
   project_memory.md → 提取规则/约束/决策
   user_profile.md → 提取偏好/背景

③ 四元组构建 + Baseline 采集（v0.3: 对齐实际字段）
   intent = session.intent
   actions = session.actions
   outcome_text = session.outcome
   learned = session.learned
   baseline_output = {
     trae_intent: session.intent,       // 一定存在
     trae_actions: session.actions,      // 一定存在
     trae_outcome: session.outcome,      // 一定存在
     trae_learned: session.learned,      // 一定存在
     // trae_token_usage / trae_latency_ms: 运行时采集（可选）
   }

④ 分层标注
   layer_tags = [
     { layer: 'S', training_data: { intent, message_id }, bucket_threshold: 100 },
     { layer: 'DSH', training_data: { actions, outcome }, bucket_threshold: 50 },
     { layer: 'C', training_data: { context: intent+actions, outcome, expected_decision }, bucket_threshold: 50 },
     { layer: 'LLM', training_data: { intent, learned, outcome }, bucket_threshold: 30 },
   ]
   // G层从 topics.md / project_memory.md 单独提取, bucket_threshold: 30

⑤ 质量闸门（v0.3 修复矛盾）
   - outcome 包含"完成/成功" + learned 非空 → B 级 → 入 TDR
   - outcome 包含"失败/错误" + learned 非空 → C 级 → 入 TDR + 标记可反思
   - outcome 包含"部分/修改" + learned 非空 → B 级 → 入 TDR
   - learned 为空 → 丢弃（噪音过滤）
   // 注：v0.2 "B+级才入TDR" 与 "failure→C级入TDR" 矛盾，v0.3 统一为：有 learned 即入库，等级按 outcome 分配

⑥ 编码入库
   四元组 → SolutionEncoder → codebook + embedding → TDR
   同步调 cognitive record() 留痕
```

**去重策略**：
- content hash 去重（相同 problem+solution 不重复入库）
- 语义去重（cosine > 0.95 视为重复，合并 verify_count）

**安全约束**：
- 只读 Trae Code 记忆文件，不修改
- B 类沉淀导入时标注 `source: "trae-code-bridge"`
- 不自动提升 user_profile 内容为 VM（物理隔离硬约束）

### 5.2 执行反馈回写

**在 SkillOrchestrationExecutor 路径 B 增强后**：

```
案例命中 → 注入 case.solution 作为 document_context → DSH 执行
  → 执行结果 → 回写 TDR：
    - success: case.replay_count++, confidence 上调
    - failure: 标记 failure, 触发 Reflection Engine
    - partial: 标记 partial, 置信度不变
  → 同步更新各层训练桶计数
```

**回写接口**：`caseBankClient.updateCaseResult(caseId, outcome, executionLog)`

---

## 6. 实时训练闭环

### 6.1 训练数据流

```
                    ┌──────────────┐
                    │ Trae Code     │
                    │ 工作过程       │
                    └──────┬───────┘
                           │ session_memory.jsonl 变更
                           ▼
                    ┌──────────────┐
                    │ Trae Memory  │
                    │ Bridge       │
                    │ + Baseline   │
                    └──────┬───────┘
                           │ 四元组 + 分层标注 + 质量闸门
                           ▼
                    ┌──────────────┐
                    │ Solution     │
                    │ Encoder      │ (VQ-VAE codebook)
                    └──────┬───────┘
                           │ codebook 索引 + embedding
                           ▼
              ┌──────────────────────────┐
              │    TDR (SQLite + ChromaDB)        │
              │                                    │
              │  ┌─────────┐  ┌──────────────────┐│
              │  │ cases   │  │ codebook (256码字)││
              │  │ +layer  │  │ + EMA 更新        ││
              │  │  _tags  │  │                  ││
              │  │ +baseline│ │                  ││
              │  └─────────┘  └──────────────────┘│
              └──────┬───────────────┬──────────────┘
                     │               │
          ① 检索     │               │ ② 漂移检测
                     ▼               ▼
              ┌──────────────┐ ┌──────────────┐
              │ Case         │ │ Drift        │
              │ Retriever    │ │ Detector     │
              │ (Soft Q)     │ │ (KL 散度)     │
              └──────┬───────┘ └──────┬───────┘
                     │                │
                     │          ③ 漂移触发
                     │          增量训练
                     │                │
         ┌───────────┼────────────────┼───────────┐
         ▼           ▼                ▼           ▼
    ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
    │S层训练 │  │DSH训练 │  │C层训练 │  │LLM/G  │
    │Loop    │  │Loop    │  │Loop    │  │Loop   │
    └───┬────┘  └───┬────┘  └───┬────┘  └───┬────┘
        │           │           │            │
        └───────────┴─────┬─────┴────────────┘
                          │ ④ 各层独立评估
                          ▼
                ┌──────────────────────┐
                │   评估层 (Eval)        │
                │   各层 vs Baseline     │
                └──────────┬─────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ CognitiveContextBuilder│
                │ (第5系统: TDR检索)     │
                └──────────┬─────────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │ SkillOrchestrationExec│
                │ 路径B增强: 案例注入   │
                └──────────┬─────────────┘
                           │
                      ⑤ 执行结果
                      回写 TDR
                           │
                           ▼
                ┌──────────────────────┐
                │ Reflection Engine     │
                │ (MCTS 纠错) [异步]    │
                └──────────────────────┘
```

### 6.2 训练节奏

| 触发条件 | 训练动作 | 频率 | 阻塞主链路 |
|----------|----------|------|-----------|
| session_memory 变更 | 四元组提取 + 分层标注 → 编码 → 入 TDR | 实时 | 否（异步） |
| 新 query 进入 | TDR 检索 → 注入上下文 | 实时 | 是（<50ms） |
| 执行结果回写 | case 更新 + verify + 各层桶计数 | 实时 | 否（异步） |
| S层桶满 100 | 规则权重增量 + DynamicRecognizer 更新 | 按需 | 否（异步） |
| DSH桶满 50 | 路径模板挖掘 + 成功率加权 | 按需 | 否（异步） |
| C层桶满 50 | CBR案例检索 + 决策规则蒸馏 | 按需 | 否（异步） |
| LLM桶满 30 | Prompt模式聚类 + 上下文优化 | 按需 | 否（异步） |
| G层桶满 30 | 决策→图映射 + 压缩模式学习 | 按需 | 否（异步） |
| KL 散度 > 0.15 | codebook 重聚类 + 参数调优 | 按需 | 否（异步） |
| 连续失败 ≥ 2 | MCTS 纠错 → 修正案例 | 按需 | 否（异步） |
| case verify ≥ 3 | 置信度升级 + 标记可沉淀为 SKILL | 按需 | 否（异步） |

### 6.3 冷启动策略

TDR 初始为空时的降级链：

```
TDR 空 → retrieval_mode='fallback'
  → 走原路径 B（文档检索 → LLM 转计划 → DSH 执行）
  → ImitationCounter 计数
  → 同时 Trae Memory Bridge 开始从历史 session_memory 导入
  → 导入完成后 TDR 可用
  → 各层训练桶开始累积
  → 桶满后触发各层训练
```

**历史导入**：首次启动时扫描最近 7 天的 session_memory.jsonl，批量导入 + 分层标注。

---

## 7. 集成点设计

### 7.1 CognitiveContextBuilder 增强

```typescript
// cognitive-context-builder.ts 新增第 5 系统接入

export interface CognitiveContext {
  experiences: CognitiveExperience[];
  knowledge: KnowledgeChunk[];
  references: IndexReference[];
  skill_candidates: SkillCandidate[];
  // v0.2: TDR 检索结果
  solution_cases: SolutionCase[];
}

// build() 方法新增并行调用
async build(intentType: string, entities: string[], message: string): Promise<CognitiveContext> {
  const [recallResult, ragResult, indexResult, skillResult, caseResult] = await Promise.allSettled([
    this.recallExperiences(intentType, entities),
    this.retrieveKnowledge(message),
    this.queryIndex(message),
    this.getSkillCandidates(intentResult),
    // v0.2: TDR 检索
    this.retrieveSolutionCases(message),
  ]);
  // ... FAIL-OPEN: caseResult 失败则 solution_cases=[]
}
```

### 7.2 SkillOrchestrationExecutor 路径 B 增强

```typescript
// skill-orchestration-executor.ts 路径 B 增强

if (plan.imitation_required) {
  // ① 先查 TDR
  const caseResult = await caseBankClient.retrieve(message, { top_k: 5 });
  
  if (caseResult.ok && caseResult.data?.cases?.length > 0) {
    // ② 有案例：注入 case.solution 作为 document_context
    const bestCase = caseResult.data.cases[0];
    const docContext = `## 历史解题模式\n意图: ${bestCase.intent}\n动作: ${bestCase.actions.join(' → ')}\n结果: ${bestCase.outcome_text}\n经验: ${bestCase.learned.join('; ')}`;
    
    const imitationPlan = {
      ...plan,
      skill_ids: plan.skill_ids || ['simple_qa'],  // v0.3: 从 plan 动态获取，非硬编码
      params: {
        document_context: docContext,
        known_components: knownComponents,
        case_source: bestCase.id,
      },
    };
    
    const skillResults = await engine.execute_plan(imitationPlan);
    
    // ③ 执行结果回写 TDR
    const outcome = assessOutcome(skillResults);
    await caseBankClient.updateCaseResult(bestCase.id, outcome, JSON.stringify(skillResults));
    
    // ④ ImitationCounter 仍计数（保留兜底）
    counter.increment(message, [], JSON.stringify(imitationPlan.params));
    
    return { /* ... */ };
  }
  
  // ⑤ 无案例：走原路径 B（文档检索 → LLM 转计划）
  // ... 原有逻辑不变
}
```

### 7.3 新增文件清单

> 注：实际实现时所有 SPL TS 模块统一放在 `src/lib/` 根目录（未创建 `solution-pattern-learner/` 子目录），与项目现有 lib 文件结构一致。

| 文件（实际路径） | 职责 | 技术栈 | 阶段 | 状态 |
|------|------|--------|------|------|
| `src/lib/case-bank-client.ts` | TDR IPC 客户端（核心逻辑在 Python 端）| TypeScript | P0 | ✅ |
| `src/lib/solution-encoder.ts` | VQ-VAE 编码器 | TypeScript | P0 | ✅ |
| `src/lib/case-retriever.ts` | Soft Q-Learning 检索 | TypeScript | P1 | ✅ |
| `src/lib/reflection-engine.ts` | MCTS 纠错引擎 | TypeScript | P4 | ✅ |
| `src/lib/drift-detector.ts` | 分布漂移检测（KL散度>0.15触发增量训练）| TypeScript | P3 | ✅ |
| `src/lib/s-intent-training-loop.ts` | S层意图训练循环 | TypeScript | P1 | ✅ |
| `src/lib/dsh-path-training-loop.ts` | DSH执行路径训练循环 | TypeScript | P2 | ✅ |
| `src/lib/c-reflection-training-loop.ts` | C层反射决策训练循环 | TypeScript | P3 | ✅ |
| `src/lib/g-graph-training-loop.ts` | G层图结构训练循环 | TypeScript | P1 | ✅ |
| `src/lib/llm-prompt-training-loop.ts` | LLM兜底Prompt优化循环 | TypeScript | P3 | ✅ |
| `src/lib/eval-layer.ts` | 评估层（各层 vs Baseline）| TypeScript | P4 | ✅ |
| `src/lib/cross-validation-gate-spl.ts` | 交叉验证门 | TypeScript | P0 | ✅ |
| `src/lib/trae-memory-bridge.ts` | Trae Code 记忆桥接 + Baseline 采集 | TypeScript | P0 | ✅ |
| `src/lib/case-verify-bridge.ts` | Case verify → cognitive verify 桥接 | TypeScript | P4 | ✅ |
| `scripts/case_bank_adapter.py` | TDR Python 适配器 | Python | P0 | ✅ |
| `scripts/case_bank_server.py` | TDR 后端服务 | Python + SQLite + ChromaDB | P0 | ✅ |

**测试统计**：19 套件 / 271 测试 / 全部通过（2026-10-09）

### 7.4 新增 API Route

```typescript
// src/app/api/spl/route.ts
// GET  /api/spl?query=xxx → 检索案例
// POST /api/spl { case: {...} } → 入库新案例
// PUT  /api/spl { case_id, outcome } → 更新执行结果
// GET  /api/spl/stats → TDR 统计
// GET  /api/spl/eval?layer=S → 各层评估结果
// POST /api/spl/train?layer=S → 手动触发某层训练
```

---

## 8. 物理隔离与安全约束

| 约束 | 说明 |
|------|------|
| TDR 独立 DB | `solution_case_bank.db`，不写 cognitive_memory.db |
| Trae 记忆只读 | Bridge 只读取 `~/.trae-cn/memory/`，不修改 |
| 用户偏好不自动提升 | user_profile.md → user_memory.db preferences 表（需 P3 人工审批才提升为 VM） |
| FAIL-OPEN | SPL 任一组件失败 → 走原路径 B，不阻塞 |
| 质量闸门 | 有 learned 即入库，等级按 outcome 分配（v0.3 修复：B/C 级均入 TDR，learned 空丢弃） |
| 异步反思 | Reflection Engine 不阻塞主链路 |
| 异步训练 | 各层 TrainingLoop 不阻塞主链路 |
| Baseline 只读 | Baseline 输出不可被训练器修改，只用于评估对照 |
| 分层隔离 | 各层训练器独立运行，不互相干扰 |
| TDR 容量 | 上限 10000 条，超限时 LRU + 质量加权淘汰（v0.3 新增） |

---

## 9. 验收标准

| 编号 | 验收项 | 标准 | 验证方法 |
|------|--------|------|----------|
| V1 | TDR 建库 | solution_case_bank.db + ChromaDB 集合创建 + 分层标注字段 | sqlite3 + chroma_client 查验 |
| V2 | Trae Memory Bridge | 从 session_memory.jsonl 提取 intent/actions/outcome/learned + Baseline + 分层标注 | 单元测试：mock jsonl → 验证提取（v0.3: 用实际字段） |
| V3 | VQ-VAE 编码 | 四元组 → codebook 索引（256 码字），k-means++ 初始化 + EMA 更新正常 | 单元测试：编码 → 码字分配 → 相似 query 编码一致 |
| V4 | TDR 检索 | 新 query → top-5 案例返回，<50ms | 基准测试：1000 条 case 库检索延迟 P95 < 50ms |
| V5 | 路径 B 增强 | 有案例时注入 case.intent+actions，无案例走原路径 | 集成测试：mock TDR → 验证注入逻辑 |
| V6 | 执行反馈回写 | success/failure/partial 正确回写 + 各层桶计数更新 | 单元测试：执行 → 回写 → 查验 case 状态 + 桶计数 |
| V7 | 漂移检测 | KL 散度计算 + 触发重聚类 | 单元测试：注入分布偏移数据 → 验证 drift_detected=true |
| V8 | 反思引擎 | 失败案例 → MCTS 纠错 → 修正案例入库 | 集成测试：mock 失败 → 验证修正案例生成 |
| V9 | 冷启动 | TDR 空 → 降级原路径 B → 历史导入后可用 | E2E 测试：空库启动 → 验证降级 → 导入后检索 |
| V10 | 认知闭环 | case verify ≥ 3 → 调 cognitive verify() 升级 | 集成测试：mock verify → 验证 cognitive 系统调用 |
| V11 | S层训练 | 桶满100 → 规则权重更新 → intent一致率≥80%（目标，待验证） | 单元测试：100条训练数据 → 验证权重更新 + eval集一致率 |
| V12 | DSH训练 | 桶满50 → 路径模板生成 → 编辑距离比≤0.3（目标，待验证） | 单元测试：50条路径数据 → 验证模板生成 + 距离比 |
| V13 | C层训练 | 桶满50 → 决策规则蒸馏 → 决策一致率≥75%（目标，待验证） | 单元测试：50条决策数据 → 验证规则蒸馏 + 一致率 |
| V14 | G层训练 | 桶满30 → 图结构更新 → 图覆盖率≥70%（目标，待验证） | 单元测试：30条决策数据 → 验证图更新 + 覆盖率 |
| V15 | LLM训练 | 桶满30 → Prompt模式优化 → 语义相似度≥0.7（目标，待验证） | 单元测试：30条LLM数据 → 验证Prompt优化 + 相似度 |
| V16 | Baseline 采集 | 每个训练样本含 trae_intent/trae_actions/trae_outcome/trae_learned | 单元测试：验证 baseline 字段完整（v0.3: 对齐实际字段） |
| V17 | 评估层 | 各层训练后 vs Baseline → 复现/超越判定 | 集成测试：mock 训练 → 验证评估输出 |
| V18 | 全链路联调 | 所有层复现后 → 端到端语义一致率≥70%（目标，待验证） | E2E 测试：相同输入 → 全链路输出 vs Trae Code |
| V19 | TDR 容量 | 上限10000条 → 超限LRU+质量加权淘汰 | 单元测试：插入10001条 → 验证淘汰策略（v0.3 新增） |
| V20-V24 | 见 §11.12 交叉验证层验收标准 | — | — |

---

## 10. 实施路径

### Phase 1: 基础设施 + 数据管线（P0）

1. TDR 后端：`case_bank_server.py` + SQLite + ChromaDB + 分层标注 + Baseline 字段
2. TDR 客户端：`case-bank-client.ts`（IPC 模式）
3. VQ-VAE 编码器：`solution-encoder.ts`（codebook 256 + EMA）
4. Trae Memory Bridge：`trae-memory-bridge.ts`（文件监听 + 四元组提取 + Baseline 采集 + 分层标注）
5. 质量闸门 + 去重
6. 历史导入：扫描最近 7 天 session_memory 批量导入
7. 单元测试：编码/存储/检索/Bridge 全链路

### Phase 2: S层 + G层 训练 + 检索注入（P1）

8. Case Retriever：`case-retriever.ts`（Soft Q-Learning）
9. CognitiveContextBuilder 增强：第 5 系统接入
10. SkillOrchestrationExecutor 路径 B 增强
11. 执行反馈回写
12. S层 IntentTrainingLoop：`s-intent-training-loop.ts`（对接 SPEC-20261004）
13. G层 GraphStructureTrainingLoop：`g-graph-training-loop.ts`
14. E2E 测试：query → 检索 → 注入 → 执行 → 回写

### Phase 3: DSH + C层 + LLM 训练（P2-P3）

15. DSH ExecutionPathTrainingLoop：`dsh-path-training-loop.ts`
16. C层 ReflectionTrainingLoop：`c-reflection-training-loop.ts`
17. LLM PromptOptimizationLoop：`llm-prompt-training-loop.ts`
18. Drift Detector：`drift-detector.ts`（KL 散度 + 增量训练）
19. 各层桶满触发训练逻辑
20. 各层单元测试

### Phase 4: 评估 + 反思 + 全链路联调（P4）

21. 评估层：`eval-layer.ts`（各层 vs Baseline）
22. Reflection Engine：`reflection-engine.ts`（MCTS 纠错）
23. 认知闭环接入：case verify → cognitive verify
24. 全链路联调：所有层复现后端到端测试
25. 性能基准测试

---

## 11. 交叉验证层架构设计（矛盾论+Transformer 集成）

> **v0.4 新增**：基于深度调研（矛盾论 v3.0 + Transformer 融合架构 v0.9，文件 `23-四层闭环自进化交易架构/docs/矛盾论与Transformer架构融合方案.md`），将交易域验证有效的交叉验证框架域迁移到 SPL。核心洞察：该框架本质域无关——Past(Validated) ↔ Present(Current) → Consistency/Divergence/QualityChange → Self-Evolution。
> **交易域实证**：5 框架 walk-forward 验证，交叉验证方案 OOS 夏普 7.77 排第一（Holm-Bonferroni 校正 p<0.001 优于 F2/F4/F5）。
> **设计原则**：与交易域一致——最小改动 + 可回退 + 模块化 + FAIL-OPEN + 自进化闭环。

### 11.1 核心命题

SPL v0.3 是**被动模仿**——从 Trae Code 沉淀中检索相似案例。交叉验证层将其升级为**矛盾感知自进化**：

| 维度 | SPL v0.3（当前） | SPL v0.4 + 交叉验证层 |
|------|-----------------|----------------------|
| 核心机制 | CBR 检索 + VQ-VAE 编码 | CBR + 交叉验证 + 质变检测 + 自进化 |
| 学习方式 | 被动模仿 Trae Code | 主动感知模式转移，驱动自训练 |
| 训练触发 | 桶满阈值（定量） | 质变事件（定性+定量双重） |
| 层权重 | 固定/均匀 | head_multipliers 动态调整 |
| 超越路径 | 无（只模仿） | 质变后重训练 → 可能超越；**超越度量**：质变后重训练的 query 解决率 vs 质变前 Trae Code 基线解决率，超越 = 重训练后解决率 > 基线 + 5% |
| 自进化 | 无 | 质变→重训练→新基线→新交叉验证→持续进化 |

### 11.2 域映射（Trading → SPL）

| 交易域概念 | SPL 域映射 | 映射逻辑 | SPL 已有组件 |
|-----------|-----------|---------|-------------|
| Granger 因果（看过去） | TDR 历史解题模式 | session_memory 验证的解题模式 | ✅ TDR |
| Attention 权重（看现在） | 当前 query 注意力分布 | 当前意图的 VQ-VAE 编码 | ✅ VQ-VAE Encoder |
| G_dim（3: technical/fundamental/macro） | G_dim_spl: 过去主解题范式 | 见 §11.3 维度分类 | ✅ TDR layer_tag |
| A_dim（8: C1-C8） | A_dim_spl: 当前主解题范式 | VQ-VAE codebook 聚类结果 | ✅ VQ-VAE |
| StructuralBreakDetector | Drift Detector | KL 散度 + EMA 漂移检测 | ✅ Drift Detector |
| head_multipliers（8 head） | 层权重（S/DSH/C/G/LLM） | 5 层 TrainingLoop 权重 | ✅ 5 TrainingLoops |
| 质变→Granger 重估 | 质变→重训练 | 质变事件触发 TDR 重训练 | ✅ TrainingLoop trigger |
| confidence_mult | 置信调整 | 案例检索置信度调整 | 新增（CVG 输出） |
| shift_signal | 模式转移信号 | 解题范式转移预警 | 新增（CVG 输出） |
| quality_change | 质变确认 | 解题范式质变确认 | 新增（CVG 输出） |

> **⚠️ 方法论降级声明**：交易域 Granger 因果是统计因果验证（p-value 显著性），SPL 域用 TDR 相似度检索作为**代理（proxy）**——相似度高 ≠ 因果验证。此降级在 TDR 数据量不足时尤为显著。后续可通过引入因果推断方法（如 PC 算法/DoWhy）升级。

### 11.3 SPL 解题范式维度分类

> **风险标注**：交易域有明确的 3 维度（technical/fundamental/macro），SPL 域的维度分类需要新设计。这是集成的主要不确定性。

基于 session_memory 实际数据分析，定义 5 个解题范式维度：

| 维度 | 标识 | 定义 | 典型 session_memory 特征 |
|------|------|------|--------------------------|
| 代码驱动 | `code-driven` | 通过代码编写/修改解决问题 | actions 含"修改/创建/编辑/实现"等动词 |
| AI 驱动 | `ai-driven` | 通过 LLM/AI 能力解决问题 | actions 含"分析/生成/评估/推理"等动词 |
| 混合驱动 | `hybrid` | 代码 + AI 协同解决 | actions 同时含代码和 AI 动词 |
| 检索驱动 | `lookup` | 通过检索已有知识/案例解决 | actions 含"查询/检索/搜索/查找"等动词 |
| 调研驱动 | `research` | 通过深度调研/多源验证解决 | actions 含"调研/研究/验证/对比"等动词 |

**维度判定方法**：对 session_memory 的 `actions` 数组做关键词匹配 + 权重投票，输出主范式维度。

**待验证**：5 维度分类是否覆盖所有解题模式？是否需要更细粒度？冷启动期（TDR < 200 条）维度判定可能不稳定。

### 11.4 三个新增组件清单

| 组件 | 职责 | 输入 | 输出 | 依赖（SPL 已有） |
|------|------|------|------|-----------------|
| **SolutionPatternValidator** | 从 TDR 检索历史验证的解题范式，输出"过去主范式" G_dim_spl | TDR 检索结果 + query embedding | `G_dim_spl ∈ {code-driven, ai-driven, hybrid, lookup, research, none}`<br>`G_confidence ∈ [0,1]` | TDR + VQ-VAE Encoder |
| **PatternAggregator** | 从当前 query 的 VQ-VAE 编码中聚合注意力，输出"现在主范式" A_dim_spl | 当前 query VQ-VAE codebook + attention | `A_dim_spl ∈ {code-driven, ai-driven, hybrid, lookup, research}`<br>`A_strength ∈ [0,1]` | VQ-VAE Encoder |
| **CrossValidationGate** | 集成层：接收 G_dim_spl 和 A_dim_spl，执行交叉验证五步算法，输出置信调整 + 转移信号 + 质变事件 + 层权重动态调整 | `G_dim_spl`/`G_confidence`<br>`A_dim_spl`/`A_strength`<br>`DriftDetector` 输出 | `confidence_mult`<br>`shift_signal`<br>`divergence_count`<br>`quality_change`<br>`layer_weight_adjustment`<br>`retrain_trigger` | 上述两个适配器 + Drift Detector |

### 11.5 交叉验证五步算法（SPL 适配版）

```typescript
// 伪代码 — 仅供方案探讨，非实现
interface CrossValidationResult {
  confidence_mult: number;        // 置信倍数（一致 1.15 / 分歧 0.9）
  shift_signal: boolean;          // 模式转移信号
  divergence_count: number;       // 连续分歧期数
  quality_change: boolean;        // 质变确认
  new_main_dim: string | null;    // 质变后的新主范式
  layer_weight_adjustment: Record<string, number>;  // 层权重调整
  retrain_trigger: boolean;       // 重训练触发
}

class CrossValidationGateSPL {
  // 参数（均有理论边界，参考交易域 §10.4）
  persistence_threshold: number;  // 持续分歧期数阈值（默认 5，范围 [3, 20]）
  confidence_boost: number;        // 一致时置信加成（默认 1.15，范围 [1.0, 1.3]）
  confidence_penalty: number;      // 分歧时置信衰减（默认 0.9，范围 [0.7, 1.0]）
  layer_boost_rate: number;        // 层权重提升速率（默认 0.3，范围 [0.1, 0.5]）
  layer_decay_rate: number;        // 层权重衰减速率（默认 0.2，范围 [0.05, 0.3]）

  compare(
    G_dim_spl: string | null,      // 过去主范式（来自 SolutionPatternValidator）
    G_conf: number,                // 过去置信
    A_dim_spl: string | null,      // 现在主范式（来自 PatternAggregator）
    A_strength: number,            // 现在强度
    drift_detected: boolean        // DriftDetector 是否检测到漂移
  ): CrossValidationResult {
    // === Step 3: 交叉比对 ===
    if (G_dim_spl === null || A_dim_spl === null) {
      return this._neutralResult();  // FAIL-OPEN
    }

    let confidence_mult: number;
    let shift_signal: boolean;

    if (G_dim_spl === A_dim_spl) {
      confidence_mult = this.confidence_boost;
      shift_signal = false;
      this._divergence_count = 0;
    } else {
      confidence_mult = this.confidence_penalty;
      shift_signal = true;
      this._divergence_count += 1;
    }

    // === Step 4: 质变判定（持续分歧 + 模式漂移）===
    let quality_change = false;
    let retrain_trigger = false;
    let new_main_dim: string | null = null;

    if (this._divergence_count >= this.persistence_threshold) {
      if (drift_detected) {
        // 质变确认：范式排序变化 AND 模式漂移
        quality_change = true;
        retrain_trigger = true;
        new_main_dim = A_dim_spl;  // 接受当前范式为新主范式
        this._divergence_count = 0;
      }
    }

    // === Step 5: 层权重动态调整（仅分歧期间，质变前）===
    const layer_weight_adjustment: Record<string, number> = {};
    if (shift_signal && !quality_change) {
      const progress = Math.min(1.0, this._divergence_count / this.persistence_threshold);
      // 维度→层映射：code-driven→S层+DSH, ai-driven→LLM层, hybrid→C层+G层, lookup→S层, research→C层
      const A_layers = this._dimToLayers(A_dim_spl);
      const G_layers = this._dimToLayers(G_dim_spl);
      for (const layer of A_layers) {
        layer_weight_adjustment[layer] = 1 + this.layer_boost_rate * progress;
      }
      for (const layer of G_layers) {
        layer_weight_adjustment[layer] = 1 - this.layer_decay_rate * progress;
      }
      // Floor/ceiling 约束（防正反馈导致维度坍缩，参考交易域 §10.11 Q2）
      // 层权重范围 [0.5, 2.0]：不低于 0.5（保证各层最低参与度），不高于 2.0（防止单层主导）
      for (const layer in layer_weight_adjustment) {
        layer_weight_adjustment[layer] = Math.max(0.5, Math.min(2.0, layer_weight_adjustment[layer]));
      }
    }

    return {
      confidence_mult,
      shift_signal,
      divergence_count: this._divergence_count,
      quality_change,
      new_main_dim,
      layer_weight_adjustment,
      retrain_trigger,
    };
  }

  _neutralResult(): CrossValidationResult {
    return {
      confidence_mult: 1.0, shift_signal: false, divergence_count: this._divergence_count,
      quality_change: false, new_main_dim: null, layer_weight_adjustment: {}, retrain_trigger: false,
    };
  }

  _dimToLayers(dim: string): string[] {
    // 解题范式→训练层映射
    const mapping: Record<string, string[]> = {
      'code-driven': ['S', 'DSH'],
      'ai-driven': ['LLM'],
      'hybrid': ['C', 'G'],
      'lookup': ['S'],
      'research': ['C'],
    };
    return mapping[dim] || [];
  }
}
```

> **⚠️ 初始经验映射，待校准**：`_dimToLayers` 的维度→层映射基于经验设计，无数据驱动校准。校准方法：积累 200+ 质变事件后，用各层在质变前后的性能变化（如解决率/准确率）反向推断正确映射，通过 `verify` 更新。冷启动期使用此初始映射。

> **KL 散度阈值设定**：冷启动期使用经验阈值 0.15（与 Drift Detector 一致）；积累 500+ query 后，用历史 KL 散度分布的 P95 分位数动态校准阈值。

### 11.6 自进化闭环

```
① 质变事件触发重训练
   CrossValidationGate.retrain_trigger=True
     → TrainingLoop 触发（对应范式维度的层）
     → 新的 VQ-VAE codebook + TDR 更新
     → 新的 G_dim_spl（新的"过去"）
     → 下一次交叉验证使用新 G_dim_spl

② shift_signal → 层权重动态调整
   CrossValidationGate.layer_weight_adjustment
     → 5 TrainingLoops 权重更新
     → 下一次 query 时各层处理优先级受新权重影响
     → PatternAggregator 提取新 A_dim_spl
     → 形成"现在"链路的反馈闭环

③ 质变事件 → 认知记忆记录（CLAUDE.md 硬约束）
   record(content="[质变事件] G_dim_spl→A_dim_spl, drift={...}, divergence_count=N",
          quality_level="B", tags="质变,交叉验证,SPL,自进化,矛盾论")
   verify(memory_id=new_id, success=True)

④ 持续闭环
   质变 → 新过去 → 新交叉验证 → 新的现在 → 新的分歧/质变 → ...
   
   这是从"模仿"到"超越"的关键路径——质变后系统基于新范式重训练，
   不再局限于 Trae Code 的原始模式。
```

### 11.7 配置开关与 FAIL-OPEN

| 开关名 | 默认 | 作用 | 关闭时回退 |
|--------|------|------|-----------|
| `enable_cross_validation_gate` | `false` | 主开关 | CVG 不实例化，SPL 走 v0.3 原路径 |
| `enable_pattern_validator` | `false` | 过去范式提取 | G_dim_spl=null → CVG FAIL-OPEN |
| `enable_pattern_aggregator` | `false` | 现在范式提取 | A_dim_spl=null → CVG FAIL-OPEN |
| `enable_layer_weight_adjustment` | `false` | 层权重动态调整 | 不应用权重调整，交叉验证仍记录（用于日志） |

**FAIL-OPEN 链**：任何子组件异常 → 返回中性结果 `{confidence_mult: 1.0, shift_signal: false, layer_weight_adjustment: {}, retrain_trigger: false}` → SPL 走 v0.3 原路径。

### 11.8 与 CognitiveContextBuilder 集成

```
CognitiveContextBuilder（第 6 系统接入）

现有 5 系统：
  1. recall（认知记忆检索）
  2. RAG（知识库向量检索）
  3. index（索引系统）
  4. SKILL（技能候选）
  5. TDR（解题案例检索）—— v0.3 新增

新增第 6 系统：
  6. CVG（交叉验证）—— v0.4 新增
     输入：TDR 检索结果 + 当前 query VQ-VAE 编码
     输出：confidence_mult + layer_weight_adjustment
     作用：调整其他 5 系统的检索置信度和层权重

集成点：CognitiveContext 末尾新增 cvg_result 字段
  export interface CognitiveContext {
    experiences: CognitiveExperience[];
    knowledge: KnowledgeChunk[];
    references: IndexReference[];
    skill_candidates: SkillCandidate[];
    solution_cases: SolutionCase[];
    cvg_result: CrossValidationResult;  // v0.4 新增
  }
```

### 11.9 落地步骤（TDD，按可回退顺序）

| 步骤 | 组件 | TDD 红灯 | TDD 绿灯 | 可回退 |
|------|------|---------|---------|--------|
| Step 1 | PatternAggregator | 测试：输入 VQ-VAE 编码，输出 A_dim_spl | 实现：codebook 聚合 + 维度判定 | ✅ 开关控制 |
| Step 2 | SolutionPatternValidator | 测试：输入 TDR 检索结果，输出 G_dim_spl | 实现：TDR 检索 + 维度判定 | ✅ 开关控制 |
| Step 3 | CrossValidationGate 主体 | 测试：输入 G/A_dim + drift，输出交叉验证结果 | 实现：五步算法 | ✅ 主开关 |
| Step 4 | 层权重接入 | 测试：layer_weight_adjustment 应用到 TrainingLoop | 实现：TrainingLoop 权重更新 | ✅ 开关控制 |
| Step 5 | 自进化闭环连接 | 测试：质变→重训练→新 TDR 基线 | 实现：retrain_trigger → TrainingLoop → TDR 更新 | ✅ FAIL-OPEN |

### 11.10 与交易域架构的对应关系

| 交易域 §10 | SPL 域 §11 | 差异 |
|-----------|-----------|------|
| GrangerPipelineAdapter | SolutionPatternValidator | 因果验证→模式检索（SPL 无因果检验，用 TDR 检索代替） |
| AttentionAggregator | PatternAggregator | head 权重→VQ-VAE codebook 聚合 |
| CrossValidationGate | CrossValidationGateSPL | 维度不同（3→5），算法结构相同 |
| StructuralBreakDetector | DriftDetector | CUSUM+HMM+Hurst → KL 散度+EMA（SPL 已有） |
| head_multipliers | TrainingLoop 权重 | 8 head → 5 层 |
| 质变→Granger 重估 | 质变→重训练 | Granger 重估→TDR 重训练 |
| FTCEvolutionBridge | TrainingLoop trigger | 基因创新→层重训练 |

### 11.11 风险与缓解

| 风险 | 严重性 | 缓解方案 |
|------|--------|---------|
| SPL 解题范式 5 维度分类不完整 | **高** | 冷启动期收集 200+ session_memory 后做聚类验证；维度可扩展 |
| 质变检测的"结构性断裂"在 SPL 域定义不明确 | 中 | 用 Drift Detector 的 KL 散度 > 阈值 代替 CUSUM+HMM+Hurst |
| TDR 数据量不足导致交叉验证不稳定 | 中 | 冷启动期（TDR < 200）禁用 CVG，走 v0.3 原路径 |
| 过度设计风险 | 中 | 严格 FAIL-OPEN，4 个开关默认全 false，逐步验证 |
| 维度→层映射（_dimToLayers）可能不准确 | 中 | 初始映射基于经验，可通过实践 verify 后调整 |

### 11.12 验收标准（待验证目标）

| 编号 | 验收项 | 目标 | 验证方法 |
|------|--------|------|---------|
| V20 | 交叉验证层集成 | CVG 4 开关可控，关闭时 SPL 走 v0.3 原路径 | 开关测试 |
| V21 | FAIL-OPEN | 任何子组件异常 → 中性结果 → SPL 不报错 | 异常注入测试 |
| V22 | 质变检测准确率 | **探索性指标**（非硬验收）：质变事件中 ≥70% 确实伴随解题范式转移 | 人工标注验证（标注协议：2 人独立标注，Cohen's κ ≥ 0.6 为可接受一致率；冷启动期不强制） |
| V23 | 自进化闭环 | 质变→重训练→新 TDR 基线→新交叉验证 闭环可运行 | 端到端集成测试 |
| V24 | 维度分类覆盖率 | 5 维度覆盖 ≥90% 的 session_memory 样本 | 数据标注验证；未覆盖样本（<10%）归入 other 类别，不强制分类，积累后扩展第 6 维度 |

---

## 12. 风险与缓解

| 风险 | 等级 | 缓解方案 |
|------|------|----------|
| Trae Code 沉淀含噪音 | 高 | 质量闸门（B+ 入 TDR，C 入 RAG，D 丢弃）+ learned 字段非空过滤 |
| TDR 冷启动为空 | 中 | 降级原路径 B + 历史导入（7 天 session_memory 批量） |
| VQ-VAE codebook 塌缩 | 中 | 码字使用率 < 1/256 → 重置 + rotation-augmented 量化 |
| 高频使用性能瓶颈 | 中 | Jaccard 倒排索引 O(1) + 精排仅 top-K + 训练全异步 |
| 跨域泛化（交易 vs 通用编程） | 低 | codebook 领域专属训练（只用 dreambuddy-v2 项目的 session_memory） |
| Trae Code 记忆格式变更 | 低 | Bridge 做格式版本检测 + 优雅降级 |
| Baseline 采集不完整 | 中 | session_memory 缺字段时 baseline_output 标注 null，评估时跳过 |
| 各层训练依赖链阻塞 | 中 | S+G 并行启动，冷启动期间降级原路径 |
| 全链路联调一致率不达标 | 中 | 逐层验收，单层达标后再联调，降级链保留 |

---

## 13. 关联文档

- [SPEC-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md](../../1-ARCHITECTURE/SPEC-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md) — 意图识别训练闭环（S层训练基础）
- [SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md](../../1-ARCHITECTURE/dream-harness-bridge/SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md) — 算法驱动+训练闭环
- [v3-frontend-architecture.md](./v3-frontend-architecture.md) — 前端架构总览
- [skill-orchestration-executor.ts](../src/lib/skill-orchestration-executor.ts) — 编排执行器
- [cognitive-context-builder.ts](../src/lib/cognitive-context-builder.ts) — 认知上下文构建
- [imitation-counter.ts](../src/lib/imitation-counter.ts) — 模仿计数器

## 14. 学术参考

> **v0.3 修正**：删除 iCLP (arXiv:2512.24014) 和 STAR 两条不可验证引用，VQ-VAE 改引经典原论文，Online-LoRA 替换为标准统计技术（KL 散度 + EMA）。

| 编号 | 引用 | 来源 | 用途 | 验证状态 |
|------|------|------|------|----------|
| R1 | Memento: Non-parametric Case Bank + Soft Q-Learning | arXiv:2508.16153 (UCL+华为, 2025.08) | CBR 在线学习 + Soft Q 参数初始化 | ✅ 已验证 |
| R2 | Neural Discrete Representation Learning (VQ-VAE) | van den Oord et al., NeurIPS 2017 | 四元组→离散 codebook 编码 | ✅ 经典高引 |
| R3 | Agent-R: MCTS error trajectory correction | arXiv:2501.11425 (复旦+字节, 2025.01) | 失败轨迹→修正样本，及时反思 | ✅ 已验证 |
| R4 | Product Quantization for Nearest Neighbor Search (PQ) | Jégou et al., IEEE TPAMI 2011 | 无梯度 codebook 可行性论证依据 | ✅ 经典高引 |
| R5 | KL 散度 + 指数移动平均（EMA）| 标准统计/信号处理技术 | 漂移检测 + codebook EMA 更新 | ✅ 标准技术 |

**删除条目**：
- ~~iCLP: VQ-VAE discrete codebook for plan encoding (arXiv:2512.24014, 2025)~~ — Web 搜索不可验证
- ~~STAR: Rotation-augmented quantization for codebook collapse prevention~~ — Web 搜索不可验证
- ~~Online-LoRA: Task-free online continual learning (WACV 2025)~~ — 改用标准 KL 散度 + EMA（R5）

## 15. 变更日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-10-09 | 初版：Case Bank + VQ-VAE + Case Retriever + Reflection + Drift Detector |
| v0.2 | 2026-10-09 | 全链路训练蒸馏：Case Bank→TDR；新增5个层专属TrainingLoop；新增Baseline采集+评估层；目标从"检索辅助"升级为"全链路复现并超越Trae Code" |
| v0.3 | 2026-10-09 | 同行评审(4角色+7模式)修订：①session_memory四元组对齐实际格式(intent,actions,outcome,learned)；②删除不可验证引用(iCLP/STAR)改用VQ-VAE原论文+PQ；③VQ-VAE轻量方案论证(k-means+++EMA公式+R4 PQ依据)；④复现/超越标准改可度量指标(语义一致率/编辑距离/覆盖率)；⑤各层桶满阈值差异化(S=100/DSH=50/C=50/G=30/LLM=30)；⑥验收阈值降级为"目标，待验证"；⑦增加TDR容量规划(10000上限+LRU+质量加权)；⑧修复质量闸门矛盾(有learned即入库)；⑨修复硬编码skill_ids(plan.skill_ids\|\|['simple_qa']) |
| v0.4 | 2026-10-09 | 集成交叉验证层（矛盾论+Transformer域迁移）：新增§11——CrossValidationGate for SPL + SolutionPatternValidator + PatternAggregator + 质变→重训练闭环；SPL解题范式5维度分类(code-driven/ai-driven/hybrid/lookup/research)；CognitiveContextBuilder第6系统接入；从'模仿'升级为'矛盾感知自进化'；4开关FAIL-OPEN默认false；新增V20-V24验收标准 |
| v0.4.1 | 2026-10-09 | 同行评审勘误7项(3Major+4Minor)：Granger降级声明;_dimToLayers待校准;V22探索性+Cohen'sκ;KL阈值方法;V24未覆盖策略;层权重floor/ceiling[0.5,2.0];超越度量指标 |

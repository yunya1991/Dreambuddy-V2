# SPEC-20261011-v0.5 — 持续算法驱动训练架构（Continual Algorithm-Driven Training）

> **版本**: v0.5-revised
> **日期**: 2026-10-11
> **作者**: Trae + User
> **状态**: 评审通过（6 Major + 6 Minor 全部修复，7 模式阻断 2 项补全）→ 待实施
> **关联**: SPEC-20261011 v0.2（双模式学习训练架构）, SPL v0.4, dream-acceptance-verify v1.1.0
> **方法论**: recall → 三域调研（传统金融+AI训练+GitHub生态）→ 综合评估 → SPEC v0.5 → 同行评审 → 修复 → v0.5-revised
> **变更性质**: v0.2 的训练触发机制升级 — 从"桶满→全量训练→清空"升级为"持续算法驱动训练"
> **评审修复**: M1(EWC→规则权重衰减) + M2(DriftDetector适配层) + M3(每层trainIncremental伪代码) + M4(checkpoint存储格式) + M6(迁移策略+冷启动) + m6(λ/DECAY_RATE关系) + #3(因果链) + #5(冷启动)

---

## 0. Executive Summary

### 0.1 核心命题

SPL 5 层训练循环的触发机制从**离散批量学习（Batch Learning）**升级为**持续算法驱动训练（Continual Algorithm-Driven Training）**。

| 维度 | v0.2（当前） | v0.5（优化后） |
|------|-------------|---------------|
| **训练范式** | 批量学习（Batch Learning） | 持续学习（Continual Learning） |
| **数据容器** | 桶（Bucket），满即清空 | Replay Buffer，永不清空，循环覆盖 |
| **触发机制** | 桶满50条→全量训练 | 三层触发：微批增量 + 漂移回调 + 优先级触发 |
| **训练方法** | 全量重算→清空→从零开始 | 增量更新（EWMA衰减）+ 保留模型状态 |
| **模型状态** | 内存中，重启丢失 | 持久化到 TDR/SQLite，可恢复 |
| **数据权重** | 所有案例等同 | 质量权重（S/A/B/C）+ 时间衰减 |
| **驱动方** | 外部调用 run_active_training() | 算法自驱动（数据到达即学习） |

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | 桶不满=不训练，S层4/50时永远不触发 | 主动训练实测 |
| F2 | 训练后清空桶=主动制造灾难性遗忘 | AI训练域共识 |
| F3 | 阈值固定不自适应，不随数据质量/到达频率调整 | 评估发现 |
| F4 | S级案例和C级案例等同入桶，高价值被淹没 | 评估发现 |
| F5 | 无时间衰减，1个月前案例和今天权重相同 | 评估发现 |
| F6 | 触发被动，需外部调用，训练循环不自驱动 | 评估发现 |
| F7 | 用户洞察：训练应该是持续的，被算法驱动 | 用户反馈 |
| F8 | 三域调研共识：桶→Buffer + 漂移触发 + 增量更新 + 持久化 | 多域调研 |

### 0.3 范围边界

**In Scope:**
- 5 层训练循环（S/DSH/C/G/LLM）的 Bucket → Replay Buffer 改造
- 新增 `trainIncremental()` 增量训练方法
- 三层触发机制（微批 + 漂移 + 优先级）
- 模型状态持久化（checkpoint + restore）
- API 扩展（action: incremental/checkpoint/restore）
- FeedbackLoop 扩展（调优 microBatch + capacity + λ）
- EWMA 时间衰减权重

**Out of Scope:**
- 不修改 5 层训练循环的核心算法逻辑（TF-IDF/路径挖掘/CBR/图映射/Prompt聚类）
- 不引入深度学习（不引入神经网络权重微调）
- 不修改认知系统 4-MEMORY 后端
- 不修改 33-REA 核心解析逻辑
- 不修改数据源采集器（P2 已完成的 5 个 collector 不变）

---

## 1. 三域调研结论

### 1.1 传统金融域

| 洞察 | 来源 | 迁移价值 |
|------|------|---------|
| Two Sigma: 每天/每周重训练 + 100+模型 ensemble + regime 感知切换 | 量化基金实践 | ensemble 思路可用于多模型并行训练 |
| Renaissance: 5分钟切片 + HMM 隐马尔可夫识别非随机模式 | Medallion 基金 | HMM k=3 可用于 regime gate |
| 贝叶斯在线学习: `Prior_today = Posterior_yesterday` | 金融首选持续学习范式 | 天然防遗忘，小样本友好，可作 S 层增量算法 |
| CUSUM + Page-Hinkley 检测漂移 | 工业标准 | 替代桶满作为训练触发器 |
| EWMA λ=0.95 衰减权重 | 日频/月频主流 | 替代 `this.bucket = []` 的清空操作 |
| Experience Replay Buffer + PER | DRL 交易系统 | 固定容量 + 优先级采样防遗忘 |
| Regime gate: regime 变化时不盲目重训练 | ReCAP 框架 (KDD 2026) | 漂移触发时先检查 regime 再决定动作 |

**关键原则**：先检测 regime，再决定动作。regime 变化时盲目重训练会加剧过拟合（新 regime 数据不足），应先降级/切换/禁用。

### 1.2 AI 训练域

| 洞察 | 来源 | 迁移价值 |
|------|------|---------|
| Online Learning: `learn_one(x,y)` 单样本即时更新 | River/在线学习理论 | 每条数据到达即学习，不等桶满 |
| Mini-batch SGD: 32-128，online 场景可降至 8-16 | 深度学习实践 | 微批量大小参考 |
| Experience Replay Buffer: 10k-50k（简单系统） | DQN/DRL | buffer 容量设计参考 |
| Prioritized Experience Replay (PER): alpha=0.6, beta=0.4→1.0 | DQN 改进 | 优先级采样参数参考 |
| Rehearsal-based: 简单系统最优选 | Continual Learning 三大方法族对比 | 我们的系统首选 rehearsal |
| EWC 正则化: `λ·Σ F_i·(θ_i-θ*_i)²` | Elastic Weight Consolidation | C 层防旧规则被新反思覆盖 |
| Catastrophic Forgetting: 清空桶=主动制造遗忘 | Continual Learning 核心问题 | 直接解释为何不能清空桶 |
| Checkpoint: weights + optimizer_state + step + drift_flag | PyTorch 最佳实践 | 模型状态持久化字段设计 |

### 1.3 GitHub 生态域

| 洞察 | 来源 | 迁移价值 |
|------|------|---------|
| River: `learn_one(x,y)` / `predict_one(x)` API 分离 | online-ml/river | 预测不污染状态，学习原地更新 |
| River: 内置 ADWIN/Page-Hinkley drift detector | River 标准组件 | 漂移检测器作为独立组件，回调触发重训练 |
| RLlib: `PrioritizedReplayBuffer{capacity, alpha, beta}` | Ray RLlib | buffer 永不清空，循环覆盖 + 优先级采样 |
| ADWIN: 变长窗口 W0/W1 均值差比较 | scikit-multiflow | 比我们现有 KL 散度更自适应 |
| PyTorch checkpoint: 必须存 optimizer_state + RNG | PyTorch 最佳实践 | 仅存 weights 会丢 Adam 动量 |
| partial_fit vs fit 分离 | scikit-multiflow | 增量训练与全量训练 API 分离 |
| MLflow: `log_metric(step=N)` + Model Registry | MLflow | 每次增量训练的 metrics 追踪 |

### 1.4 跨域共识

| 变更方向 | 传统金融 | AI训练 | GitHub生态 | 共识度 |
|---------|---------|--------|-----------|--------|
| 桶→Replay Buffer | experience replay + PER | rehearsal-based (最简有效) | RLlib PrioritizedReplayBuffer | ★★★★★ |
| 桶满→漂移触发 | CUSUM + Page-Hinkley | ADWIN + concept drift | River ADWIN 变长窗口 | ★★★★★ |
| 清空→增量更新 | 贝叶斯在线学习 / EWMA | EWC正则化 + replay | partial_fit / learn_one | ★★★★★ |
| 模型状态持久化 | checkpoint | state_dict + optimizer | PyTorch checkpoint | ★★★★ |

---

## 2. 当前分桶机制问题分析

### 2.1 当前架构

```
数据源(5 collectors) → TrainingCase → TSHTTPTrainingExecutor.add_case()
  → POST /api/training/{layer} action=add
  → 前端训练循环 addTrainingData() → bucket.push(data)
  → if bucket.length >= threshold → train() → bucket = [] (清空)
```

### 2.2 问题矩阵

| # | 问题 | 现状 | 影响 | 三域依据 |
|---|------|------|------|---------|
| P1 | 间歇性训练 | 桶不满=不训练 | S层4/50时永远不触发 | 金融: 信息延迟最长50条 |
| P2 | 训练后清空桶 | `this.bucket = []` | 每次从零开始，灾难性遗忘 | AI: 清空=主动制造遗忘 |
| P3 | 阈值固定 | S=50/DSH=50/G=60/LLM=30 | 不随数据质量/频率自适应 | 三域: 都推荐自适应 |
| P4 | 无优先级 | S级和C级等同入桶 | 高价值被低价值淹没 | AI: PER 按优先级采样 |
| P5 | 无时间衰减 | 1月前和今天权重相同 | 旧模式不再适用 | 金融: EWMA 衰减 |
| P6 | 触发被动 | 需外部调用 | 训练循环不自驱动 | GitHub: River learn_one 自驱动 |

### 2.3 真实案例佐证

2026-10-11 SPL 主动训练实测：
- S层: 100条数据 → trained=true, accuracy=0.18
- 训练后桶清空 → 下次训练从零开始
- 如果只有4条S层数据 → 永远不触发训练（4 < 50）
- S级高价值案例和C级低价值案例在桶中权重相同

---

## 3. 优化架构设计

### 3.1 架构总览

```
┌──────────────────────────────────────────────────────────┐
│              SPL v0.5: 持续算法驱动训练架构                  │
│                                                            │
│  数据源(5 collectors, 不变)                                  │
│    ↓                                                       │
│  Replay Buffer (capacity-bounded, 永不清空)                  │
│    ↓                                                       │
│  三层触发机制:                                               │
│    ① 微批增量 (每N条 → trainIncremental, EWMA更新)           │
│    ② 漂移回调 (DriftDetector KL>0.15 → train, 保留baseline)  │
│    ③ 优先级触发 (quality=S → 立即trainIncremental)           │
│    ↓                                                       │
│  模型状态 + Checkpoint (持久化到 TDR/SQLite)                  │
│                                                            │
│  FeedbackLoop: 调优 microBatch + capacity + λ              │
└──────────────────────────────────────────────────────────┘
```

### 3.2 Replay Buffer（P0 核心）

**替代**: `bucket: TrainingData[]` → `buffer: ReplayBuffer`

```typescript
/**
 * Replay Buffer — 永不清空的训练数据缓冲区
 *
 * 设计借鉴:
 *   - RLlib PrioritizedReplayBuffer (capacity + 优先级采样)
 *   - DQN Experience Replay (固定容量 + 循环覆盖)
 *   - 金融 EWMA 衰减 (旧数据权重渐淡)
 */

interface BufferEntry {
  data: TrainingData;           // 原始训练数据
  quality: QualityLevel;        // S | A | B | C
  weight: number;               // 质量权重 (S=1.0, A=0.8, B=0.5, C=0.2)
  timestamp: number;            // 到达时间 (Date.now())
  age: number;                  // 在 buffer 中的训练轮次 (初始0, 每次训练后++)
  decayedWeight: number;        // 衰减后权重 = weight × exp(-age × DECAY_RATE)
}

class ReplayBuffer {
  private entries: BufferEntry[] = [];
  private capacity: number;       // 最大容量
  private microBatchSize: number; // 微批量大小
  private ewmaLambda: number;     // EWMA 衰减率 (默认0.95)

  // 各层差异化容量
  static LAYER_CAPACITY = {
    S: 200,    // 意图识别: 需要快速响应，容量适中
    DSH: 300,  // 执行路径: 模式挖掘需要更多样本
    C: 200,    // 反思: 规则蒸馏，容量适中
    G: 500,    // 图结构: 拓扑稳定，容量大
    LLM: 100,  // Prompt优化: 变化快，容量小
  };

  static LAYER_MICRO_BATCH = {
    S: 5,      // 意图识别: 微批量小，快速响应
    DSH: 10,   // 执行路径: 需要更多样本发现模式
    C: 10,     // 反思: 增量蒸馏
    G: 15,     // 图结构: 变化慢，微批量稍大
    LLM: 5,    // Prompt: 变化快，微批量小
  };

  static DECAY_RATE = 0.05;  // EWMA 衰减率, weight *= exp(-age × 0.05)

  /**
   * 添加数据到 buffer
   * 超过 capacity → 淘汰 age 最大 + decayedWeight 最小的条目
   */
  add(data: TrainingData, quality: QualityLevel): void;

  /**
   * 优先级采样（评审修复 m3: 明确算法）
   * 按 decayedWeight 比例随机采样 batchSize 条（不是 Top-K）
   * 使用轮盘赌算法: weight 越大被选中概率越高
   * 避免总是采样高权重条目，保证低权重也有机会被采样
   */
  sample(batchSize: number): BufferEntry[];

  /**
   * 全量数据（用于全量重训练）
   */
  getAll(): BufferEntry[];

  /**
   * 衰减所有条目
   * 每次训练后调用: age++, weight *= exp(-DECAY_RATE)
   */
  decayAll(): void;

  /**
   * 获取当前大小
   */
  get size(): number;

  /**
   * 获取统计信息
   */
  getStats(): {
    size: number;
    capacity: number;
    avgWeight: number;
    oldestAge: number;
    qualityDistribution: Record<QualityLevel, number>;
  };
}
```

### 3.3 增量训练方法（P0）

**新增**: `trainIncremental(batch)` — 不清空 buffer，增量更新模型

```typescript
/**
 * 增量训练 — 用 batch 更新现有模型，保留历史状态
 *
 * 设计借鉴:
 *   - River learn_one: 原地更新，不清空
 *   - 金融 EWMA: 旧权重衰减，新权重叠加
 *
 * @param batch 从 buffer 中采样的微批量数据
 * @returns 训练结果
 */
trainIncremental(batch: TrainingData[]): TrainingResult {
  // 1. 用 batch 做增量更新（不从零算，层专属算法见 §3.3.1-3.3.5）
  // 2. buffer.decayAll() — 旧数据权重衰减
  // 3. 保留模型状态，不清空
  // 4. 更新训练步数 step++
  // 5. 每 N 次增量后 checkpoint()
}
```

#### 3.3.1 S 层 trainIncremental — TF-IDF 增量更新

```typescript
// S层: 意图分类的 TF-IDF 频率表增量更新
trainIncremental_S(batch: TrainingData[]): TrainingResult {
  for (const data of batch) {
    const { message, intent_type } = data;

    // 1. 增量更新词频表: term_freq[term] += 1
    for (const term of tokenize(message)) {
      this.termFreq[term] = (this.termFreq[term] || 0) + 1;
    }

    // 2. 增量更新文档频率: doc_freq[term] += 1（新文档到达）
    //    IDF = log(N_docs / (1 + doc_freq[term]))
    this.docCount++;
    const seen = new Set(tokenize(message));
    for (const term of seen) {
      this.docFreq[term] = (this.docFreq[term] || 0) + 1;
    }

    // 3. 增量更新意图频率: intent_freq[intent_type] += 1
    this.intentFreq[intent_type] = (this.intentFreq[intent_type] || 0) + 1;
  }

  // 4. EWMA 衰减旧权重（不是清空）
  //    weights[intent] = λ × new_evidence + (1-λ) × weights[intent]
  for (const intent of Object.keys(this.intentFreq)) {
    const newEvidence = this.intentFreq[intent] / this.docCount;
    this.weights[intent] = this.ewmaLambda * newEvidence
      + (1 - this.ewmaLambda) * (this.weights[intent] || 0);
  }

  // 5. 重新计算 TF-IDF（增量，只重算受影响的 term）
  //    不清空，只更新
  this.step++;
  return { layer: 'S', success: true, metrics: { step: this.step, intent_count: Object.keys(this.weights).length } };
}
```

#### 3.3.2 DSH 层 trainIncremental — 路径频率统计增量

```typescript
// DSH层: 执行路径的频率统计 + 模板权重增量更新
trainIncremental_DSH(batch: TrainingData[]): TrainingResult {
  for (const data of batch) {
    const { task, node_sequence, outcome } = data;

    // 1. 路径签名: pathSignature = node_sequence.join('→')
    const pathSig = node_sequence.join('→');

    // 2. 增量更新路径频率: path_freq[pathSig] += 1
    this.pathFreq[pathSig] = (this.pathFreq[pathSig] || 0) + 1;

    // 3. 增量更新路径模板权重
    //    模板权重 = 路径频率 × outcome 成功率
    const successBonus = outcome === 'success' ? 1.0 : (outcome === 'partial' ? 0.5 : 0.1);
    this.templateWeight[pathSig] = this.pathFreq[pathSig] * successBonus;
  }

  // 4. EWMA 衰减旧模板权重（不是清空）
  for (const path of Object.keys(this.templateWeight)) {
    this.templateWeight[path] *= this.ewmaLambda;  // λ=0.95, 旧模板渐淡
  }

  // 5. 保留模板（权重低于阈值的标记为"候选淘汰"，但不立即删除）
  //    避免历史路径完全消失
  this.step++;
  return { layer: 'DSH', success: true, metrics: { step: this.step, path_count: Object.keys(this.pathFreq).length } };
}
```

#### 3.3.3 C 层 trainIncremental — 规则权重衰减 + 保留阈值

> **评审修复 M1**: 原 SPEC 使用 EWC（Fisher 矩阵正则化），但 C 层是 CBR + 规则蒸馏的非参数化系统，
> 无法计算 Fisher 信息矩阵。改为更简单的"规则权重衰减 + 保留阈值"方案：
> 每条规则有 weight，增量训练时旧规则 weight 衰减，新规则加入，
> weight 低于 RETENTION_THRESHOLD 时才从活跃规则集中移除（但保留在历史档案中）。

```typescript
// C层: 反思规则的增量蒸馏 + 权重衰减防遗忘
trainIncremental_C(batch: TrainingData[]): TrainingResult {
  const RETENTION_THRESHOLD = 0.05;  // 低于此权重的规则从活跃集移除

  for (const data of batch) {
    const { context_summary, action_taken, outcome, expected_decision } = data;

    // 1. 从新案例蒸馏新规则
    const newRule = {
      context: context_summary,
      action: action_taken,
      expected: expected_decision,
      outcome: outcome,
    };

    // 2. 检查是否已有相似规则（Jaccard 相似度 > 0.7）
    const existingRule = this.findSimilarRule(newRule, 0.7);

    if (existingRule) {
      // 2a. 相似规则存在: 增强其权重（reinforcement）
      existingRule.weight = existingRule.weight * this.ewmaLambda + 0.1;
      existingRule.support_count++;
    } else {
      // 2b. 新规则: 加入活跃规则集，初始权重 = 1.0
      this.rules.push({ ...newRule, weight: 1.0, support_count: 1 });
    }
  }

  // 3. EWMA 衰减所有规则权重（防遗忘: 不删除，只衰减）
  for (const rule of this.rules) {
    rule.weight *= this.ewmaLambda;  // λ=0.90, 旧规则渐淡
  }

  // 4. 保留阈值: 低于阈值的移到历史档案（不从系统中删除）
  const active = this.rules.filter(r => r.weight >= RETENTION_THRESHOLD);
  const archived = this.rules.filter(r => r.weight < RETENTION_THRESHOLD);
  this.ruleArchive.push(...archived);  // 保留在档案中，可恢复
  this.rules = active;

  this.step++;
  return { layer: 'C', success: true, metrics: { step: this.step, active_rules: this.rules.length, archived: this.ruleArchive.length } };
}
```

#### 3.3.4 G 层 trainIncremental — 图结构增量更新

```typescript
// G层: 决策→图映射的增量节点/边添加 + 权重衰减
trainIncremental_G(batch: TrainingData[]): TrainingResult {
  const ORPHAN_THRESHOLD = 0.02;  // 孤立节点权重低于此值时标记为"待清理"

  for (const data of batch) {
    const { decisions, rules } = data;

    // 1. 增量添加节点（决策→节点）
    for (const decision of decisions) {
      if (!this.graph.nodes[decision]) {
        this.graph.nodes[decision] = { weight: 1.0, edges: [] };
      } else {
        this.graph.nodes[decision].weight += 0.1;  // 增强已存在节点
      }
    }

    // 2. 增量添加边（规则→边）
    for (const rule of rules) {
      const [src, dst] = this.parseRuleEdge(rule);
      if (src && dst) {
        const edgeKey = `${src}→${dst}`;
        if (!this.graph.edges[edgeKey]) {
          this.graph.edges[edgeKey] = { weight: 1.0, source: src, target: dst };
          // 更新邻接表
          this.graph.nodes[src]?.edges.push(edgeKey);
        } else {
          this.graph.edges[edgeKey].weight += 0.1;
        }
      }
    }
  }

  // 3. EWMA 衰减所有节点/边权重（拓扑保留，只衰减权重）
  for (const node of Object.values(this.graph.nodes)) {
    node.weight *= this.ewmaLambda;  // λ=0.99, 图结构变化慢，衰减慢
  }
  for (const edge of Object.values(this.graph.edges)) {
    edge.weight *= this.ewmaLambda;
  }

  // 4. 拓扑一致性检查: 不删除节点（避免断边），只标记低权重
  for (const [id, node] of Object.entries(this.graph.nodes)) {
    if (node.weight < ORPHAN_THRESHOLD && node.edges.length === 0) {
      node.orphan = true;  // 标记为孤立，但不删除（可恢复）
    }
  }

  this.step++;
  return { layer: 'G', success: true, metrics: { step: this.step, node_count: Object.keys(this.graph.nodes).length, edge_count: Object.keys(this.graph.edges).length } };
}
```

#### 3.3.5 LLM 层 trainIncremental — Prompt 模式增量 + KL 约束

```typescript
// LLM层: Prompt 模式聚类增量 + 旧模板 KL 散度约束
trainIncremental_LLM(batch: TrainingData[]): TrainingResult {
  const SIMILARITY_THRESHOLD = 0.8;  // 余弦相似度阈值

  for (const data of batch) {
    const { intent, learned, outcome, prompt_pattern } = data;

    // 1. 计算新 prompt 与现有模板的相似度
    const newEmbedding = this.embed(prompt_pattern);
    let bestMatch = null;
    let bestSim = 0;

    for (const template of this.promptTemplates) {
      const sim = cosineSimilarity(newEmbedding, template.embedding);
      if (sim > bestSim) {
        bestSim = sim;
        bestMatch = template;
      }
    }

    if (bestMatch && bestSim > SIMILARITY_THRESHOLD) {
      // 2a. 相似模板存在: 增强其权重
      bestMatch.weight = bestMatch.weight * this.ewmaLambda + 0.1;
      bestMatch.usage_count++;
    } else {
      // 2b. 新模板: 加入模板库
      this.promptTemplates.push({
        pattern: prompt_pattern,
        embedding: newEmbedding,
        intent: intent,
        weight: 1.0,
        usage_count: 1,
      });
    }
  }

  // 3. KL 散度约束: 新旧模板的分布差异不应太大
  //    如果新 batch 导致模板分布剧变，降低学习率
  const newDist = this.computeTemplateDistribution();
  const kl = this.klDivergence(this.lastDistribution || newDist, newDist);
  const effectiveLambda = kl > 0.3 ? this.ewmaLambda * 0.5 : this.ewmaLambda;  // KL过大则降速

  // 4. EWMA 衰减旧模板权重
  for (const template of this.promptTemplates) {
    template.weight *= effectiveLambda;  // λ=0.90
  }
  this.lastDistribution = newDist;

  this.step++;
  return { layer: 'LLM', success: true, metrics: { step: this.step, template_count: this.promptTemplates.length, kl_divergence: kl } };
}
```

#### 3.3.6 各层增量训练策略汇总

| 层 | 增量策略 | 防遗忘机制 | 保留阈值 | 借鉴 |
|---|---|---|---|---|
| S（意图） | TF-IDF 频率表增量更新 + EWMA 权重 | 频率表保留历史，不清空 | N/A（频率表不清除） | River learn_one + 金融 EWMA |
| DSH（路径） | 路径频率统计增量 + 模板权重衰减 | 旧模板权重渐淡但不清除 | 低于阈值标记候选淘汰 | DQN replay buffer |
| C（反思） | 新增规则 + 规则权重衰减 | 旧规则衰减不移入档案 | weight < 0.05 → 移入档案 | ~~EWC~~ → 规则权重衰减 (M1 修复) |
| G（图） | 增量添加节点/边 + 权重衰减 | 拓扑保留，只衰减权重 | 孤立节点标记不删除 | 金融 expanding window |
| LLM（Prompt） | 新增模板 + KL 约束 + 权重衰减 | KL 约束 + 旧模板渐淡 | N/A | AI 知识蒸馏 |

> **评审修复 M1**: C 层原使用 EWC（Fisher 矩阵），但非参数化系统无法计算 Fisher 信息矩阵。
> 改为"规则权重衰减 + 保留阈值"——旧规则 weight 随训练轮次衰减，低于 RETENTION_THRESHOLD(0.05)
> 时移入 ruleArchive（历史档案，可恢复），但不从系统中完全删除。效果等同于 EWC 的"重要参数保护"，
> 但实现简单，不依赖梯度/Fisher 计算。

### 3.4 三层触发机制（P1）

**变更**: `addTrainingData()` 内置三层触发逻辑

```typescript
/**
 * 添加训练数据 + 触发训练
 *
 * 三层触发:
 *   ① 微批增量: 每N条 → trainIncremental()
 *   ② 漂移回调: DriftDetector KL > 阈值 → train() (全量，保留baseline)
 *   ③ 优先级: quality=S → 立即 trainIncremental()
 *
 * 冷启动守卫（评审修复 #5）:
 *   - buffer.size == 0 时不触发微批（0 % N == 0 但无数据）
 *   - buffer.size < microBatchSize 时不触发（warmup 期）
 *   - restore() 返回 null 时首次训练为冷启动
 */
addTrainingData(data: TrainingData, quality?: QualityLevel): void {
  const q = quality || 'C';  // M5修复: quality 可选，默认 'C'
  this.buffer.add(data, q);

  // 触发层3: 优先级触发（S级立即，不受 warmup 限制）
  if (q === 'S') {
    this.trainIncremental([data]);
    this.maybeCheckpoint();
    return;
  }

  // 冷启动守卫: buffer 数据量不足时不触发微批
  if (this.buffer.size < this.microBatchSize) {
    return;  // warmup 期，等待数据积累
  }

  // 触发层1: 微批增量（每N条，且 size > 0）
  if (this.buffer.size > 0 && this.buffer.size % this.microBatchSize === 0) {
    const batch = this.buffer.sample(this.microBatchSize);
    this.trainIncremental(batch);
    this.maybeCheckpoint();
    return;
  }

  // 触发层2: 漂移触发（DriftDetector 通过适配层检测）
  if (this.driftAdapter) {
    const driftResult = this.driftAdapter.detectDrift(this.getModelSnapshot());
    if (driftResult.drift_detected) {
      // 全量重训前先 checkpoint 旧模型作 baseline（可回滚）
      this.checkpoint();  // m4修复: 明确 baseline 含义
      this.train();       // 全量重训
      this.driftAdapter.reset();
    }
  }
}
```

#### 3.4.1 DriftDetector 适配层（评审修复 M2）

> **评审修复 M2**: 现有 DriftDetector 检测的是 codebook 索引分布（数值数组），
> 但 5 层数据格式各异（TF-IDF 表/路径序列/规则字典/图结构/Prompt 字符串）。
> 新增 `DriftDetectorAdapter` 适配层，将各层模型状态转换为分布向量再检测。

```typescript
/**
 * DriftDetector 适配层 — 将各层模型状态转换为可检测的分布向量
 *
 * 各层转换策略:
 *   S层:  intent_freq 分布 → [freq_intent1, freq_intent2, ...] 概率向量
 *   DSH:  path_freq 分布 → Top-K 路径频率向量
 *   C层:  rule_outcome 分布 → {success: N, partial: M, failure: K} 概率向量
 *   G层:  node_degree 分布 → 度数直方图
 *   LLM:  template_usage 分布 → 模板使用频率向量
 */
class DriftDetectorAdapter {
  private detector: DriftDetector;  // 现有 KL 散度检测器
  private layer: TrainingLayer;

  /**
   * 将模型状态快照转换为分布向量
   */
  private toDistribution(modelSnapshot: any): number[] {
    switch (this.layer.value) {
      case 'S':
        // S层: intent 频率 → 概率向量
        const intentFreqs = Object.values(modelSnapshot.intentFreq || {});
        const total = intentFreqs.reduce((a, b) => a + b, 0) || 1;
        return intentFreqs.map(f => f / total);

      case 'DSH':
        // DSH: Top-K 路径频率
        const pathEntries = Object.entries(modelSnapshot.pathFreq || {})
          .sort(([, a], [, b]) => b - a)
          .slice(0, 20);
        const pathTotal = pathEntries.reduce((s, [, f]) => s + f, 0) || 1;
        return pathEntries.map(([, f]) => f / pathTotal);

      case 'C':
        // C层: rule outcome 分布
        const outcomes = { success: 0, partial: 0, failure: 0 };
        for (const rule of modelSnapshot.rules || []) {
          outcomes[rule.outcome] = (outcomes[rule.outcome] || 0) + 1;
        }
        const cTotal = outcomes.success + outcomes.partial + outcomes.failure || 1;
        return [outcomes.success / cTotal, outcomes.partial / cTotal, outcomes.failure / cTotal];

      case 'G':
        // G层: 节点度数直方图
        const degrees = Object.values(modelSnapshot.graph?.nodes || {})
          .map(n => n.edges.length);
        const maxDegree = Math.max(...degrees, 10);
        const histogram = new Array(maxDegree + 1).fill(0);
        for (const d of degrees) histogram[d]++;
        const gTotal = degrees.length || 1;
        return histogram.map(h => h / gTotal);

      case 'LLM':
        // LLM: 模板使用频率
        const usageCounts = (modelSnapshot.promptTemplates || [])
          .map(t => t.usage_count);
        const llmTotal = usageCounts.reduce((a, b) => a + b, 0) || 1;
        return usageCounts.map(u => u / llmTotal);

      default:
        return [];
    }
  }

  detectDrift(modelSnapshot: any): { drift_detected: boolean; kl_score: number } {
    const dist = this.toDistribution(modelSnapshot);
    if (dist.length === 0) return { drift_detected: false, kl_score: 0 };
    return this.detector.detectDrift(dist);
  }

  reset(): void {
    this.detector.reset();
  }
}
```

**各层 KL 阈值差异化（评审修复 m5）**:

| 层 | KL 阈值 | 理由 |
|---|---|---|
| S | 0.15 | 意图分布变化需敏感检测 |
| DSH | 0.15 | 路径分布变化标准阈值 |
| C | 0.20 | 规则分布变化更剧烈，阈值放宽 |
| G | 0.25 | 图结构变化慢，阈值更宽松 |
| LLM | 0.15 | Prompt 模式变化需敏感检测 |

### 3.5 模型状态持久化（P1）

**新增**: `checkpoint()` + `restore()`

> **评审修复 M4**: 明确 checkpoint 存储位置和格式。
> TDR 的 case 表存储 TrainingCase，ModelState 不是 TrainingCase，不能存入同一张表。
> 新建 `model_state` 表（SQLite）存储 checkpoint，或存为 JSON 文件。

#### 3.5.1 存储格式

**方案 A（推荐）: SQLite model_state 表**

```sql
-- 新建表，与 TDR 的 case 表分离
CREATE TABLE IF NOT EXISTS model_state (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  layer       TEXT NOT NULL,              -- S | DSH | C | G | LLM
  step        INTEGER NOT NULL,           -- 训练步数
  state_json  TEXT NOT NULL,              -- ModelState JSON
  drift_flag  BOOLEAN DEFAULT FALSE,     -- 上次是否漂移触发
  created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_model_state_layer ON model_state(layer, created_at DESC);
```

**方案 B（备选）: JSON 文件**

```
3.1-FRONTEND/checkpoints/
  ├── S.json       # S 层最新 checkpoint
  ├── DSH.json
  ├── C.json
  ├── G.json
  └── LLM.json
```

#### 3.5.2 ModelState 结构

```typescript
/**
 * 模型状态
 * 借鉴 PyTorch checkpoint: weights + optimizer_state + step + drift_flag
 */
interface ModelState {
  weights: Record<string, number>;          // 模型权重（TF-IDF/路径频率/规则权重/节点权重/模板权重）
  patterns: unknown[];                       // 模式/模板/规则/图结构/Prompt模板
  codebook?: number[][];                     // 码本（检索用，可选）
  step: number;                              // 训练步数
  drift_flag: boolean;                       // 上次是否漂移触发
  buffer_stats: {
    size: number;
    capacity: number;
    avg_weight: number;
    quality_distribution: Record<string, number>;
  };
  timestamp: number;                         // 保存时间
  version: string;                           // 模型版本
  layer: string;                             // 所属层
}

class ModelCheckpoint {
  private static CHECKPOINT_INTERVAL = 10;   // 每10次增量后落盘

  /**
   * 保存模型状态
   * 方案A: POST /api/training/{layer}/checkpoint → 写入 model_state 表
   * 方案B: 写入 checkpoints/{layer}.json
   */
  async checkpoint(layer: TrainingLayer, state: ModelState): Promise<void>;

  /**
   * 恢复模型状态
   * 从 model_state 表读取最近 checkpoint（按 created_at DESC LIMIT 1）
   * 如果无记录返回 null（冷启动）
   */
  async restore(layer: TrainingLayer): Promise<ModelState | null>;

  /**
   * 获取历史 checkpoint 列表（用于回滚）
   */
  async listCheckpoints(layer: TrainingLayer, limit: number): Promise<ModelState[]>;
}
```

#### 3.5.3 内存估算（评审修复 m2）

| 层 | Buffer 容量 | 每条平均大小 | Buffer 内存 | 模型状态内存 | 总计 |
|---|---|---|---|---|---|
| S | 200 | ~0.5KB | ~100KB | ~50KB | ~150KB |
| DSH | 300 | ~1KB | ~300KB | ~100KB | ~400KB |
| C | 200 | ~0.8KB | ~160KB | ~80KB | ~240KB |
| G | 500 | ~2KB | ~1MB | ~200KB | ~1.2MB |
| LLM | 100 | ~1.5KB | ~150KB | ~100KB | ~250KB |
| **总计** | | | **~1.7MB** | **~530KB** | **~2.2MB** |

> 内存预算充足（远低于 SPEC v0.2 的 ACTIVE_QUOTA memory≤2GB 限制）

### 3.6 API 扩展（P2）

**现有 API**:
```
GET  /api/training/{layer}                     — 获取桶状态
POST /api/training/{layer}                     — action: add | train
```

**v0.5 扩展**:
```
POST /api/training/{layer}
  body: { action: "add", data: {...}, quality: "S" }    // 新增 quality 参数
  body: { action: "incremental" }                        // 新增: 触发增量训练
  body: { action: "train" }                              // 现有: 全量训练
  body: { action: "checkpoint" }                         // 新增: 保存模型状态
  body: { action: "restore" }                            // 新增: 恢复模型状态

GET  /api/training/{layer}/model                          — 新增: 获取模型状态
GET  /api/training/{layer}/buffer                         — 新增: 获取buffer统计
```

**响应格式扩展**:
```json
{
  "success": true,
  "data": {
    "bucketCount": 124,           // 现有: 桶计数（改为 buffer.size）
    "bucketThreshold": 50,        // 现有: 阈值（改为 capacity）
    "trained": true,              // 现有: 是否训练
    "incrementalStep": 12,        // 新增: 增量训练步数
    "lastDriftDetected": false,   // 新增: 上次是否漂移触发
    "bufferStats": {               // 新增: buffer 统计
      "size": 124,
      "capacity": 200,
      "avgWeight": 0.65,
      "oldestAge": 8,
      "qualityDistribution": { "S": 5, "A": 20, "B": 40, "C": 59 }
    },
    "modelState": {                // 新增: 模型状态
      "step": 12,
      "version": "v0.5-20261011",
      "hasCheckpoint": true
    }
  }
}
```

### 3.7 FeedbackLoop 扩展（P2）

**现有**: 调优 `novelty_threshold`
**v0.5 扩展**: 调优 `microBatchSize` + `bufferCapacity` + `ewmaLambda`

```python
class FeedbackLoop:
    def get_adjusted_parameters(self) -> dict:
        """根据历史训练质量调优参数。"""
        recent_quality = self._get_recent_quality(window=5)

        return {
            # 现有
            "novelty_threshold": self._adjust_novelty(recent_quality),

            # v0.5 新增
            "micro_batch_size": self._adjust_micro_batch(recent_quality),
            # 高质量 → 增大 microBatch（每次多学点）
            # 低质量 → 减小 microBatch（更精细学习）

            "buffer_capacity": self._adjust_capacity(recent_quality),
            # 漂移频繁 → 减小 capacity（更快遗忘旧数据）
            # 质量稳定 → 增大 capacity（保留更多历史）

            "ewma_lambda": self._adjust_lambda(recent_quality),
            # 漂移频繁 → 增大 lambda（更快衰减旧权重）
            # 质量稳定 → 减小 lambda（保留历史更久）
        }
```

#### 3.7.1 EWMA λ 与 DECAY_RATE 的关系（评审修复 m6）

> SPEC 中出现了两个参数: `ewmaLambda`（各层不同: S=0.95/C=0.90/G=0.99）和 `DECAY_RATE=0.05`。
> 明确关系: `DECAY_RATE = 1 - ewmaLambda`，即 `decayedWeight = weight × Math.exp(-age × (1 - λ))`

| 层 | ewmaLambda | DECAY_RATE = 1-λ | 衰减速度 | 理由 |
|---|---|---|---|---|
| S | 0.95 | 0.05 | 中 | 意图分类标准衰减 |
| DSH | 0.95 | 0.05 | 中 | 路径模式标准衰减 |
| C | 0.90 | 0.10 | 快 | 反思变化快，快速遗忘旧规则 |
| G | 0.99 | 0.01 | 慢 | 图结构变化慢，缓慢衰减 |
| LLM | 0.90 | 0.10 | 快 | Prompt 变化快，快速遗忘旧模板 |

> 注: ReplayBuffer 中的 `DECAY_RATE = 0.05` 是默认值（对应 S/DSH 层），
> 实际使用时各层用各自的 `1 - ewmaLambda` 替代。

### 3.8 迁移策略与冷启动（评审修复 M6）

#### 3.8.1 v0.2 → v0.5 迁移步骤

```
Step 1: 代码部署
  - 部署 ReplayBuffer + trainIncremental + DriftDetectorAdapter
  - 部署 model_state 表 / checkpoint 文件
  - 保留现有 train() 方法（全量训练仍可用）

Step 2: 数据迁移
  - 现有 bucket 中的数据 → 转换为 BufferEntry
  - quality 默认为 'C'（无质量信息的旧数据）
  - age 初始为 0，weight = 1.0（不衰减旧数据）

Step 3: 模型状态 baseline
  - 对每层执行一次 train()（全量训练）→ 生成 baseline checkpoint
  - 或: 如果有已训练的模型状态，直接 checkpoint()

Step 4: 切换触发模式
  - addTrainingData() 从"桶满触发"切换到"三层触发"
  - 保留旧 train() 方法作为 fallback（漂移触发时使用）

Step 5: 验证
  - 运行 run_continual_training.py 验证三层触发
  - 检查 checkpoint 文件生成
  - 检查 buffer 统计（size/capacity/avgWeight）
```

#### 3.8.2 冷启动策略

> **评审修复 #5（7模式阻断）**: SPEC 原缺少冷启动策略。

| 场景 | 处理 | 说明 |
|------|------|------|
| 全新部署（无历史数据） | warmup 期: buffer.size < microBatchSize 时不触发训练 | S 级案例可跳过 warmup 立即触发 |
| 重启恢复（有 checkpoint） | restore() 恢复模型状态 + buffer 清空重建 | 模型状态不丢，buffer 从空开始积累 |
| 重启恢复（无 checkpoint） | 冷启动: 首次训练从零开始 | warmup 期保护 |
| 迁移启动（v0.2 bucket 有数据） | bucket → BufferEntry 转换 + 一次性 baseline checkpoint | §3.8.1 Step 2-3 |

**warmup 期规则**:
```typescript
// 借鉴 RLlib num_steps_sampled_before_learning_starts
const WARMUP_SIZE = this.microBatchSize;  // warmup = 1个微批量

if (this.buffer.size < WARMUP_SIZE) {
  // warmup 期: 只积累数据，不触发微批训练
  // 但 S 级案例可跳过 warmup（优先级触发不受限）
  return;
}
```

#### 3.8.3 持续训练→训练质量提升因果链（评审修复 #3）

> **评审修复 #3（7模式阻断因果链跳跃）**: 原 SPEC 从"持续训练"到"更好的训练效果"缺少量化证据链。

**因果假设**:

```
持续训练（每N条增量学习）
  → 旧模式保留率 > 80%（EWMA 衰减 vs 清空 = 0%）
  → 漂移响应延迟 < 1次训练（KL 检测 vs 桶满50条）
  → S级案例学习延迟 = 0（优先级触发 vs 桶满50条）
  → 训练质量分提升（FeedbackLoop 历史对比）
  → 最终: 意图分类 accuracy / 路径模板 coverage / 规则蒸馏质量 提升
```

**量化验证方法**:
- 对比 v0.2（清空桶）和 v0.5（增量训练）的模型 metrics
- 旧模式保留率 = `训练后仍存在的 weights 数量 / 训练前 weights 数量`
- 漂移响应延迟 = `KL 超阈值到 train() 的数据条数`
- S级案例学习延迟 = `S级 add 到 trainIncremental 的数据条数`（应为 0）

---

## 4. 各层差异化设计

### 4.1 S 层 — IntentTrainingLoop

| 参数 | 值 | 理由 |
|------|---|------|
| capacity | 200 | 意图分类需要快速响应，容量适中 |
| microBatchSize | 5 | 微批量小，快速响应新意图 |
| ewmaLambda | 0.95 | 标准衰减率 |
| 增量策略 | TF-IDF 频率表增量更新 | 新意图立即加入频率表 |
| 防遗忘 | EWMA 衰减旧意图权重 | 旧意图渐淡但不清除 |
| 漂移检测 | KL散度 > 0.15 | 意图分布漂移时全量重训 |

### 4.2 DSH 层 — ExecutionPathTrainingLoop

| 参数 | 值 | 理由 |
|------|---|------|
| capacity | 300 | 路径模式挖掘需要更多样本 |
| microBatchSize | 10 | 路径模式需要更多样本发现 |
| ewmaLambda | 0.95 | 标准衰减率 |
| 增量策略 | 路径频率统计增量 + 模板权重衰减 | 新路径加入频率表 |
| 防遗忘 | 旧模板权重渐淡但不清除 | 历史路径保留参考 |
| 漂移检测 | KL散度 > 0.15 | 路径分布漂移时全量重训 |

### 4.3 C 层 — ReflectionTrainingLoop

| 参数 | 值 | 理由 |
|------|---|------|
| capacity | 200 | 反思规则蒸馏，容量适中 |
| microBatchSize | 10 | 规则蒸馏需要足够样本 |
| ewmaLambda | 0.90 | 反思变化较快，衰减更快 |
| 增量策略 | 新增 decision rule + 规则权重衰减 | 新规则加入，旧规则衰减不移除（M1修复） |
| 防遗忘 | 规则权重衰减 + 保留阈值 0.05 | 旧规则 weight 低于阈值移入 ruleArchive（可恢复） |
| 漂移检测 | KL散度 > 0.20 | 反思分布变化更剧烈，阈值放宽（m5修复） |

### 4.4 G 层 — GraphStructureTrainingLoop

| 参数 | 值 | 理由 |
|------|---|------|
| capacity | 500 | 图结构变化慢，容量大保证拓扑稳定 |
| microBatchSize | 15 | 图结构变化慢，微批量稍大 |
| ewmaLambda | 0.99 | 图结构变化慢，衰减慢 |
| 增量策略 | 增量添加节点/边 + 旧子图权重衰减 | 新节点/边加入图 |
| 防遗忘 | 旧子图权重衰减但拓扑保留 | 历史拓扑结构保留 |
| 漂移检测 | KL散度 > 0.25 | 图结构变化慢，阈值更宽松（m5修复） |

### 4.5 LLM 层 — PromptOptimizationLoop

| 参数 | 值 | 理由 |
|------|---|------|
| capacity | 100 | Prompt 模式变化快，容量小 |
| microBatchSize | 5 | Prompt 变化快，微批量小 |
| ewmaLambda | 0.90 | Prompt 变化快，衰减快 |
| 增量策略 | 新增 prompt 模式 + 旧模板 KL 约束 | 新模板加入 |
| 防遗忘 | 旧模板作 teacher KL 散度约束 | 旧模板约束新模板 |
| 漂移检测 | KL散度 > 0.15 | Prompt 分布漂移时全量重训 |

---

## 5. 实施计划

### 5.1 P0：Replay Buffer + trainIncremental（核心）

**目标**: 桶→Buffer + 增量训练方法

| 任务 | 文件 | 变更 |
|------|------|------|
| P0.1 | `3.1-FRONTEND/src/lib/replay-buffer.ts` | 新建: ReplayBuffer 类 + BufferEntry 接口 |
| P0.2 | `3.1-FRONTEND/src/lib/s-intent-training-loop.ts` | bucket → buffer + trainIncremental() |
| P0.3 | `3.1-FRONTEND/src/lib/dsh-path-training-loop.ts` | bucket → buffer + trainIncremental() |
| P0.4 | `3.1-FRONTEND/src/lib/c-reflection-training-loop.ts` | bucket → buffer + trainIncremental() + 规则权重衰减 |
| P0.5 | `3.1-FRONTEND/src/lib/g-graph-training-loop.ts` | bucket → buffer + trainIncremental() |
| P0.6 | `3.1-FRONTEND/src/lib/llm-prompt-training-loop.ts` | bucket → buffer + trainIncremental() |
| P0.7 | `34-前端应用训练系统/tests/test_replay_buffer.py` | TDD: ReplayBuffer 单元测试 |

**验收标准**:
- [ ] ReplayBuffer: add + sample + decayAll + getStats 全部可用
- [ ] 5 层训练循环: trainIncremental() 可用，不清空 buffer
- [ ] 增量训练后模型状态保留（weights/patterns 非空）
- [ ] TDD: RED → GREEN → REFACTOR

### 5.2 P1：三层触发 + 模型状态持久化

**目标**: 触发机制 + checkpoint

| 任务 | 文件 | 变更 |
|------|------|------|
| P1.1 | 5 层训练循环 | addTrainingData() 内置三层触发 |
| P1.2 | `3.1-FRONTEND/src/lib/model-checkpoint.ts` | 新建: ModelCheckpoint 类 |
| P1.3 | 5 层训练循环 | 集成 DriftDetector 作为触发层2 |
| P1.4 | `34-前端应用训练系统/tests/test_trigger_mechanism.py` | TDD: 触发机制测试 |
| P1.5 | `34-前端应用训练系统/tests/test_model_checkpoint.py` | TDD: 持久化测试 |

**验收标准**:
- [ ] 微批触发: 每 N 条 → trainIncremental()
- [ ] 漂移触发: KL > 0.15 → train()
- [ ] 优先级触发: quality=S → 立即 trainIncremental()
- [ ] checkpoint: 保存 weights + patterns + step + drift_flag
- [ ] restore: 重启后恢复模型状态

### 5.3 P2：API 扩展 + FeedbackLoop 扩展

**目标**: API + 自适应调优

| 任务 | 文件 | 变更 |
|------|------|------|
| P2.1 | `3.1-FRONTEND/src/app/api/training/[layer]/route.ts` | 新增 action: incremental/checkpoint/restore |
| P2.2 | `3.1-FRONTEND/src/app/api/training/[layer]/model/route.ts` | 新建: GET model 端点 |
| P2.3 | `34-前端应用训练系统/adapters/ts_http_training_executor.py` | 新增 triggerIncremental/checkpoint/restore |
| P2.4 | `34-前端应用训练系统/core/training_metrics.py` | FeedbackLoop 扩展: 调优 microBatch + capacity + λ |

**验收标准**:
- [ ] POST action=incremental → 触发增量训练
- [ ] POST action=checkpoint → 保存模型状态
- [ ] POST action=restore → 恢复模型状态
- [ ] GET /model → 返回模型状态 JSON
- [ ] FeedbackLoop: 调优 microBatch + capacity + λ

### 5.4 P3：EWMA 衰减 + 集成验证

**目标**: 时间衰减 + 全链路验证

| 任务 | 文件 | 变更 |
|------|------|------|
| P3.1 | ReplayBuffer | 实现 decayAll() + EWMA 衰减 |
| P3.2 | C 层训练循环 | 规则权重衰减 + 保留阈值实现 |
| P3.3 | LLM 层训练循环 | KL 散度约束实现 |
| P3.4 | `34-前端应用训练系统/scripts/run_continual_training.py` | 主动训练脚本: 持续模式 |
| P3.5 | `34-前端应用训练系统/acceptance_bundles/` | 验收包: 五维证据 |

**验收标准**:
- [ ] EWMA: 旧数据 weight 随 age 衰减
- [ ] C层规则权重衰减: 旧规则 weight 低于 0.05 时移入 ruleArchive，不从系统删除
- [ ] 持续训练: 数据到达即学习，不等桶满
- [ ] 五维验收: 症状+日志+回归+影响面+边界

---

## 6. 反模式清单（禁止 — 三域共识）

| # | 反模式 | 三域依据 | 后果 |
|---|--------|---------|------|
| AP1 | 等桶满才训练 | 金融: 信息延迟最长50条 | 数据量少的层长期不训练 |
| AP2 | 清空桶/Buffer | AI: 主动制造灾难性遗忘 | 每次从零开始，无增量学习 |
| AP3 | regime 变化时立即用少量数据全量重训 | 金融: 加剧过拟合 | 新 regime 数据不足，模型退化 |
| AP4 | 只存 weights 不存 optimizer_state | GitHub: 丢 Adam 动量 | 恢复后训练不稳定 |
| AP5 | 预测时污染学习状态 | GitHub: River learn_one/predict_one 分离 | 预测和学习耦合，难以排查 |
| AP6 | 所有案例等同入桶 | AI: PER 按优先级采样 | S级高价值被C级低价值淹没 |
| AP7 | 无时间衰减 | 金融: EWMA 衰减 | 1月前案例和今天权重相同 |
| AP8 | 只检查"API 返回200"不检查 metrics | dream-acceptance-verify v1.1.0 | 功能验收不完整 |

---

## 7. 与现有组件的兼容性

| 现有组件 | v0.2 角色 | v0.5 角色 | 改动量 |
|---------|---------|---------|--------|
| DriftDetector | CaseRetriever 可选依赖 | **触发层2** 核心，集成到5层训练循环 | 小（接线） |
| FeedbackLoop | 调优 novelty_threshold | 扩展: 调优 microBatch + capacity + λ | 中（扩展） |
| TrainingQueue | 优先级堆 + 重试 | 扩展: 优先级触发（S级立即训练） | 小（扩展） |
| TSHTTPTrainingExecutor | HTTP API add/train | 新增 triggerIncremental/checkpoint/restore | 中（新方法） |
| 5层训练循环 | bucket + train() + clear() | buffer + trainIncremental() + checkpoint() | 大（核心改动） |
| 5个数据采集器 | TrainingDataProvider | 不变 | 无 |
| TDR (case_bank_server) | SQLite 训练数据仓库 | 扩展: 存储模型 checkpoint | 小（新表） |
| DualModeOrchestrator | run_active_training() | 扩展: run_continual_training() | 中（新方法） |

---

## 8. 验收标准

### 8.1 功能验收（dream-acceptance-verify v1.1.0）

| 维度 | 验收方式 | 通过标准 |
|------|---------|---------|
| 症状复测 | 运行持续训练脚本 | 数据到达即学习，不等桶满 |
| 日志证据 | SPEC→代码→运行→日志追溯链 | metrics 非空 (trained + step + bufferStats) |
| 回归测试 | pytest + tsc | 全绿, exit=0 |
| 影响面 | git diff | 仅改动声明范围 |
| 边界验证 | 空buffer/满buffer/漂移/S级 | 3场景全通过 |

### 8.2 性能验收

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 增量训练延迟 | < 100ms | trainIncremental() 计时 |
| Buffer 内存占用 | < 50MB | getStats().size × avgEntrySize |
| Checkpoint 写入 | < 500ms | checkpoint() 计时 |
| 漂移检测延迟 | < 10ms | detectDrift() 计时 |

### 8.3 质量验收

| 指标 | 目标 | 测量方式 |
|------|------|---------|
| 灾难性遗忘 | 增量训练后旧模式保留率 > 80% | 对比训练前后的 weights/patterns |
| 漂移响应 | KL > 0.15 后 1 次训练内触发 | 日志检查 drift → train 时间差 |
| 优先级响应 | S级案例到达后 1 次训练内触发 | 日志检查 add → train 时间差 |
| EWMA 衰减 | 10 轮后旧数据 weight < 0.5 | getStats().avgWeight |

---

## 9. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.2 | 2026-10-11 | 双模式学习训练架构（主动横向 + 被动纵深），5个数据源采集器，资源配额管理，训练队列，评估反馈闭环 |
| v0.5 | 2026-10-11 | 持续算法驱动训练架构：桶→Replay Buffer + 三层触发（微批+漂移+优先级）+ 增量训练（EWMA+EWC）+ 模型状态持久化。来源：用户洞察「训练应该是持续的，被算法驱动」+ 三域调研（传统金融CUSUM/贝叶斯/EWMA + AI在线学习/EWC/rehearsal + GitHub River/RLlib/PyTorch checkpoint）|
| v0.5-revised | 2026-10-11 | 同行评审修复: M1(C层EWC→规则权重衰减+保留阈值，非参数化系统无法计算Fisher矩阵) + M2(DriftDetector适配层，5层数据格式异构) + M3(每层trainIncremental伪代码算法) + M4(checkpoint存储model_state表+JSON双方案) + M5(quality默认C向后兼容) + M6(迁移策略5步+冷启动warmup) + m3(轮盘赌采样) + m5(各层KL阈值差异化) + m6(DECAY_RATE=1-λ) + #3(因果链量化) + #5(冷启动warmup守卫) |

---

## 10. 参考文献

### 三域调研来源

**传统金融**:
- Two Sigma: ensemble + regime detection + continuous retrain
- Renaissance (Medallion): 5分钟切片 + HMM
- 贝叶斯在线学习: Prior_today = Posterior_yesterday
- CUSUM + Page-Hinkley: 工业标准漂移检测
- EWMA λ=0.95: 日频/月频增量更新主流
- ReCAP 框架 (KDD 2026): regime-gated policy library

**AI 训练**:
- Online Learning: learn_one(x,y) 单样本即时更新 (River)
- Experience Replay Buffer: DQN 1M transitions, PER alpha=0.6 beta=0.4→1.0
- Continual Learning 三大方法族: Regularization (EWC) / Rehearsal / Architectural
- Catastrophic Forgetting: 清空=主动制造遗忘
- EWC: λ·Σ F_i·(θ_i-θ*_i)² Fisher 矩阵正则化

**GitHub 生态**:
- River (online-ml/river): learn_one/predict_one API 分离, 内置 ADWIN
- RLlib (Ray): PrioritizedReplayBuffer{capacity, alpha, beta}
- ADWIN: 变长窗口 W0/W1 均值差比较
- PyTorch checkpoint: model_state_dict + optimizer_state_dict + epoch + RNG
- scikit-multiflow: partial_fit vs fit 分离
- MLflow: log_metric(step=N) + Model Registry

### 项目内文档
- SPEC-20261011 v0.2: 双模式学习训练架构
- SPL v0.4: 5层训练循环 + TDR + CaseIngestGate
- dream-acceptance-verify v1.1.0: 五维证据验收 + HC-9 功能验收日志追溯 SPEC

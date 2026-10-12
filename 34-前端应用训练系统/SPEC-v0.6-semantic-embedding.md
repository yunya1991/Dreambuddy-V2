# SPEC-20261012-v0.6 — 语义嵌入混合架构（Semantic Embedding Hybrid）

> **版本**: v0.6-draft
> **日期**: 2026-10-12
> **作者**: Trae + User
> **状态**: Draft（待用户审查 → 审查通过后 TDD 实施）
> **关联**: SPEC-v0.5-continual-training (v0.5), SPL v0.4, 3.1-FRONTEND/src/lib/knowledge-rag.ts
> **方法论**: recall → 现有基础设施调研 → 复用方案设计 → SPEC v0.6
> **变更性质**: v0.5 的 S 层意图识别升级 — 从"纯 TF-IDF 关键词匹配"升级为"TF-IDF 主干 + 语义嵌入辅助"混合架构

---

## 0. Executive Summary

### 0.1 核心命题

S 层意图识别从**纯词频匹配**升级为**混合架构**：TF-IDF 主干不变，新增语义嵌入辅助层，用预训练 LLM 的语义表示能力弥补 TF-IDF 在同义/近义/跨表达意图上的盲区。

| 维度 | v0.5（当前） | v0.6（优化后） |
|------|-------------|---------------|
| **匹配机制** | 纯 TF-IDF 2-gram 词频 | TF-IDF 主干 + 语义嵌入辅助 |
| **语义能力** | 无（仅字符级 n-gram 重叠） | DeepSeek LLM embedding 语义相似度 |
| **预测公式** | `argmax(tfidf_score)` | `argmax(α·tfidf + (1-α)·semantic_sim)` |
| **同义识别** | 无（"重启"和"reload"无关联） | 有（语义嵌入捕获同义关系） |
| **降级策略** | N/A | 三级 FAIL-OPEN：API → n-gram → 纯 TF-IDF |
| **主干破坏** | N/A | 零破坏（TF-IDF 逻辑完全保留，语义是叠加层） |

### 0.2 设计驱动力

| 编号 | 驱动力 | 来源 |
|------|--------|------|
| F1 | TF-IDF 无法识别同义/近义表达（"重启服务" vs "reload service" 判为不同意图） | S 层实测 |
| F2 | 意图识别本质偏语义层面，与大语言模型算法贴近 | 用户洞察 |
| F3 | 项目已有完整 embedding 基础设施（knowledge-rag.ts），零新依赖 | 调研发现 |
| F4 | solution-encoder.ts L69 预留"生产环境可替换为真实 embedding"接入点 | 代码注释 |
| F5 | 认知记忆 quality=S/A 级样本可作为高质量语义锚点 | v0.5 数据流 |
| F6 | 用户偏好"现有成熟稳定方案"而非引入新重依赖 | 用户 profile |

### 0.3 范围边界

**In Scope:**
- S 层 IntentTrainingLoop 新增语义原型层（semantic prototype）
- 混合打分公式（TF-IDF + 语义相似度加权融合）
- 三级 FAIL-OPEN 降级链
- 语义锚点用 quality=S/A 样本 embedding 聚合
- SModelState 扩展 + checkpoint 兼容
- API 扩展（语义开关、α 参数可调）

**Out of Scope:**
- 不修改 TF-IDF 主干逻辑（trainIncremental 的 Step 1-4 完全保留）
- 不引入 @xenova/transformers / TensorFlow.js / ONNX Runtime 等新依赖
- 不做 Transformer 权重微调 / 分类头训练
- 不集成矛盾论交叉验证框架（用户明确澄清无关）
- 不修改其他 4 层（DSH/C/G/LLM）
- 不修改 DeepSeek API 本身（只复用 embedTexts 函数）

---

## 1. 调研结论

### 1.1 现有 embedding 基础设施

| 组件 | 路径 | 现状 | 复用价值 |
|------|------|------|---------|
| DeepSeek embedTexts | `knowledge-rag.ts` L305-L373 | 完整：批量向量化 + 重试 + 超时 + 429 处理 | ★★★★★ 直接复用 |
| cosineSimilarity | `knowledge-rag.ts` L383-L397 | 纯数学零依赖 | ★★★★★ 直接复用 |
| ngramSimilarity | `knowledge-rag.ts` L407-L422 | 字符 3-gram 余弦，API 不可用时 fallback | ★★★★ 降级用 |
| 伪 embedding | `solution-encoder.ts` L71-L104 | hash 投影，注释"可替换为真实 embedding" | 不复用（已被 DeepSeek 替代） |

**关键结论**：零新依赖。DeepSeek API 已在 RAG 场景验证可用，S 层复用同一管线。

### 1.2 方案对比（为何不用 @xenova/transformers）

| 维度 | DeepSeek API（复用） | @xenova/transformers（新引入） |
|------|---------------------|-------------------------------|
| 新依赖 | 零 | +1 包，~100MB+ 模型文件 |
| 语义能力 | 大模型级（DeepSeek LLM） | 小模型级（DistilBERT） |
| 网络依赖 | 需要 API 调用 | 首次下载模型后离线 |
| 集成复杂度 | 低（已有完整实现） | 高（WASM/worker/Next.js 兼容） |
| 用户偏好匹配 | ✓ 现有成熟稳定 | ✗ 新重依赖 |
| FAIL-OPEN | 已有三级降级 | 需新建降级链 |

**决策**：复用 DeepSeek API。语义能力更强，零新依赖，符合用户偏好。

### 1.3 训练数据源

| 来源 | 质量等级 | 用途 | 数据量 |
|------|---------|------|--------|
| cognitive_memory_collector | S/A 级 | 语义锚点（原型向量聚合） | ~2% of 2235 条 |
| Trae 对话历史 | B/C 级 | TF-IDF 主干训练（不变） | ~98% |
| 33-REA 解析 | B 级 | TF-IDF 主干（不变） | 按需 |

**关键约束**：语义原型只用 quality=S/A 级样本聚合，确保锚点质量。B/C 级样本仍走 TF-IDF 主干，不受语义层影响。

---

## 2. 混合架构设计

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    S 层 IntentTrainingLoop                    │
│                    (混合架构 v0.6)                             │
├──────────────────────────┬──────────────────────────────────┤
│   TF-IDF 主干（不变）      │   语义嵌入辅助层（新增）            │
│   2-gram 词频统计          │   DeepSeek LLM embedding          │
│   EWMA 权重衰减            │   语义原型向量（per intent_type）  │
│   quality boost           │   EWMA 原型更新                   │
│   ruleArchive             │   quality=S/A 锚点聚合             │
├──────────────────────────┼──────────────────────────────────┤
│ 训练数据: B/C 级样本       │ 训练数据: S/A 级样本              │
│ (全部样本走 TF-IDF)        │ (仅高质量样本做 embedding)         │
├──────────────────────────┴──────────────────────────────────┤
│              混合打分层（新增）                                │
│                                                              │
│   final_score(intent) = α × tfidf_score(intent)              │
│                       + (1-α) × semantic_sim(intent)         │
│                                                              │
│   α = SEMANTIC_FUSION_ALPHA (默认 0.7, 偏重 TF-IDF 主干)     │
├──────────────────────────────────────────────────────────────┤
│              三级 FAIL-OPEN 降级链                            │
│                                                              │
│   ① DeepSeek API 可用 → 语义 embedding + TF-IDF 混合         │
│   ② API 不可用 → n-gram 相似度 + TF-IDF 混合（降级语义）      │
│   ③ n-gram 也不行 → 纯 TF-IDF（当前 v0.5 行为）              │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 语义原型层设计

**核心概念**：每个 intent_type 维护一个"语义原型向量"（semantic prototype），代表该意图的语义中心。

**原型构建**：
```
对 quality=S/A 级样本 x:
  embedding_x = embedTexts([x.message])[0]   // DeepSeek API
  semantic_prototype[intent] = β × embedding_x + (1-β) × old_prototype

其中 β = SEMANTIC_EWMA_LAMBDA (默认 0.3, 慢更新保证稳定性)
```

**原型存储**：
```typescript
// SModelState 新增字段
semanticPrototypes: Record<string, number[]>;  // intent_type → 原型向量
semanticEnabled: boolean;                      // 语义层是否启用
semanticStep: number;                          // 语义训练步数（独立于 TF-IDF step）
```

**冷启动**：首个 S/A 级样本到达时初始化原型向量 = embedding_x。后续样本做 EWMA 更新。

### 2.3 混合打分公式

**预测时**（predictIntent）：

```
对候选 intent_i:
  tfidf_score_i = TF-IDF 2-gram 匹配分（现有逻辑不变）

  semantic_sim_i = cosineSimilarity(
    embedTexts([query])[0],      // query 的语义向量
    semanticPrototypes[intent_i]  // 该意图的原型向量
  )

  final_score_i = α × tfidf_score_i + (1-α) × semantic_sim_i

返回 argmax(final_score_i)
```

**参数**：
- `α = 0.7`（偏重 TF-IDF 主干，语义只做辅助修正）
- 语义不可用时 `α = 1.0`（退化为纯 TF-IDF）

**设计理由**：
- α=0.7 而非 0.5：TF-IDF 已验证有效，语义只补充盲区（同义/近义），不做主导
- 语义相似度范围 [0,1]，与 TF-IDF 分数同量级，加权有意义
- 懒计算：只在 predictIntent 时才调 embedTexts（训练时不调，省 API 配额）

### 2.4 三级 FAIL-OPEN 降级

```
predictIntent(query):
  try {
    // Level 1: DeepSeek API
    queryEmbedding = await embedTexts([query])
    semanticAvailable = true
  } catch {
    // Level 2: n-gram fallback
    queryEmbedding = null
    semanticAvailable = this._ngramFallback  // 配置开关
  }

  for each intent_i:
    tfidf_score = this._tfidfScore(query, intent_i)  // 现有逻辑

    if (semanticAvailable && this._semanticPrototypes[intent_i]):
      if (queryEmbedding):
        // Level 1: 语义 embedding
        semantic_sim = cosineSimilarity(queryEmbedding, prototype_i)
      else:
        // Level 2: n-gram 降级
        semantic_sim = ngramSimilarity(query, representative_text_i)

      final_score = α × tfidf_score + (1-α) × semantic_sim
    else:
      // Level 3: 纯 TF-IDF
      final_score = tfidf_score

  return argmax(final_score)
```

**降级触发条件**：
- Level 1 → 2: DeepSeek API 超时/429/5xx/网络错误
- Level 2 → 3: 无原型向量（冷启动期）或 `_ngramFallback=false`

### 2.5 接入点（IntentTrainingLoop 修改清单）

| 修改点 | 文件 | 行号（v0.5）| 变更类型 |
|--------|------|-------------|---------|
| SModelState | s-intent-training-loop.ts | L52-L63 | 新增 3 字段 |
| 常量 | s-intent-training-loop.ts | L86-L88 | 新增 SEMANTIC_FUSION_ALPHA / SEMANTIC_EWMA_LAMBDA |
| IntentTrainingLoop 字段 | s-intent-training-loop.ts | L100-L117 | 新增 _semanticPrototypes / _semanticEnabled |
| trainIncremental | s-intent-training-loop.ts | L241-L290 | 新增 Step 4.5: 语义原型更新 |
| _predictIntent | s-intent-training-loop.ts | (现有) | 改为混合打分 |
| getModelSnapshot | s-intent-training-loop.ts | (现有) | 包含 semanticPrototypes |
| restoreModel | s-intent-training-loop.ts | (现有) | 恢复 semanticPrototypes |

**不修改的方法**：
- `addTrainingData` — 不变（quality 传递已支持）
- `_checkTriggers` — 不变（触发逻辑不变）
- `train` — 不变（全量训练保留向后兼容）
- `_archiveLowWeightIntents` — 不变（归档逻辑不变）
- `shouldTrain` — 不变

### 2.6 API 扩展

```typescript
// POST /api/training/S 新增 action
{
  action: "semantic_config",
  data: {
    enabled: boolean,        // 语义层开关
    fusion_alpha: number,    // 混合权重 α (0-1)
    ewma_lambda: number,     // 原型更新 β (0-1)
    ngram_fallback: boolean  // n-gram 降级开关
  }
}

// 响应新增字段
{
  semanticEnabled: boolean,
  semanticPrototypeCount: number,
  semanticStep: number,
}
```

---

## 3. 实施计划

### 3.1 TDD 流程

```
RED:  tests/test-s-semantic-hybrid.test.ts
      ├─ test: 语义原型初始化（S/A 样本 → 原型向量）
      ├─ test: 混合打分（α=0.7 时 TF-IDF + 语义融合）
      ├─ test: FAIL-OPEN Level 1→2（API 失败 → n-gram）
      ├─ test: FAIL-OPEN Level 2→3（无原型 → 纯 TF-IDF）
      ├─ test: 冷启动（无 S/A 样本时纯 TF-IDF）
      ├─ test: checkpoint 持久化（semanticPrototypes 存取）
      └─ test: 零回归（v0.5 测试全绿）

GREEN: s-intent-training-loop.ts 实现
       ├─ SModelState 扩展
       ├─ 常量定义
       ├─ _updateSemanticPrototype (新增)
       ├─ _predictIntentHybrid (新增/替换)
       └─ getModelSnapshot/restoreModel 扩展

REFACTOR: 提取 SemanticEmbeddingAdapter（可选）
          ├─ 封装 embedTexts + cosineSimilarity + ngramFallback
          └─ 便于未来替换 embedding provider
```

### 3.2 测试策略

| 测试类别 | 测试文件 | 关键用例 |
|---------|---------|---------|
| 单元测试 | s-intent-training-loop.test.ts | 原型更新、混合打分、降级链 |
| 集成测试 | test-s-semantic-hybrid.test.ts | S/A 样本 → 原型 → 预测闭环 |
| 回归测试 | 现有 s-intent-training-loop.test.ts | 561 条全绿（v0.5 零回归） |
| E2E | test_e2e_rea_to_llm_outcome.py | 18 条全绿（outcome 闭环不变） |

**Mock 策略**：
- 单元测试 mock `embedTexts`（不调真实 API）
- 集成测试可选调真实 API（标记 `@integration`）
- 回归测试不涉及语义层（α=1.0 时行为与 v0.5 完全一致）

### 3.3 落地检查清单

- [ ] SPEC v0.6 用户审查通过
- [ ] RED: 测试文件编写 + 确认红
- [ ] GREEN: IntentTrainingLoop 扩展实现
- [ ] 回归: 561 条 + 18 条全绿
- [ ] 认知闭环: record + verify

---

## 4. 风险与缓解

| 风险 | 等级 | 缓解 |
|------|------|------|
| DeepSeek API 延迟影响预测 | 中 | 懒计算（仅 predictIntent 时调）+ 原型缓存 + 异步更新 |
| API 配额消耗 | 中 | 训练时只对 S/A 级样本调（~2% 数据量） |
| 语义原型漂移 | 低 | EWMA β=0.3 慢更新 + quality 门控 |
| checkpoint 体积增大 | 低 | 原型向量 ~1536 维 × 45 intent ≈ 70KB，可接受 |
| v0.5 回归 | 低 | α=1.0 时行为完全一致 + 回归测试套件 |

---

## 5. 认知记忆规划

实施完成后 record 以下经验：

```
record(
  content="[SPEC v0.6][语义嵌入混合架构] S层意图识别升级: TF-IDF主干不变 + DeepSeek embedding语义原型辅助. 混合打分 α=0.7. 三级FAIL-OPEN: API→n-gram→纯TF-IDF. 复用knowledge-rag.ts的embedTexts/cosineSimilarity/ngramSimilarity, 零新依赖. 语义原型只用quality=S/A样本聚合.",
  quality_level="B",
  tags="SPEC,v0.6,语义嵌入,混合架构,S层,意图识别,FAIL-OPEN,DeepSeek,复用"
)
```

硬约束关键词检测：本 SPEC 包含"默认"(α默认0.7)、"阈值"(无原型时降级)，需按 CLAUDE.md §3 硬约束闸门流程 record。

---
name: graph-context-compressor
description: |
  🗜️ 图结构上下文压缩 SKILL - 对话过程中自动构建三层图（B 层蓝图 / A 层架构 / C 层执行），
  自动评估节点价值，压缩低价值节点，生成可可视化的压缩摘要。

  核心能力：
  1. 上下文图谱构建：对话消息 → B/A/C 三层图结构
  2. 语义感知压缩：Token/耗时/关键词多维度评分，自动保留高价值节点
  3. 意图路由：根据对话主题自动匹配对应 Blueprint 模板
  4. 可视化输出：生成前后对比数据，可直接用于前端组件渲染

  触发场景：
  - 用户请求压缩上下文、总结对话
  - 对话超过 10 条消息，需要保留关键信息
  - 对话包含明确的执行步骤/决策过程（如策略研究、交易执行链）
  - 需要展示决策路径时
  - 对话转向新主题前，需要总结旧主题

  输入格式：
  - 对话消息列表（role + content + timestamp）
  - 可选：已知的架构步骤、关键决策点
  - 可选：目标压缩率（默认 0.5）

  输出格式：
  - 压缩结果摘要（压缩率、保留节点数）
  - 保留节点列表（高价值内容）
  - 压缩节点列表（摘要引用）
  - 前端可用的可视化数据（VisualizationData）

version: 1.0.0
created: 2026-06-21
updated: 2026-06-21
license: Internal
---

# 🗜️ Graph-Context-Compressor: 图结构上下文压缩 SKILL (v1.0)

> 对话过程中自动构建三层图结构，识别高价值信息，智能压缩上下文。
> 基于技术文档 `6-图结构上下文压缩/TECHNICAL-DOC.md`。

---

## 🎯 SKILL 目标

1. **自动图谱构建**：从对话消息中识别意图→步骤→执行记录，构建三层图结构
2. **智能压缩**：基于 Token 消耗、执行耗时、语义关键词，自动评估节点价值
3. **上下文保留**：压缩后仍保留完整决策路径和关键信息（可追溯、可复盘）
4. **可视化呈现**：输出前端 GraphCompressionVisualizer 可渲染的数据

---

## 📋 三层图模型

### B 层：Blueprint（蓝图）
顶层架构图，描述本次对话的核心意图和主要组件。

- **节点类型**：意图识别、分析引擎、执行模块、报告生成器
- **数据结构**：`{ id, type, name, description, metadata }`
- **节点数**：2-6 个（依对话复杂度）

### A 层：Architecture（架构图）
DAG（有向无环图），描述具体执行步骤和依赖关系。

- **节点类型**：S0 快速回答 / S1 调研 / S2 分析 / S3 设计 / S4 验证 / S5 执行
- **依赖边**：描述步骤间的数据流转
- **节点数**：3-10 个

### C 层：Chronicle（执行记录）
时间线，记录每条消息的执行过程和内容。

- **节点**：每条对话消息 / 工具调用 / 决策点
- **属性**：时间戳、Token 消耗、内容摘要、状态（completed/compressed/skipped）
- **节点数**：10-N 条（随对话增长）

---

## 🔄 工作流程

### Phase 1：意图识别（B 层构建）

```yaml
输入: 用户消息列表
输出: BlueprintGraph
规则:
  - 从消息中识别核心意图（研究/分析/执行/设计/验证/报告）
  - 为每个意图创建一个组件节点
  - 基于 blueprintRegistry 预定义模板路由
```

**意图路由表**（见 `blueprint-registry.ts`）：
| 意图关键词 | 对应 Blueprint | 典型场景 |
|-----------|---------------|---------|
| 买入/卖出/仓位/入场 | 经典交易 | 交易决策对话 |
| 研究/调研/分析/行情 | 深度分析 | 市场调研对话 |
| 策略/设计/优化/回测 | 策略研究 | 策略开发对话 |
| 信号/监控/触发 | 信号执行 | 监控与通知 |
| 风险/止损/风控 | 持仓管理 | 风险管理对话 |

### Phase 2：步骤提取（A 层构建）

```yaml
输入: 结构化对话 + Blueprint
输出: ArchitectureGraph
规则:
  - 从每条消息中提取明确的步骤描述
  - 识别步骤间的依赖关系（先有调研 → 后有分析）
  - 为高价值步骤分配更高的节点权重
  - 识别决策点（如条件分支、跳过逻辑）
```

### Phase 3：执行记录（C 层构建）

```yaml
输入: 所有消息/工具调用/决策记录
输出: ChronicleGraph
规则:
  - 为每条消息创建一个执行节点
  - 记录: 时间戳、角色（user/assistant/tool）、内容摘要、Token数
  - 自动估算执行耗时和 Token 消耗
  - 标记关键决策点（用户确认 / 关键数据输出）
```

### Phase 4：压缩评估（核心算法）

```yaml
输入: 三层图
输出: CompressionResult + VisualizationData
评分维度（见 semantic-compressor.ts）:
  1. Token 消耗权重 (0.4): 消耗越高价值越高
  2. 执行耗时权重 (0.3): 耗时越长复杂度越高
  3. 关键词命中权重 (0.3): 匹配领域关键词（风险/信号/决策/关键）
压缩策略:
  - 目标压缩率: 0.5 (保留 50%)
  - 强制保留: B 层全部 / A 层核心步骤 / C 层关键决策点
  - 动态调整: 长对话 (>100 节点) 自动切换分片模式
```

---

## 📊 压缩结果

### 输出字段

| 字段 | 类型 | 说明 |
|-----|------|------|
| `compressionRatio` | number | 实际压缩率（后/前） |
| `retainedNodes` | number | 保留节点数 |
| `compressedNodes` | number | 压缩节点数 |
| `avgRetainedScore` | number | 保留节点平均分 |
| `avgCompressedScore` | number | 压缩节点平均分 |
| `retainedContext` | number | 上下文保留率 |
| `visualizationData` | VisualizationData | 前端可渲染数据（见 `visualization.ts`） |

### 典型效果

| 对话长度 | 压缩前节点数 | 压缩后节点数 | 压缩率 |
|---------|------------|------------|-------|
| 短对话（< 10 消息） | 5-10 | 3-7 | ~60% |
| 中等对话（10-50 消息） | 20-50 | 10-25 | ~50% |
| 长对话（50-200 消息） | 80-200 | 25-60 | ~30% |
| 超长对话（> 200 消息） | 200+ | 40-80 | ~25% |

---

## 🛠️ 执行脚本

### 核心工具（`core/build_and_compress.ts`）

```bash
# 方式1：通过 CLI 执行（从 JSON 文件读取对话）
npx tsx 6-图结构上下文压缩/skills/graph-compressor/core/build_and_compress.ts \
  --input /path/to/conversation.json \
  --output /path/to/compressed_result.json \
  --target-ratio 0.5

# 方式2：通过通用模块 API 调用（前端/系统集成）
import { createGraphCompressor } from '../../6-图结构上下文压缩/skills/graph-compressor/core/build_and_compress.ts';
const result = await createGraphCompressor({
  messages: conversationMessages,
  intent: 'trading-analysis',
  targetRatio: 0.5,
  mode: 'semantic'
});

# 方式3：通过通用模块的 Compressor API 调用
const compressor = createCompressor({ mode: 'semantic', semanticWeight: 0.4 });
const result = await compressor.compress({
  context: { blueprint, architecture, chronicle },
  targetRatio: 0.5
});
```

### 输入格式

```typescript
interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool_call' | 'tool_result' | 'system';
  content: string;
  timestamp: number;
  tokens?: number;
  toolName?: string;          // 若为工具调用
  decision?: string;           // 若为决策点
  importance?: 'high' | 'medium' | 'low';  // 人工标记
}

interface CompressionInput {
  messages: ConversationMessage[];
  intent?: string;             // 可选：显式意图提示
  targetRatio?: number;        // 默认 0.5
  mode?: 'basic' | 'semantic' | 'sharded' | 'auto';  // 默认 auto
  highlightKeywords?: string[]; // 可选：领域关键词（提升命中优先级）
}
```

---

## 🎨 可视化

### 输出格式（`VisualizationData`）

见 `6-图结构上下文压缩/visualization.ts` 完整定义：

```typescript
interface VisualizationData {
  before: { B: VizLayer; A: VizLayer; C: VizLayer };    // 压缩前
  after:  { B: VizLayer; A: VizLayer; C: VizLayer };    // 压缩后
  diff: {
    retained: string[];                                    // 保留节点 ID
    compressed: string[];                                  // 压缩节点 ID
    compressionRatio: number;
    avgRetainedScore: number;
    avgCompressedScore: number;
  };
  stats: {
    totalNodesBefore: number;
    totalNodesAfter: number;
    nodesByLayerBefore: { B: number; A: number; C: number };
    nodesByLayerAfter:  { B: number; A: number; C: number };
    compressionRatio: number;
    retainedContext: number;
  };
  timeline: VizTimelineItem[];      // 执行时间线（用于前端渲染）
  discarded: { nodeId: string; reason: string }[];  // 丢弃详情
}
```

### 前端渲染组件

见 `3-FRONTEND/dream-universal-gateway/src/components/graph-compression-viz/`：

- `GraphCompressionVisualizer.tsx`: 主组件（压缩前后三层图对比 + 时间线）
- 在对话界面中，消息底部可嵌入压缩状态摘要

---

## 🔍 典型使用场景

### 场景1：对话转向

> "我们换个话题之前，先总结一下之前的讨论"

调用：
```
压缩目标：当前主题的所有消息
预期输出：主题结构摘要，保留关键决策，压缩细节讨论
```

### 场景2：策略研究长对话

> "帮我看看我们刚才讨论的策略，哪些是关键决策点"

调用：
```
压缩目标：10+ 条策略讨论消息
预期输出：保留关键参数决策、风险判断、执行步骤，压缩工具调用细节
```

### 场景3：上下文超限预警

> "上下文将超过 token 限制，需要压缩"

调用：
```
压缩目标：整个对话历史（> 100 消息）
预期输出：自动切换分片模式，按时间分片压缩，保留关键决策
```

---

## ✅ 成功标准

1. **构建成功**：三层图结构正确构建，节点数合理
2. **压缩有效**：压缩率在目标范围内（±20%），关键节点未被压缩
3. **信息保留**：用户提问 "关键决策是什么" 时，压缩结果中可找到答案
4. **可追溯性**：任意压缩节点都能展开为原始上下文引用
5. **可视化可用**：输出数据可直接渲染为前端组件

---

## 📝 版本记录

| 版本 | 日期 | 变更 |
|-----|------|------|
| v1.0.0 | 2026-06-21 | 初始版本，支持三层图构建与语义感知压缩 |

---

*依赖：`6-图结构上下文压缩/` 通用模块（contract.ts + semantic-compressor.ts + blueprint-registry.ts + visualization.ts）*

# 图架构模块升级设计方案

> **日期**: 2026-06-28
> **版本**: v1.0
> **目标**: 给图结构上下文压缩模块增加 State + Checkpoint + HITL + 并行链路能力

---

## 一、整体架构

```
用户意图
   ↓
IntentGateway（意图识别）
   ↓
ChainPlanner（B层规划）
   - 知识库、历史、预算等综合判断
   - 输出：市场形态 + 推荐路径
   ↓
B 层 = 规划好的路径（静态骨架）
   ↓
A 层 = 执行骨架
   - State（运行时状态）        ← 新增
   - Checkpoint（断点持久化）   ← 新增
   - 并行链路（parallelGroup）  ← 新增
   - HITL（人机协作，可选）     ← 新增
   ↓
LLM 根据 A 层骨架执行，置信度不足时动态调整（迭代/降级/插入）
   ↓
C 层 = 执行轨迹压缩（Chronicle）
```

**核心原则**：
- 图架构只是规划路径，不直接执行分析
- LLM 是实际工作分析研究的核心
- AI 动态链（置信度驱动）属于 LLM 工作机制，不作为独立层

---

## 二、Phase 1 — State + Checkpoint

### 2.1 目标

给 A 层执行增加"运行时状态 + 断点续跑"能力，让执行过程可追溯、可回滚。

### 2.2 新增文件

| 文件 | 位置 | 职责 |
|------|------|------|
| `graph-state.ts` | `6-图结构上下文压缩/` | State 类型定义 + 状态管理器 |
| `graph-checkpointer.ts` | `6-图结构上下文压缩/` | 断点持久化（扩展现有 graph-persistence.ts）|

### 2.3 State 结构

```typescript
interface GraphState {
  // 当前执行位置
  currentNodeId: string;

  // 各节点执行结果
  nodeResults: Map<string, NodeResult>;

  // 当前置信度
  confidence: number;

  // 已消耗 Token
  tokenUsed: number;

  // 上下文摘要
  contextSummary: string;

  // 元数据
  metadata: {
    startedAt: number;       // 开始时间
    lastUpdated: number;     // 最后更新时间
    hitlEnabled: boolean;    // HITL 开关（Phase 2）
    blueprintRef: string;    // 关联的 B 层 ID
  };
}
```

### 2.4 Checkpoint 机制

- **保存时机**：每个节点执行完成后自动保存
- **保存内容**：完整的 GraphState
- **核心 API**：
  - `saveCheckpoint(state: GraphState)` — 保存当前状态
  - `revertToNode(nodeId: string)` — 回滚到指定节点重新执行
  - `getLatestCheckpoint()` — 获取最新检查点
  - `listCheckpoints()` — 列出所有历史检查点

### 2.5 验证方式

1. 现有测试全部通过（chain-planner.test.ts 等）
2. 新增 State + Checkpoint 单元测试
3. 集成验证：模拟多步骤思维链（S1→S2→S3），在任意节点中断并恢复

---

## 三、Phase 2 — HITL 人机协作

### 3.1 目标

在关键节点前可中断，等人类确认后再继续（可选开关，不影响生产环境）。

### 3.2 开关机制

```typescript
// 通过 State metadata 控制
state.metadata.hitlEnabled = true;   // 开发/研究模式
state.metadata.hitlEnabled = false;  // 实盘执行模式
```

### 3.3 节点扩展

```typescript
interface ANode {
  // ... 现有字段 ...

  // HITL 相关
  interruptBefore?: boolean;   // 是否在此节点前中断
  interruptLabel?: string;    // 中断提示（如"即将执行下单操作"）
  riskLevel?: 'low' | 'medium' | 'high';  // 风险等级
}
```

### 3.4 中断流程

```
节点执行前
   ↓
检查 interruptBefore + hitlEnabled
   ↓
[是] → 暂停，输出节点信息 + 风险提示
         等待外部信号（approve/reject/edit）
         ↓
         接收到信号 → 继续 / 拒绝 / 修改后执行
[否] → 继续执行
```

### 3.5 验证方式

1. 模拟 S4/S5 节点设置 interruptBefore=true
2. 验证执行是否正确暂停并等待信号
3. 验证收到 approve/reject 后行为正确

---

## 四、Phase 3 — A 层并行链路

### 4.1 目标

同组节点并行执行，完了再汇入主流程。

### 4.2 节点扩展

```typescript
interface ANode {
  // ... 现有字段 ...

  // 并行相关
  parallelGroup?: string;       // 同组并行标记（如 "market_scan"）
  mergeStrategy?: 'all' | 'any';  // 汇总策略
}
```

### 4.3 执行语义

```
A 层执行到并行节点
   ↓
识别 parallelGroup，找到同组所有节点
   ↓
同组节点并行执行（Promise.all 或类似）
   ↓
等待全部完成（根据 mergeStrategy 决定是否等待全部）
   ↓
汇总结果，继续后续边
```

### 4.4 示例

```typescript
// 三者并行分析，同时执行
{ id: "C1_技术扫描", parallelGroup: "market_scan" }
{ id: "F1_新闻扫描", parallelGroup: "market_scan" }
{ id: "F2_资金流", parallelGroup: "market_scan" }

// 汇入点
{ id: "S2_分析", requires: ["C1_技术扫描", "F1_新闻扫描", "F2_资金流"] }
```

### 4.5 验证方式

1. 创建带 parallelGroup 的测试用例
2. 验证同组节点确实并行执行
3. 验证汇入节点正确等待并接收所有结果

---

## 五、实施顺序

```
Phase 1 → Phase 2 → Phase 3
  ↓           ↓           ↓
State +    HITL      并行链路
Checkpoint
```

**Phase 1 是基础**，Phase 2 和 3 依赖 Phase 1 的 State 模型。

---

## 六、风险控制

1. **不改现有接口**：新增文件，不修改现有 types.ts 等核心类型文件
2. **可选开关**：HITL 和并行都是可选特性，不影响现有流程
3. **每阶段验证**：每个 Phase 完成后必须验证通过才进入下一阶段
4. **向后兼容**：新增的 State/Checkpoint 不影响现有 Chronicle 压缩逻辑

# 图结构上下文压缩 — 接口规格

> **版本**：v1.0 | **更新日期**：2026-10-11

## 1. 核心接口

### 1.1 压缩器接口

```typescript
interface Compressor {
  compress(context: GraphContext): CompressedContext;
  decompress(compressed: CompressedContext): GraphContext;
}
```

### 1.2 图状态接口

```typescript
class GraphState {
  addNode(node: GraphNode): void;
  addEdge(edge: GraphEdge): void;
  getNode(id: string): GraphNode | undefined;
  getEdges(from: string): GraphEdge[];
  serialize(): SerializedGraph;
  static deserialize(data: SerializedGraph): GraphState;
}
```

### 1.3 图执行器接口

```typescript
class GraphExecutor {
  execute(graph: GraphState, inputs: Record<string, any>): ExecutionResult;
  parallelExecute(graph: GraphState): ParallelExecutionResult;
}
```

### 1.4 HITL 接口

```typescript
class GraphHITL {
  requestHumanInput(nodeId: string, question: string): Promise<HumanResponse>;
  approve(nodeId: string): void;
  reject(nodeId: string, reason: string): void;
}
```

## 2. 蓝图接口

```typescript
class BlueprintRegistry {
  register(blueprint: Blueprint): void;
  get(id: string): Blueprint | undefined;
  list(): Blueprint[];
}
```

## 3. 意图网关接口

```typescript
class IntentGateway {
  route(intent: Intent): RouteResult;
  registerHandler(type: string, handler: IntentHandler): void;
}
```

## 4. 类型定义

完整类型定义见 [types.ts](../types.ts)、[models.ts](../models.ts)、[contract.ts](../contract.ts)。

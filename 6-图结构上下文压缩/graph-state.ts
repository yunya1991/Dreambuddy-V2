/**
 * ============================================================
 *  📊 图执行状态管理 (Graph State)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-state.ts
 *
 * Phase 1 核心模块：为 A 层执行增加运行时状态管理能力
 *
 * 设计原则：
 * 1. 与现有类型兼容（ANode, ArchitectureGraph, BlueprintGraph）
 * 2. 最小化 State，仅包含运行时必需字段
 * 3. 可选 HITL 支持（通过 metadata.hitlEnabled 控制）
 */

import type { NodeId, ANode, ArchitectureGraph, BlueprintGraph } from './models';

// ============================================================
// 节点执行结果
// ============================================================

export interface NodeResult {
  /** 节点 ID */
  nodeId: NodeId;

  /** 节点名称 */
  nodeName: string;

  /** 执行状态 */
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'cancelled';

  /** 输出摘要 */
  outputSummary?: string;

  /** Token 消耗 */
  tokenCost: number;

  /** 执行延迟（毫秒） */
  latencyMs: number;

  /** 置信度（0-1） */
  confidence: number;

  /** 输出数据 */
  outputs: Record<string, unknown>;

  /** 执行时间 */
  startedAt: number;
  completedAt?: number;

  /** 错误信息（如果失败） */
  error?: string;
}

// ============================================================
// Graph State — 运行时状态
// ============================================================

export interface GraphStateMetadata {
  /** 开始时间 */
  startedAt: number;

  /** 最后更新时间 */
  lastUpdated: number;

  /** HITL 开关（Phase 2）*/
  hitlEnabled: boolean;

  /** 关联的 B 层 ID */
  blueprintRef: string;

  /** 关联的 A 层 ID */
  architectureRef: string;

  /** 执行 ID（用于区分不同次执行） */
  executionId: string;
}

export interface GraphState {
  /** 当前执行节点 ID */
  currentNodeId: NodeId;

  /** 各节点执行结果 */
  nodeResults: Map<NodeId, NodeResult>;

  /** 当前置信度（0-1） */
  confidence: number;

  /** 已消耗 Token */
  tokenUsed: number;

  /** 上下文摘要 */
  contextSummary: string;

  /** 元数据 */
  metadata: GraphStateMetadata;
}

// ============================================================
// State 快照（用于 Checkpoint）
// ============================================================

export interface GraphStateSnapshot {
  /** 快照 ID */
  id: string;

  /** 快照时间 */
  timestamp: number;

  /** 对应的节点 ID（快照是在哪个节点执行后保存的） */
  nodeId: NodeId;

  /** 快照数据 */
  state: SerializedGraphState;
}

// 序列化版本（用于存储）
export interface SerializedGraphState {
  currentNodeId: NodeId;
  nodeResults: [NodeId, NodeResult][];  // Map → Array for JSON
  confidence: number;
  tokenUsed: number;
  contextSummary: string;
  metadata: GraphStateMetadata;
}

// ============================================================
// State 管理器
// ============================================================

export interface StateManagerConfig {
  /** 目标 A 层 */
  architecture: ArchitectureGraph;

  /** 关联的 B 层 */
  blueprint: BlueprintGraph;

  /** 是否启用 HITL */
  hitlEnabled?: boolean;

  /** 最大 Token 预算 */
  maxTokenBudget?: number;

  /** 置信度阈值（低于此值触发警告） */
  confidenceThreshold?: number;
}

export class GraphStateManager {
  private state: GraphState;
  private config: StateManagerConfig;

  constructor(config: StateManagerConfig) {
    this.config = {
      hitlEnabled: false,
      maxTokenBudget: 8000,
      confidenceThreshold: 0.6,
      ...config,
    };

    this.state = this.createInitialState();
  }

  /**
   * 创建初始状态
   */
  private createInitialState(): GraphState {
    const entryPoint = this.config.architecture.entryPoint;
    return {
      currentNodeId: entryPoint,
      nodeResults: new Map(),
      confidence: 0,
      tokenUsed: 0,
      contextSummary: '',
      metadata: {
        startedAt: Date.now(),
        lastUpdated: Date.now(),
        hitlEnabled: this.config.hitlEnabled ?? false,
        blueprintRef: this.config.blueprint.id,
        architectureRef: this.config.architecture.id,
        executionId: `exec_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      },
    };
  }

  /**
   * 获取当前状态
   */
  getState(): GraphState {
    return this.state;
  }

  /**
   * 获取当前状态（序列化版本）
   */
  getSerializedState(): SerializedGraphState {
    return {
      currentNodeId: this.state.currentNodeId,
      nodeResults: Array.from(this.state.nodeResults.entries()),
      confidence: this.state.confidence,
      tokenUsed: this.state.tokenUsed,
      contextSummary: this.state.contextSummary,
      metadata: this.state.metadata,
    };
  }

  /**
   * 从快照恢复状态
   */
  restoreFromSnapshot(snapshot: SerializedGraphState): void {
    this.state = {
      currentNodeId: snapshot.currentNodeId,
      nodeResults: new Map(snapshot.nodeResults),
      confidence: snapshot.confidence,
      tokenUsed: snapshot.tokenUsed,
      contextSummary: snapshot.contextSummary,
      metadata: snapshot.metadata,
    };
  }

  /**
   * 推进到下一个节点
   */
  advanceTo(nodeId: NodeId): void {
    this.state.currentNodeId = nodeId;
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 记录节点开始执行
   */
  recordNodeStart(nodeId: NodeId): void {
    const node = this.config.architecture.nodes.get(nodeId);
    if (!node) return;

    this.state.nodeResults.set(nodeId, {
      nodeId,
      nodeName: node.name,
      status: 'running',
      tokenCost: 0,
      latencyMs: 0,
      confidence: 0,
      outputs: {},
      startedAt: Date.now(),
    });
    this.state.currentNodeId = nodeId;
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 记录节点执行完成
   */
  recordNodeComplete(
    nodeId: NodeId,
    result: {
      outputSummary?: string;
      tokenCost: number;
      latencyMs: number;
      confidence: number;
      outputs: Record<string, unknown>;
    }
  ): void {
    const existing = this.state.nodeResults.get(nodeId);
    if (!existing) return;

    const updated: NodeResult = {
      ...existing,
      status: 'completed',
      outputSummary: result.outputSummary,
      tokenCost: result.tokenCost,
      latencyMs: result.latencyMs,
      confidence: result.confidence,
      outputs: result.outputs,
      completedAt: Date.now(),
    };

    this.state.nodeResults.set(nodeId, updated);
    this.state.tokenUsed += result.tokenCost;
    this.state.confidence = result.confidence;
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 记录节点失败
   */
  recordNodeFailure(nodeId: NodeId, error: string): void {
    const existing = this.state.nodeResults.get(nodeId);
    if (!existing) return;

    const updated: NodeResult = {
      ...existing,
      status: 'failed',
      error,
      completedAt: Date.now(),
    };

    this.state.nodeResults.set(nodeId, updated);
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 记录节点跳过
   */
  recordNodeSkip(nodeId: NodeId, reason: string): void {
    const existing = this.state.nodeResults.get(nodeId);
    if (!existing) return;

    const updated: NodeResult = {
      ...existing,
      status: 'skipped',
      outputSummary: reason,
      completedAt: Date.now(),
    };

    this.state.nodeResults.set(nodeId, updated);
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 获取指定节点的结果
   */
  getNodeResult(nodeId: NodeId): NodeResult | undefined {
    return this.state.nodeResults.get(nodeId);
  }

  /**
   * 获取所有已完成节点的结果
   */
  getCompletedNodes(): NodeResult[] {
    return Array.from(this.state.nodeResults.values()).filter(
      (r) => r.status === 'completed'
    );
  }

  /**
   * 检查是否应该中断（基于 HITL 配置）
   */
  shouldInterrupt(nodeId: NodeId): boolean {
    if (!this.state.metadata.hitlEnabled) return false;

    const node = this.config.architecture.nodes.get(nodeId);
    if (!node) return false;

    // 检查节点是否标记了 interruptBefore
    return (node as any).interruptBefore === true;
  }

  /**
   * 获取下一个可执行节点（根据依赖关系）
   */
  getNextExecutableNodes(): NodeId[] {
    const nextNodes: NodeId[] = [];

    for (const [nodeId, node] of this.config.architecture.nodes) {
      // 跳过已完成的节点
      const result = this.state.nodeResults.get(nodeId);
      if (result?.status === 'completed' || result?.status === 'skipped') {
        continue;
      }

      // 检查依赖是否都满足
      if (node.requires && node.requires.length > 0) {
        const allDepsCompleted = node.requires.every((depId) => {
          const depResult = this.state.nodeResults.get(depId);
          return depResult?.status === 'completed';
        });

        if (!allDepsCompleted) continue;
      }

      nextNodes.push(nodeId);
    }

    return nextNodes;
  }

  /**
   * 检查是否所有节点都已完成
   */
  isComplete(): boolean {
    for (const [, node] of this.config.architecture.nodes) {
      const result = this.state.nodeResults.get(node.id);
      if (!result || (result.status !== 'completed' && result.status !== 'skipped')) {
        return false;
      }
    }
    return true;
  }

  /**
   * 检查 Token 预算是否超限
   */
  isOverBudget(): boolean {
    return this.state.tokenUsed >= (this.config.maxTokenBudget ?? 8000);
  }

  /**
   * 获取执行摘要
   */
  getExecutionSummary(): {
    totalNodes: number;
    completedNodes: number;
    failedNodes: number;
    skippedNodes: number;
    tokenUsed: number;
    totalLatencyMs: number;
    finalConfidence: number;
    executionId: string;
  } {
    const results = Array.from(this.state.nodeResults.values());
    return {
      totalNodes: this.config.architecture.nodes.size,
      completedNodes: results.filter((r) => r.status === 'completed').length,
      failedNodes: results.filter((r) => r.status === 'failed').length,
      skippedNodes: results.filter((r) => r.status === 'skipped').length,
      tokenUsed: this.state.tokenUsed,
      totalLatencyMs: results.reduce((sum, r) => sum + r.latencyMs, 0),
      finalConfidence: this.state.confidence,
      executionId: this.state.metadata.executionId,
    };
  }

  /**
   * 更新上下文摘要
   */
  updateContextSummary(summary: string): void {
    this.state.contextSummary = summary;
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 启用/禁用 HITL
   */
  setHitlEnabled(enabled: boolean): void {
    this.state.metadata.hitlEnabled = enabled;
    this.state.metadata.lastUpdated = Date.now();
  }

  /**
   * 创建检查点快照
   */
  createSnapshot(nodeId: NodeId): GraphStateSnapshot {
    return {
      id: `snap_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      timestamp: Date.now(),
      nodeId,
      state: this.getSerializedState(),
    };
  }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 从序列化状态恢复 Map
 */
export function deserializeNodeResults(
  entries: [NodeId, NodeResult][]
): Map<NodeId, NodeResult> {
  return new Map(entries);
}

/**
 * 状态是否可继续执行
 */
export function canContinue(state: GraphState): boolean {
  if (state.metadata.lastUpdated === 0) return true;
  return true; // 可以扩展更多检查逻辑
}

/**
 * ============================================================
 *  🔄  图执行引擎 (Graph Execution Engine)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-executor.ts
 *
 * Phase 2 核心：将 State + Checkpoint + HITL 整合为统一执行引擎
 *
 * 不修改现有 graph-state.ts 和 graph-checkpointer.ts，
 * 通过组合模式提供统一的执行接口。
 */

import { GraphStateManager } from './graph-state';
import { GraphCheckpointer } from './graph-checkpointer';
import { HITLManager, type HITLNode, type InterruptContext, type InterruptDecisionResult } from './graph-hitl';
import type { ArchitectureGraph, BlueprintGraph, ANode, NodeId } from './models';

// ============================================================
// 执行引擎配置
// ============================================================

export interface GraphExecutorConfig {
  architecture: ArchitectureGraph;
  blueprint: BlueprintGraph;

  /** 是否启用 HITL */
  hitlEnabled?: boolean;

  /** HITL 配置 */
  hitlConfig?: {
    defaultTimeoutMs?: number;
    autoApproveLowRisk?: boolean;
    requireHumanForHighRisk?: boolean;
  };

  /** Checkpoint 配置 */
  checkpointConfig?: {
    storageDir?: string;
    autoSave?: boolean;
    maxCheckpoints?: number;
  };

  /** 最大 Token 预算 */
  maxTokenBudget?: number;

  /** 置信度阈值 */
  confidenceThreshold?: number;
}

// ============================================================
// 节点处理函数类型
// ============================================================

export type NodeHandler = (
  node: ANode,
  context: ExecutionContext
) => Promise<NodeHandlerResult> | NodeHandlerResult;

export interface NodeHandlerResult {
  outputSummary?: string;
  tokenCost: number;
  latencyMs: number;
  confidence: number;
  outputs: Record<string, unknown>;
  shouldInterrupt?: boolean;
}

export interface ExecutionContext {
  stateManager: GraphStateManager;
  checkpointer: GraphCheckpointer;
  hitlManager: HITLManager;
  architecture: ArchitectureGraph;
  blueprint: BlueprintGraph;
}

// ============================================================
// 执行引擎
// ============================================================

export class GraphExecutor {
  private config: GraphExecutorConfig;
  private stateManager: GraphStateManager;
  private checkpointer: GraphCheckpointer;
  private hitlManager: HITLManager;
  private executionId: string;
  private nodeHandlers: Map<string, NodeHandler> = new Map();
  private isRunning = false;

  constructor(config: GraphExecutorConfig) {
    this.config = {
      hitlEnabled: false,
      maxTokenBudget: 8000,
      confidenceThreshold: 0.6,
      ...config,
    };

    this.executionId = `exec_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    // 初始化各组件
    this.stateManager = new GraphStateManager({
      architecture: config.architecture,
      blueprint: config.blueprint,
      maxTokenBudget: this.config.maxTokenBudget,
      confidenceThreshold: this.config.confidenceThreshold,
      hitlEnabled: this.config.hitlEnabled ?? false,
    });

    this.checkpointer = new GraphCheckpointer(
      this.executionId,
      config.architecture,
      config.blueprint,
      this.config.checkpointConfig
    );

    this.hitlManager = new HITLManager({
      enabled: this.config.hitlEnabled ?? false,
      ...this.config.hitlConfig,
    });
  }

  /**
   * 注册节点处理函数
   */
  registerNodeHandler(nodeId: string, handler: NodeHandler): void {
    this.nodeHandlers.set(nodeId, handler);
  }

  /**
   * 注册默认节点处理函数（用于未单独注册的节点）
   */
  setDefaultHandler(handler: NodeHandler): void {
    this.defaultHandler = handler;
  }

  private defaultHandler: NodeHandler = async (node) => {
    return {
      outputSummary: `执行 ${node.name}`,
      tokenCost: 100,
      latencyMs: 500,
      confidence: 0.8,
      outputs: {},
    };
  };

  /**
   * 获取 StateManager
   */
  getStateManager(): GraphStateManager {
    return this.stateManager;
  }

  /**
   * 获取 Checkpointer
   */
  getCheckpointer(): GraphCheckpointer {
    return this.checkpointer;
  }

  /**
   * 获取 HITL 管理器
   */
  getHITLManager(): HITLManager {
    return this.hitlManager;
  }

  /**
   * 获取执行 ID
   */
  getExecutionId(): string {
    return this.executionId;
  }

  /**
   * 执行完整流程
   */
  async execute(): Promise<{
    success: boolean;
    completedNodes: number;
    totalNodes: number;
    tokenUsed: number;
    finalConfidence: number;
    interrupts: InterruptContext[];
    error?: string;
  }> {
    if (this.isRunning) {
      return {
        success: false,
        completedNodes: 0,
        totalNodes: this.config.architecture.nodes.size,
        tokenUsed: 0,
        finalConfidence: 0,
        interrupts: [],
        error: '执行中，请勿重复调用',
      };
    }

    this.isRunning = true;
    const interrupts: InterruptContext[] = [];

    try {
      while (!this.stateManager.isComplete()) {
        // 获取下一个可执行节点
        const nextNodes = this.stateManager.getNextExecutableNodes();

        if (nextNodes.length === 0) {
          break;
        }

        const nodeId = nextNodes[0];
        const node = this.config.architecture.nodes.get(nodeId);
        if (!node) break;

        // 检查 HITL 中断
        const hitlNode = node as HITLNode;
        if (this.hitlManager.shouldInterrupt(hitlNode)) {
          const interrupt = this.hitlManager.createInterrupt(
            hitlNode,
            this.stateManager.getState(),
            {}
          );
          interrupts.push(interrupt);

          // 等待人类决策
          const decision = await this.hitlManager.waitForResolution(
            interrupt.interruptId
          );

          if (decision.decision === 'reject') {
            // 拒绝则跳过节点
            this.stateManager.recordNodeStart(nodeId);
            this.stateManager.recordNodeSkip(nodeId, '人工拒绝执行');
            this.checkpointer.saveCheckpoint(
              this.stateManager.createSnapshot(nodeId)
            );
            continue;
          }

          if (decision.decision === 'approve' || decision.decision === 'edit') {
            // 通过或修改后继续执行
          }
        }

        // 执行节点
        const handler = this.nodeHandlers.get(nodeId) ?? this.defaultHandler;

        this.stateManager.recordNodeStart(nodeId);

        const context: ExecutionContext = {
          stateManager: this.stateManager,
          checkpointer: this.checkpointer,
          hitlManager: this.hitlManager,
          architecture: this.config.architecture,
          blueprint: this.config.blueprint,
        };

        const result = await handler(node, context);

        this.stateManager.recordNodeComplete(nodeId, result);
        this.stateManager.advanceTo(nodeId);

        // 保存检查点
        this.checkpointer.saveCheckpoint(
          this.stateManager.createSnapshot(nodeId)
        );

        // Token 超预算检查
        if (this.stateManager.isOverBudget()) {
          return {
            success: false,
            completedNodes: this.stateManager.getCompletedNodes().length,
            totalNodes: this.config.architecture.nodes.size,
            tokenUsed: this.stateManager.getState().tokenUsed,
            finalConfidence: this.stateManager.getState().confidence,
            interrupts,
            error: 'Token 预算超限',
          };
        }
      }

      const summary = this.stateManager.getExecutionSummary();

      return {
        success: true,
        completedNodes: summary.completedNodes,
        totalNodes: summary.totalNodes,
        tokenUsed: summary.tokenUsed,
        finalConfidence: summary.finalConfidence,
        interrupts,
      };
    } catch (error) {
      return {
        success: false,
        completedNodes: this.stateManager.getCompletedNodes().length,
        totalNodes: this.config.architecture.nodes.size,
        tokenUsed: this.stateManager.getState().tokenUsed,
        finalConfidence: this.stateManager.getState().confidence,
        interrupts,
        error: error instanceof Error ? error.message : String(error),
      };
    } finally {
      this.isRunning = false;
    }
  }

  /**
   * 从检查点恢复并继续执行
   */
  async resumeFromCheckpoint(nodeId: NodeId): Promise<void> {
    const restoredState = this.checkpointer.revertToNode(nodeId);
    if (restoredState) {
      this.stateManager.restoreFromSnapshot(restoredState);
    }
  }

  /**
   * 中断当前执行
   */
  pause(): void {
    // 设置标志，下一个节点前停止
    this.isRunning = false;
  }

  /**
   * 是否正在执行
   */
  getIsRunning(): boolean {
    return this.isRunning;
  }

  /**
   * 获取执行摘要
   */
  getExecutionSummary() {
    return {
      ...this.stateManager.getExecutionSummary(),
      executionId: this.executionId,
      hitlEnabled: this.hitlManager.isEnabled(),
      checkpointCount: this.checkpointer.getCheckpointCount(),
    };
  }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建执行引擎
 */
export function createGraphExecutor(
  config: GraphExecutorConfig
): GraphExecutor {
  return new GraphExecutor(config);
}

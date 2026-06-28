/**
 * ============================================================
 *  ⚡  增强版图执行引擎（支持并行链路）
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-parallel-executor.ts
 *
 * Phase 3：在 GraphExecutor 基础上增加并行链路支持
 *
 * 不修改 graph-executor.ts，通过继承/组合方式实现。
 */

import { GraphExecutor, type GraphExecutorConfig, type NodeHandler, type ExecutionContext } from './graph-executor';
import { ParallelScheduler, type ParallelSchedulerConfig, getGroupRepresentative } from './graph-parallel';
import type { ArchitectureGraph, BlueprintGraph, ANode, NodeId } from './models';

// ============================================================
// 增强版执行器配置
// ============================================================

export interface ParallelGraphExecutorConfig extends GraphExecutorConfig {
  /** 并行调度配置 */
  parallelConfig?: ParallelSchedulerConfig;
}

// ============================================================
// 增强版执行器
// ============================================================

export class ParallelGraphExecutor extends GraphExecutor {
  private parallelScheduler: ParallelScheduler;
  private parallelGroups: Map<string, NodeId[]>;
  private nodeToGroup: Map<NodeId, string>;
  private completedGroups: Set<string> = new Set();

  constructor(config: ParallelGraphExecutorConfig) {
    super(config);

    this.parallelScheduler = new ParallelScheduler(config.parallelConfig);

    // 识别并行组
    this.parallelGroups = this.parallelScheduler.identifyParallelGroups(
      config.architecture.nodes
    );

    // 构建节点到组的映射
    this.nodeToGroup = new Map();
    for (const [groupId, nodeIds] of this.parallelGroups) {
      for (const nodeId of nodeIds) {
        this.nodeToGroup.set(nodeId, groupId);
      }
    }
  }

  /**
   * 获取并行调度器
   */
  getParallelScheduler(): ParallelScheduler {
    return this.parallelScheduler;
  }

  /**
   * 获取所有并行组
   */
  getParallelGroups(): Map<string, NodeId[]> {
    return new Map(this.parallelGroups);
  }

  /**
   * 获取节点所属的并行组
   */
  getNodeGroup(nodeId: NodeId): string | null {
    return this.nodeToGroup.get(nodeId) ?? null;
  }

  /**
   * 执行完整流程（支持并行）
   */
  async execute(): Promise<{
    success: boolean;
    completedNodes: number;
    totalNodes: number;
    tokenUsed: number;
    finalConfidence: number;
    parallelGroups: number;
    error?: string;
  }> {
    const stateManager = this.getStateManager();
    const checkpointer = this.getCheckpointer();
    const hitlManager = this.getHITLManager();
    const arch = (this as any).config.architecture as ArchitectureGraph;

    let completedGroups = 0;
    const processedGroups = new Set<string>();
    const completedNodesSet = new Set<NodeId>();

    try {
      let iteration = 0;
      const maxIterations = arch.nodes.size * 2; // 防止死循环

      while (!stateManager.isComplete() && iteration < maxIterations) {
        iteration++;

        // 获取下一个可执行节点
        const nextNodes = stateManager.getNextExecutableNodes();

        if (nextNodes.length === 0) {
          break;
        }

        // 检查是否有并行组可以执行
        let groupExecuted = false;

        for (const nodeId of nextNodes) {
          const groupId = this.nodeToGroup.get(nodeId);

          if (groupId && !processedGroups.has(groupId)) {
            const groupNodeIds = this.parallelGroups.get(groupId);
            if (!groupNodeIds) continue;

            // 检查组是否所有节点的依赖都满足（排除组内依赖）
            if (this.canExecuteGroup(groupNodeIds, completedNodesSet)) {
              // 执行并行组
              await this.executeGroup(groupId, groupNodeIds);
              processedGroups.add(groupId);
              completedGroups++;

              // 标记组内节点为已完成
              for (const nid of groupNodeIds) {
                completedNodesSet.add(nid);
              }

              groupExecuted = true;
              break; // 执行完一个组后重新检查
            }
          }
        }

        if (groupExecuted) {
          continue;
        }

        // 没有可执行的并行组，执行单个非并行节点
        const nonParallelNode = nextNodes.find(
          (nid) => !this.nodeToGroup.has(nid)
        );

        if (!nonParallelNode) {
          // 没有可执行的节点了
          break;
        }

        // 执行单个节点（调用父类逻辑）
        await this.executeSingleNode(nonParallelNode);
        completedNodesSet.add(nonParallelNode);
      }

      const summary = stateManager.getExecutionSummary();

      return {
        success: true,
        completedNodes: summary.completedNodes,
        totalNodes: summary.totalNodes,
        tokenUsed: summary.tokenUsed,
        finalConfidence: summary.finalConfidence,
        parallelGroups: completedGroups,
      };
    } catch (error) {
      const summary = stateManager.getExecutionSummary();

      return {
        success: false,
        completedNodes: summary.completedNodes,
        totalNodes: summary.totalNodes,
        tokenUsed: summary.tokenUsed,
        finalConfidence: summary.finalConfidence,
        parallelGroups: completedGroups,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  }

  /**
   * 执行单个节点（包含 HITL 检查）
   */
  private async executeSingleNode(nodeId: NodeId): Promise<void> {
    const stateManager = this.getStateManager();
    const checkpointer = this.getCheckpointer();
    const hitlManager = this.getHITLManager();
    const arch = (this as any).config.architecture as ArchitectureGraph;
    const nodeHandlers = (this as any).nodeHandlers as Map<string, NodeHandler>;
    const defaultHandler = (this as any).defaultHandler as NodeHandler;

    const node = arch.nodes.get(nodeId);
    if (!node) return;

    // 检查 HITL 中断
    if (hitlManager.shouldInterrupt(node as any)) {
      const interrupt = hitlManager.createInterrupt(
        node as any,
        stateManager.getState(),
        {}
      );
      const decision = await hitlManager.waitForResolution(interrupt.interruptId);

      if (decision.decision === 'reject') {
        stateManager.recordNodeStart(nodeId);
        stateManager.recordNodeSkip(nodeId, '人工拒绝执行');
        checkpointer.saveCheckpoint(stateManager.createSnapshot(nodeId));
        return;
      }
    }

    // 执行节点
    const handler = nodeHandlers.get(nodeId) ?? defaultHandler;

    stateManager.recordNodeStart(nodeId);

    const context: ExecutionContext = {
      stateManager,
      checkpointer,
      hitlManager,
      architecture: arch,
      blueprint: (this as any).config.blueprint as BlueprintGraph,
    };

    const result = await handler(node, context);

    stateManager.recordNodeComplete(nodeId, result);
    stateManager.advanceTo(nodeId);

    // 保存检查点
    checkpointer.saveCheckpoint(stateManager.createSnapshot(nodeId));
  }

  /**
   * 执行并行组
   */
  private async executeGroup(
    groupId: string,
    groupNodeIds: NodeId[]
  ): Promise<void> {
    const stateManager = this.getStateManager();
    const checkpointer = this.getCheckpointer();
    const hitlManager = this.getHITLManager();
    const arch = (this as any).config.architecture as ArchitectureGraph;
    const nodeHandlers = (this as any).nodeHandlers as Map<string, NodeHandler>;
    const defaultHandler = (this as any).defaultHandler as NodeHandler;

    const context: ExecutionContext = {
      stateManager,
      checkpointer,
      hitlManager,
      architecture: arch,
      blueprint: (this as any).config.blueprint as BlueprintGraph,
    };

    // 先检查组内节点是否需要 HITL 中断
    // 对于并行组，我们只检查代表节点的 HITL 配置
    const repNodeId = getGroupRepresentative(groupNodeIds);
    const repNode = arch.nodes.get(repNodeId);
    if (repNode && hitlManager.shouldInterrupt(repNode as any)) {
      const interrupt = hitlManager.createInterrupt(
        repNode as any,
        stateManager.getState(),
        { parallelGroup: groupId, parallelNodes: groupNodeIds.length }
      );
      const decision = await hitlManager.waitForResolution(interrupt.interruptId);

      if (decision.decision === 'reject') {
        // 整个组被拒绝
        for (const nid of groupNodeIds) {
          stateManager.recordNodeStart(nid);
          stateManager.recordNodeSkip(nid, '人工拒绝执行并行组');
        }
        checkpointer.saveCheckpoint(stateManager.createSnapshot(repNodeId));
        return;
      }
    }

    // 标记所有节点开始执行
    for (const nid of groupNodeIds) {
      stateManager.recordNodeStart(nid);
    }

    // 并行执行
    const parallelResult = await this.parallelScheduler.executeParallelGroup(
      groupId,
      groupNodeIds,
      arch.nodes,
      nodeHandlers.size > 0 ? nodeHandlers : new Map([['__default__', defaultHandler]]),
      context
    );

    // 记录每个节点的结果
    for (const [nid, result] of parallelResult.results) {
      stateManager.recordNodeComplete(nid, {
        ...result,
        outputs: result.outputs,
      });
    }

    // 推进到代表节点（用于 checkpoint）
    stateManager.advanceTo(repNodeId);

    // 保存检查点（用代表节点）
    checkpointer.saveCheckpoint(stateManager.createSnapshot(repNodeId));
  }

  /**
   * 检查并行组是否可以执行
   */
  private canExecuteGroup(
    groupNodeIds: NodeId[],
    completedNodes: Set<NodeId>
  ): boolean {
    const arch = (this as any).config.architecture as ArchitectureGraph;
    return this.parallelScheduler.canExecuteGroup(
      groupNodeIds,
      arch.nodes,
      completedNodes
    );
  }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建并行执行器
 */
export function createParallelGraphExecutor(
  config: ParallelGraphExecutorConfig
): ParallelGraphExecutor {
  return new ParallelGraphExecutor(config);
}

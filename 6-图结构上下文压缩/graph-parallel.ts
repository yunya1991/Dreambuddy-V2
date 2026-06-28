/**
 * ============================================================
 *  ⚡ 并行节点调度器 (Parallel Scheduler)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-parallel.ts
 *
 * Phase 3 核心模块：A 层并行链路执行
 *
 * 设计原则：
 * 1. 与现有 GraphExecutor 兼容，不修改核心类型
 * 2. 通过 parallelGroup 标记同组并行节点
 * 3. 支持 all/any 两种汇总策略
 * 4. 不修改现有 models.ts，通过扩展接口实现
 */

import type { ANode, NodeId } from './models';
import type { NodeHandler, NodeHandlerResult, ExecutionContext } from './graph-executor';

// ============================================================
// 并行节点扩展类型
// ============================================================

export type ParallelNode = ANode & {
  /** 并行组标识，同组节点并行执行 */
  parallelGroup?: string;

  /** 汇总策略 */
  mergeStrategy?: 'all' | 'any';
};

// ============================================================
// 并行执行结果
// ============================================================

export interface ParallelExecutionResult {
  /** 并行组 ID */
  groupId: string;

  /** 组内节点结果 */
  results: Map<NodeId, NodeHandlerResult>;

  /** 成功节点数 */
  successCount: number;

  /** 失败节点数 */
  failedCount: number;

  /** 总 Token 消耗 */
  totalTokenCost: number;

  /** 总耗时（取最长的那个） */
  totalLatencyMs: number;

  /** 平均置信度 */
  avgConfidence: number;

  /** 合并后的输出 */
  mergedOutput: {
    outputSummary: string;
    outputs: Record<string, unknown>;
  };
}

// ============================================================
// 并行调度器配置
// ============================================================

export interface ParallelSchedulerConfig {
  /** 最大并行数，默认 10 */
  maxConcurrency?: number;

  /** 默认汇总策略 */
  defaultMergeStrategy?: 'all' | 'any';
}

// ============================================================
// 并行调度器
// ============================================================

export class ParallelScheduler {
  private config: Required<ParallelSchedulerConfig>;

  constructor(config?: ParallelSchedulerConfig) {
    this.config = {
      maxConcurrency: 10,
      defaultMergeStrategy: 'all',
      ...config,
    };
  }

  /**
   * 从节点列表中识别并行组
   *
   * 返回 Map<groupId, nodeId[]>
   */
  identifyParallelGroups(nodes: Map<NodeId, ANode>): Map<string, NodeId[]> {
    const groups = new Map<string, NodeId[]>();

    for (const [nodeId, node] of nodes) {
      const parallelNode = node as ParallelNode;
      if (parallelNode.parallelGroup) {
        const groupId = parallelNode.parallelGroup;
        if (!groups.has(groupId)) {
          groups.set(groupId, []);
        }
        groups.get(groupId)!.push(nodeId);
      }
    }

    return groups;
  }

  /**
   * 检查节点是否属于并行组
   */
  isParallelNode(node: ANode): boolean {
    return !!(node as ParallelNode).parallelGroup;
  }

  /**
   * 获取节点的并行组 ID
   */
  getGroupId(node: ANode): string | null {
    return (node as ParallelNode).parallelGroup ?? null;
  }

  /**
   * 获取节点的汇总策略
   */
  getMergeStrategy(node: ANode): 'all' | 'any' {
    return (node as ParallelNode).mergeStrategy ?? this.config.defaultMergeStrategy;
  }

  /**
   * 执行并行组
   *
   * @param groupId 并行组 ID
   * @param nodeIds 组内节点 ID 列表
   * @param nodes 所有节点 Map
   * @param handlers 节点处理器 Map
   * @param context 执行上下文
   * @returns 并行执行结果
   */
  async executeParallelGroup(
    groupId: string,
    nodeIds: NodeId[],
    nodes: Map<NodeId, ANode>,
    handlers: Map<NodeId, NodeHandler>,
    context: ExecutionContext
  ): Promise<ParallelExecutionResult> {
    const results = new Map<NodeId, NodeHandlerResult>();
    let successCount = 0;
    let failedCount = 0;
    let totalTokenCost = 0;
    const startTimes = new Map<NodeId, number>();
    const endTimes = new Map<NodeId, number>();
    const confidences: number[] = [];

    // 分批次执行（受 maxConcurrency 限制）
    const batches = this.chunk(nodeIds, this.config.maxConcurrency);

    for (const batch of batches) {
      const promises = batch.map(async (nodeId) => {
        const node = nodes.get(nodeId);
        if (!node) {
          throw new Error(`节点 ${nodeId} 不存在`);
        }

        const handler = handlers.get(nodeId);
        if (!handler) {
          throw new Error(`节点 ${nodeId} 没有处理器`);
        }

        startTimes.set(nodeId, Date.now());
        try {
          const result = await handler(node, context);
          endTimes.set(nodeId, Date.now());
          return { nodeId, result, success: true };
        } catch (error) {
          endTimes.set(nodeId, Date.now());
          return {
            nodeId,
            result: {
              outputSummary: `执行失败: ${error instanceof Error ? error.message : String(error)}`,
              tokenCost: 0,
              latencyMs: 0,
              confidence: 0,
              outputs: { error: String(error) },
            },
            success: false,
          };
        }
      });

      const batchResults = await Promise.all(promises);

      for (const { nodeId, result, success } of batchResults) {
        results.set(nodeId, result);
        if (success) {
          successCount++;
          confidences.push(result.confidence);
        } else {
          failedCount++;
        }
        totalTokenCost += result.tokenCost;
      }
    }

    // 计算总耗时（取最长的）
    const allStartTimes = Array.from(startTimes.values());
    const allEndTimes = Array.from(endTimes.values());
    const totalLatencyMs = allStartTimes.length > 0
      ? Math.max(...allEndTimes) - Math.min(...allStartTimes)
      : 0;

    // 计算平均置信度
    const avgConfidence = confidences.length > 0
      ? confidences.reduce((a, b) => a + b, 0) / confidences.length
      : 0;

    // 合并输出
    const mergedOutput = this.mergeResults(groupId, results, successCount, failedCount);

    return {
      groupId,
      results,
      successCount,
      failedCount,
      totalTokenCost,
      totalLatencyMs,
      avgConfidence,
      mergedOutput,
    };
  }

  /**
   * 合并并行节点的结果
   */
  private mergeResults(
    groupId: string,
    results: Map<NodeId, NodeHandlerResult>,
    successCount: number,
    failedCount: number
  ): {
    outputSummary: string;
    outputs: Record<string, unknown>;
  } {
    const summaries: string[] = [];
    const mergedOutputs: Record<string, unknown> = {};

    for (const [nodeId, result] of results) {
      if (result.outputSummary) {
        summaries.push(`[${nodeId}] ${result.outputSummary}`);
      }
      // 将每个节点的 outputs 以节点 ID 为键存入合并结果
      mergedOutputs[nodeId] = result.outputs;
    }

    const outputSummary = `并行组 ${groupId} 执行完成（成功 ${successCount}，失败 ${failedCount}）\n${summaries.join('\n')}`;

    return {
      outputSummary,
      outputs: {
        groupId,
        successCount,
        failedCount,
        nodeResults: mergedOutputs,
      },
    };
  }

  /**
   * 检查并行组是否满足执行条件（所有依赖都完成）
   */
  canExecuteGroup(
    groupNodeIds: NodeId[],
    nodes: Map<NodeId, ANode>,
    completedNodes: Set<NodeId>
  ): boolean {
    for (const nodeId of groupNodeIds) {
      const node = nodes.get(nodeId);
      if (!node) return false;

      // 检查节点的依赖
      if (node.requires && node.requires.length > 0) {
        for (const depId of node.requires) {
          // 如果依赖在同一个并行组内，不检查
          if (groupNodeIds.includes(depId)) continue;

          if (!completedNodes.has(depId)) {
            return false;
          }
        }
      }
    }

    return true;
  }

  /**
   * 获取并行组的所有依赖（去重，排除组内依赖）
   */
  getGroupDependencies(
    groupNodeIds: NodeId[],
    nodes: Map<NodeId, ANode>
  ): NodeId[] {
    const deps = new Set<NodeId>();
    const groupSet = new Set(groupNodeIds);

    for (const nodeId of groupNodeIds) {
      const node = nodes.get(nodeId);
      if (!node || !node.requires) continue;

      for (const depId of node.requires) {
        if (!groupSet.has(depId)) {
          deps.add(depId);
        }
      }
    }

    return Array.from(deps);
  }

  /**
   * 获取并行组之后的节点（依赖此组的节点）
   */
  getGroupDependents(
    groupNodeIds: NodeId[],
    nodes: Map<NodeId, ANode>
  ): NodeId[] {
    const groupSet = new Set(groupNodeIds);
    const dependents = new Set<NodeId>();

    for (const [nodeId, node] of nodes) {
      if (groupSet.has(nodeId)) continue;
      if (!node.requires) continue;

      // 如果节点的依赖包含组内的任一节点
      const hasGroupDep = node.requires.some((depId) => groupSet.has(depId));
      if (hasGroupDep) {
        dependents.add(nodeId);
      }
    }

    return Array.from(dependents);
  }

  /**
   * 数组分块
   */
  private chunk<T>(arr: T[], size: number): T[][] {
    const chunks: T[][] = [];
    for (let i = 0; i < arr.length; i += size) {
      chunks.push(arr.slice(i, i + size));
    }
    return chunks;
  }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建并行节点
 */
export function createParallelNode(
  baseNode: ANode,
  parallelConfig: {
    parallelGroup: string;
    mergeStrategy?: 'all' | 'any';
  }
): ParallelNode {
  return {
    ...baseNode,
    parallelGroup: parallelConfig.parallelGroup,
    mergeStrategy: parallelConfig.mergeStrategy,
  };
}

/**
 * 从 ArchitectureGraph 中提取所有并行组
 */
export function extractParallelGroups(
  nodes: Map<NodeId, ANode>
): Map<string, ParallelNode[]> {
  const groups = new Map<string, ParallelNode[]>();

  for (const node of nodes.values()) {
    const pNode = node as ParallelNode;
    if (pNode.parallelGroup) {
      if (!groups.has(pNode.parallelGroup)) {
        groups.set(pNode.parallelGroup, []);
      }
      groups.get(pNode.parallelGroup)!.push(pNode);
    }
  }

  return groups;
}

/**
 * 获取并行组的代表节点（用于 Checkpoint 记录等）
 *
 * 选组内第一个节点作为代表
 */
export function getGroupRepresentative(
  groupNodeIds: NodeId[]
): NodeId {
  return groupNodeIds[0];
}

/**
 * ============================================================
 * 🤖 HITL 人机协作 (Human-in-the-Loop)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-hitl.ts
 *
 * Phase 2 核心模块：为 A 层执行增加人机协作中断能力
 *
 * 设计原则：
 * 1. 可选开关（hitlEnabled），不影响默认流程
 * 2. 中断/恢复机制与 StateManager 解耦
 * 3. 支持多种中断决策（approve/reject/edit）
 * 4. 不修改现有 models.ts 类型，通过扩展接口实现
 */

import type { ANode, NodeId } from './models';
import type { GraphState, NodeResult } from './graph-state';

// ============================================================
// HITL 扩展类型
// ============================================================

export type HITLNode = ANode & {
  /** 是否在此节点前中断 */
  interruptBefore?: boolean;

  /** 中断提示信息 */
  interruptLabel?: string;

  /** 风险等级 */
  riskLevel?: 'low' | 'medium' | 'high';

  /** 需要人类确认的字段列表 */
  approvalFields?: string[];
};

export type InterruptDecision = 'approve' | 'reject' | 'edit';

export interface InterruptContext {
  /** 中断 ID */
  interruptId: string;

  /** 节点 ID */
  nodeId: NodeId;

  /** 节点名称 */
  nodeName: string;

  /** 风险等级 */
  riskLevel: 'low' | 'medium' | 'high';

  /** 中断提示 */
  label: string;

  /** 当前状态摘要 */
  stateSummary: {
    confidence: number;
    tokenUsed: number;
    completedNodes: number;
    totalNodes: number;
  };

  /** 节点输入预览 */
  inputPreview: Record<string, unknown>;

  /** 中断时间 */
  interruptedAt: number;

  /** 是否超时 */
  isExpired?: boolean;

  /** 超时时间（毫秒） */
  timeoutMs?: number;
}

export interface InterruptDecisionResult {
  /** 决策类型 */
  decision: InterruptDecision;

  /** 决策时间 */
  decidedAt: number;

  /** 决策人（可选） */
  decidedBy?: string;

  /** 修改后的输入（当 decision=edit 时） */
  modifiedInput?: Record<string, unknown>;

  /** 备注 */
  note?: string;
}

// ============================================================
// HITL 管理器配置
// ============================================================

export interface HITLManagerConfig {
  /** 是否启用 HITL */
  enabled: boolean;

  /** 默认中断超时（毫秒），默认 1 小时 */
  defaultTimeoutMs?: number;

  /** 自动通过低风险中断 */
  autoApproveLowRisk?: boolean;

  /** 高风险节点必须人工确认 */
  requireHumanForHighRisk?: boolean;
}

// ============================================================
// HITL 管理器
// ============================================================

export class HITLManager {
  private config: HITLManagerConfig;
  private activeInterrupt: InterruptContext | null = null;
  private interruptQueue: InterruptContext[] = [];
  private resolvedInterrupts: Map<string, InterruptDecisionResult> = new Map();
  private onInterruptCallback?: (interrupt: InterruptContext) => void;

  constructor(config?: Partial<HITLManagerConfig>) {
    this.config = {
      enabled: false,
      defaultTimeoutMs: 60 * 60 * 1000, // 1小时
      autoApproveLowRisk: false,
      requireHumanForHighRisk: true,
      ...config,
    };
  }

  /**
   * 启用/禁用 HITL
   */
  setEnabled(enabled: boolean): void {
    this.config.enabled = enabled;
  }

  /**
   * 检查是否启用
   */
  isEnabled(): boolean {
    return this.config.enabled;
  }

  /**
   * 设置中断回调
   */
  setOnInterrupt(callback: (interrupt: InterruptContext) => void): void {
    this.onInterruptCallback = callback;
  }

  /**
   * 检查节点是否需要中断
   */
  shouldInterrupt(node: HITLNode | ANode): boolean {
    if (!this.config.enabled) {
      return false;
    }

    const hitlNode = node as HITLNode;
    if (!hitlNode.interruptBefore) {
      return false;
    }

    // 低风险自动通过
    if (this.config.autoApproveLowRisk && hitlNode.riskLevel === 'low') {
      return false;
    }

    return true;
  }

  /**
   * 创建中断
   */
  createInterrupt(
    node: HITLNode | ANode,
    currentState: GraphState,
    inputPreview: Record<string, unknown> = {}
  ): InterruptContext {
    const hitlNode = node as HITLNode;

    const completedNodes = Array.from(currentState.nodeResults.values()).filter(
      (r) => r.status === 'completed'
    ).length;

    const context: InterruptContext = {
      interruptId: `int_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      nodeId: node.id,
      nodeName: node.name,
      riskLevel: hitlNode.riskLevel ?? 'medium',
      label: hitlNode.interruptLabel ?? `即将执行: ${node.name}`,
      stateSummary: {
        confidence: currentState.confidence,
        tokenUsed: currentState.tokenUsed,
        completedNodes,
        totalNodes: 0, // 由调用方传入总节点数
      },
      inputPreview,
      interruptedAt: Date.now(),
      timeoutMs: this.config.defaultTimeoutMs,
    };

    this.activeInterrupt = context;
    this.interruptQueue.push(context);

    // 触发回调
    if (this.onInterruptCallback) {
      this.onInterruptCallback(context);
    }

    return context;
  }

  /**
   * 获取当前活跃的中断
   */
  getActiveInterrupt(): InterruptContext | null {
    return this.activeInterrupt;
  }

  /**
   * 检查是否有活跃中断
   */
  hasActiveInterrupt(): boolean {
    return this.activeInterrupt !== null;
  }

  /**
   * 解决中断（人类做出决策）
   */
  resolveInterrupt(
    interruptId: string,
    decision: InterruptDecision,
    options: {
      decidedBy?: string;
      modifiedInput?: Record<string, unknown>;
      note?: string;
    } = {}
  ): InterruptDecisionResult {
    const result: InterruptDecisionResult = {
      decision,
      decidedAt: Date.now(),
      decidedBy: options.decidedBy,
      modifiedInput: options.modifiedInput,
      note: options.note,
    };

    this.resolvedInterrupts.set(interruptId, result);

    // 如果是当前活跃的中断，清除它
    if (this.activeInterrupt?.interruptId === interruptId) {
      this.activeInterrupt = null;
    }

    return result;
  }

  /**
   * 获取中断的决策结果
   */
  getDecision(interruptId: string): InterruptDecisionResult | undefined {
    return this.resolvedInterrupts.get(interruptId);
  }

  /**
   * 等待中断解决（Promise 版本，用于异步等待）
   */
  waitForResolution(interruptId: string): Promise<InterruptDecisionResult> {
    return new Promise((resolve) => {
      // 立即检查
      const existing = this.resolvedInterrupts.get(interruptId);
      if (existing) {
        resolve(existing);
        return;
      }

      // 轮询等待
      const interval = setInterval(() => {
        const result = this.resolvedInterrupts.get(interruptId);
        if (result) {
          clearInterval(interval);
          resolve(result);
        }
      }, 100);

      // 超时处理
      const timeout = this.config.defaultTimeoutMs ?? 60 * 60 * 1000;
      setTimeout(() => {
        clearInterval(interval);
        resolve({
          decision: 'approve',
          decidedAt: Date.now(),
          note: '超时自动通过',
        });
      }, timeout);
    });
  }

  /**
   * 获取中断历史
   */
  getInterruptHistory(): {
    interrupt: InterruptContext;
    decision?: InterruptDecisionResult;
  }[] {
    return this.interruptQueue.map((interrupt) => ({
      interrupt,
      decision: this.resolvedInterrupts.get(interrupt.interruptId),
    }));
  }

  /**
   * 获取统计信息
   */
  getStats(): {
    totalInterrupts: number;
    approved: number;
    rejected: number;
    edited: number;
    pending: number;
  } {
    const resolved = Array.from(this.resolvedInterrupts.values());

    return {
      totalInterrupts: this.interruptQueue.length,
      approved: resolved.filter((r) => r.decision === 'approve').length,
      rejected: resolved.filter((r) => r.decision === 'reject').length,
      edited: resolved.filter((r) => r.decision === 'edit').length,
      pending: this.interruptQueue.length - resolved.length,
    };
  }

  /**
   * 检查中断是否超时
   */
  isInterruptExpired(interrupt: InterruptContext): boolean {
    if (!interrupt.timeoutMs) return false;
    return Date.now() - interrupt.interruptedAt > interrupt.timeoutMs;
  }

  /**
   * 清除所有中断
   */
  clearAll(): void {
    this.activeInterrupt = null;
    this.interruptQueue = [];
    this.resolvedInterrupts.clear();
  }
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 从 ArchitectureGraph 中提取所有 HITL 节点
 */
export function getHITLNodes(
  nodes: Map<NodeId, ANode>
): HITLNode[] {
  return Array.from(nodes.values()).filter(
    (node) => (node as HITLNode).interruptBefore === true
  ) as HITLNode[];
}

/**
 * 根据风险等级排序节点
 */
export function sortByRisk(nodes: HITLNode[]): HITLNode[] {
  const riskOrder = { high: 0, medium: 1, low: 2 };
  return [...nodes].sort(
    (a, b) => riskOrder[a.riskLevel ?? 'medium'] - riskOrder[b.riskLevel ?? 'medium']
  );
}

/**
 * 创建 HITL 节点工厂函数
 */
export function createHITLNode(
  baseNode: ANode,
  hitlConfig: {
    interruptBefore?: boolean;
    interruptLabel?: string;
    riskLevel?: 'low' | 'medium' | 'high';
    approvalFields?: string[];
  }
): HITLNode {
  return {
    ...baseNode,
    interruptBefore: hitlConfig.interruptBefore,
    interruptLabel: hitlConfig.interruptLabel,
    riskLevel: hitlConfig.riskLevel,
    approvalFields: hitlConfig.approvalFields,
  };
}

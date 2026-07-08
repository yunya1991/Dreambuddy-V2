/**
 * Graph <-> Reflection 双向融合桥
 * ============================================================
 *
 * 核心设计：让图结构上下文压缩模块和 6 个智能决策模块深度融合
 *
 * ┌─────────────────────────────────────────────────────┐
 * │  Graph → Reflection 融合（让决策更智能）            │
 * │  ├─ graphAwareSelfCriticism(): 用节点依赖/累计置信度增强自省│
 * │  ├─ graphAwareShouldSkipStep(): 用架构节点状态判断跳步│
 * │  └─ graphAwareRollback(): 用图历史验证判断是否回退   │
 * │                                                      │
 * │  Reflection → Graph 融合（让压缩更智能）            │
 * │  ├─ recordStepReflection(): 将自省结果写入 graph    │
 * │  ├─ reflectionDrivenCompression(): 高风险节点保留   │
 * │  └─ buildGraphSummary(): 从 graph 生成执行摘要      │
 * │                                                      │
 * │  统一入口：executeWithGraphReflection()             │
 * └─────────────────────────────────────────────────────┘
 *
 * @stability experimental
 */

import type { StepPhase, StepMetadata, SelfCriticismResult } from './reflection-gates';
import { runSelfCriticism, analyzeStepConfidence, shouldSkipStep } from './reflection-gates';

// ============================================================
// Graph-Side 数据类型（对应 compressor 的三层节点）
// ============================================================

/** A 层架构节点（步骤），被 reflection 扩展了 metadata */
export interface ArchitectureNodeRef {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'rerun';
  parentModuleId: string;
  requires?: string[];
  tokenCost: number;
  latencyMs: number;
  /** Reflection 注入：置信度 */
  confidence?: number;
  /** Reflection 注入：风险评分 */
  riskScore?: number;
  /** Reflection 注入：不确定性标签 */
  uncertaintyTags?: string[];
  /** Reflection 注入：发现的问题 */
  issuesFound?: string[];
  /** Reflection 注入：修正建议 */
  corrections?: string[];
  /** Reflection 注入：自省 gate 是否通过 */
  gatePassed?: boolean;
  /** 工具调用迭代次数 */
  toolIterations?: number;
}

/** B 层蓝图模块 */
export interface BlueprintModuleRef {
  id: string;
  name: string;
  type: 'service' | 'module';
  nodes: ArchitectureNodeRef[];
  avgConfidence: number;
  maxRisk: number;
  status: 'incomplete' | 'partial' | 'complete';
}

/** 轻量级 graph 状态（不依赖完整 graph-compressor 实例） */
export interface GraphReflectionState {
  sessionId: string;
  blueprintNodes: BlueprintModuleRef[];
  architectureNodes: Map<string, ArchitectureNodeRef>;
  executedOrder: string[];
  cumulativeConfidence: number;
  cumulativeRisk: number;
  totalNodes: number;
  completedNodes: number;
  skippedNodes: string[];
  rollbackCount: number;
  compressionSignal: {
    /** 优先保留：置信度高 / 风险高 / 包含修正 */
    highValueNodes: string[];
    /** 可压缩：置信度低 / 无问题 */
    compressibleNodes: string[];
  };
  /** Phase 2+: 动态链控制状态（用于 PLAN/EXECUTE/REFLECT 闭环） */
  dynamicChain: {
    enabled: boolean;
    iteration: number;
    lastDecision: 'CONTINUE' | 'REDO' | 'INSERT_BEFORE' | 'JUMP_TO' | 'EARLY_TERMINATE';
    lastDecisionTargetStepId?: string;
    lastDecisionReason?: string;
    planTrace: Array<{ stepId: string; decision: string; confidence: number }>;
  };
}

// ============================================================
// 创建初始状态
// ============================================================

/**
 * 创建 graph-reflection 融合状态
 * 在 S 系列开始前调用
 */
export function createGraphReflectionState(sessionId: string): GraphReflectionState {
  // 复刻 B 层蓝图 + A 层架构的结构（与 graph-compressor 保持一致）
  const blueprintTemplate: { id: string; name: string; type: 'service' | 'module'; nodes: string[] }[] = [
    { id: 'intent_engine', name: '意图识别引擎', type: 'service', nodes: [] },
    { id: 'knowledge_base', name: 'S1 知识库服务', type: 'service', nodes: [] },
    { id: 'market_data', name: 'S1 行情数据服务', type: 'service', nodes: [] },
    {
      id: 'analysis_chain',
      name: '分析链',
      type: 'module',
      nodes: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
    },
    { id: 'strategy_engine', name: '策略引擎', type: 'service', nodes: [] },
    { id: 'report_generator', name: '报告生成器', type: 'service', nodes: [] },
  ];

  const archNodes = new Map<string, ArchitectureNodeRef>();
  const blueprintNodes: BlueprintModuleRef[] = blueprintTemplate.map((bp) => ({
    id: bp.id,
    name: bp.name,
    type: bp.type,
    nodes: bp.nodes.map((nodeId) => {
      const node: ArchitectureNodeRef = {
        id: nodeId,
        name: nodeId,
        status: 'pending',
        parentModuleId: bp.id,
        tokenCost: 0,
        latencyMs: 0,
      };
      archNodes.set(nodeId, node);
      return node;
    }),
    avgConfidence: 0,
    maxRisk: 0,
    status: 'incomplete',
  }));

  return {
    sessionId,
    blueprintNodes,
    architectureNodes: archNodes,
    executedOrder: [],
    cumulativeConfidence: 0,
    cumulativeRisk: 0,
    totalNodes: archNodes.size,
    completedNodes: 0,
    skippedNodes: [],
    rollbackCount: 0,
    compressionSignal: {
      highValueNodes: [],
      compressibleNodes: [],
    },
    dynamicChain: {
      enabled: false,
      iteration: 0,
      lastDecision: 'CONTINUE',
      planTrace: [],
    },
  };
}

// ============================================================
// Graph → Reflection 融合：用 graph 增强自省判断
// ============================================================

/**
 * 图感知自省 Gate：结合 graph 节点状态 + 文本启发式判断
 *
 * 增强点：
 *  1. 如果上一步 confidence < 0.5 → 当前步骤自动降级（要求更多验证）
 *  2. 如果当前节点 requires 的节点未完成 → 标记缺失前置
 *  3. 如果同模块 avgConfidence < 0.6 → 要求补充验证
 *  4. 如果存在高风险节点（risk > 0.7）→ 额外风险检查
 */
export function graphAwareSelfCriticism(
  step: StepPhase,
  content: string,
  previousSteps: StepMetadata[],
  graphState: GraphReflectionState,
  marketDataSnapshot?: any,
): SelfCriticismResult {
  // 第一步：调用原有文本启发式
  const baseResult = runSelfCriticism(step, content, previousSteps, marketDataSnapshot);

  const extraIssues: string[] = [];
  const extraCorrections: string[] = [];
  let confidenceDeltaAdjust = 0;

  // 增强 1：上一步置信度检查（优化：更温和的降级）
  if (previousSteps.length > 0) {
    const prev = previousSteps[previousSteps.length - 1];
    if (prev.confidence < 0.45) {
      extraIssues.push(`上一步 ${prev.step} 置信度仅 ${prev.confidence.toFixed(2)}，结论不可靠`);
      extraCorrections.push('建议回到上一步补充更详细的数据支撑');
      confidenceDeltaAdjust -= 0.05; // -0.1 -> -0.05
    }
    // 风险继承（优化：更温和的风险惩罚）
    if (prev.riskScore > 0.75) {
      extraIssues.push(`${prev.step} 存在高风险信号（risk=${prev.riskScore.toFixed(2)}）`);
      extraCorrections.push('需在本步中明确风险控制措施');
      confidenceDeltaAdjust -= 0.02; // -0.05 -> -0.02
    }
  }

  // 增强 2：graph 中前置依赖检查
  const node = graphState.architectureNodes.get(step);
  if (node && node.requires) {
    for (const dep of node.requires) {
      const depNode = graphState.architectureNodes.get(dep);
      if (depNode && depNode.status === 'pending') {
        extraIssues.push(`依赖节点 ${dep} 尚未执行完毕`);
        extraCorrections.push('确保前置步骤已有完整输出');
      }
    }
  }

  // 增强 3：累计置信度趋势检查（优化：更温和的惩罚）
  if (graphState.completedNodes >= 2) {
    const avg = graphState.cumulativeConfidence;
    if (avg < 0.5) {  // 0.55 -> 0.5
      extraIssues.push(`整体链置信度偏低（${avg.toFixed(2)}），建议加强后续步骤验证`);
      confidenceDeltaAdjust -= 0.02; // -0.05 -> -0.02
    }
  }

  // 合并
  const mergedIssues = [...baseResult.issues, ...extraIssues];
  const mergedCorrections = [...baseResult.corrections, ...extraCorrections];
  const passed = mergedIssues.length <= 3; // 放宽到 3 个问题
  const confidenceDelta = baseResult.confidenceDelta + confidenceDeltaAdjust;

  return {
    passed,
    confidenceDelta,
    riskScore: baseResult.riskScore,
    issues: mergedIssues,
    corrections: mergedCorrections,
    uncertaintyTags: baseResult.uncertaintyTags,
  };
}

/**
 * 图感知自适应路径：用 graph 节点状态 + 累计置信度判断是否跳过
 *
 * 增强点：
 *  1. 如果 analysis_chain 模块 avgConfidence >= 0.85 → 跳过 S4
 *  2. 如果当前模块已无高风险节点且前置都 complete → 可跳步
 *  3. 如果执行时间过长但置信度稳定 → 提前收敛
 */
export function graphAwareShouldSkipStep(
  step: StepPhase,
  graphState: GraphReflectionState,
  stepMetadatas: StepMetadata[],
): { skipStep: boolean; reason: string } {
  const baseResult = shouldSkipStep(step, stepMetadatas);
  if (baseResult.skipStep) return baseResult;

  // 增强：graph 结构分析
  if (step === 'S4_VALIDATE' && graphState.completedNodes >= 3) {
    // 已完成 S1+S2+S3
    const s1 = graphState.architectureNodes.get('S1_RESEARCH');
    const s2 = graphState.architectureNodes.get('S2_ANALYSIS');
    const s3 = graphState.architectureNodes.get('S3_DESIGN');
    const allHighConfidence =
      s1 && s2 && s3 &&
      (s1.confidence || 0) >= 0.75 &&
      (s2.confidence || 0) >= 0.75 &&
      (s3.confidence || 0) >= 0.75;

    const lowRisk =
      (s2?.riskScore || 1) < 0.5 && (s3?.riskScore || 1) < 0.5;

    if (allHighConfidence && lowRisk) {
      return {
        skipStep: true,
        reason: `Graph 感知：S1-S3 置信度均 ≥ 0.75 且风险 < 0.5 → 跳过 S4`,
      };
    }
  }

  // 如果已执行过该步骤（回退场景）→ 不再跳过（回退后需要重新评估）
  if (graphState.executedOrder.includes(step)) {
    return { skipStep: false, reason: `节点 ${step} 已执行过，回退后不跳过` };
  }

  return { skipStep: false, reason: 'Graph 感知：正常流程继续' };
}

// ============================================================
// Reflection → Graph 融合：将自省结果写入 graph
// ============================================================

/**
 * 将步骤自省结果写入 graph 节点 metadata
 * 这让压缩算法可以：
 *   - 保留高置信度节点（推理有效）
 *   - 保留高风险节点（不可丢失）
 *   - 标记问题节点为"需验证"
 */
export function recordStepReflection(
  graphState: GraphReflectionState,
  step: StepPhase,
  metadata: StepMetadata,
  options?: { toolIterations?: number; tokenCost?: number; latencyMs?: number },
): void {
  const node = graphState.architectureNodes.get(step);
  if (!node) return;

  node.status = metadata.shouldBeSkipped ? 'skipped' : 'completed';
  node.confidence = metadata.confidence;
  node.riskScore = metadata.riskScore;
  node.uncertaintyTags = metadata.uncertaintyTags;
  node.issuesFound = metadata.issuesFound;
  node.corrections = metadata.corrections;
  node.gatePassed = metadata.gatePassed;
  if (options?.toolIterations) node.toolIterations = options.toolIterations;
  if (options?.tokenCost) node.tokenCost = options.tokenCost;
  if (options?.latencyMs) node.latencyMs = options.latencyMs;

  // 更新全局状态
  graphState.executedOrder.push(step);
  graphState.completedNodes = Array.from(graphState.architectureNodes.values())
    .filter((n) => n.status === 'completed').length;
  graphState.skippedNodes = Array.from(graphState.architectureNodes.values())
    .filter((n) => n.status === 'skipped').map((n) => n.id);

  // 累计置信度/风险
  const completed = Array.from(graphState.architectureNodes.values())
    .filter((n) => n.status === 'completed' && n.confidence !== undefined);
  if (completed.length > 0) {
    graphState.cumulativeConfidence = completed.reduce((s, n) => s + (n.confidence || 0), 0) / completed.length;
    graphState.cumulativeRisk = Math.max(...completed.map((n) => n.riskScore || 0));
  }

  // 更新 Blueprint 模块状态
  for (const bp of graphState.blueprintNodes) {
    if (bp.nodes.length === 0) continue;
    const completedInBp = bp.nodes.filter((n) => n.status === 'completed');
    const confs = bp.nodes.map((n) => n.confidence || 0).filter((c) => c > 0);
    const risks = bp.nodes.map((n) => n.riskScore || 0).filter((r) => r > 0);
    bp.avgConfidence = confs.length > 0 ? confs.reduce((s, c) => s + c, 0) / confs.length : 0;
    bp.maxRisk = risks.length > 0 ? Math.max(...risks) : 0;
    bp.status = completedInBp.length === bp.nodes.length ? 'complete' :
      completedInBp.length > 0 ? 'partial' : 'incomplete';
  }

  // 生成压缩信号
  updateCompressionSignal(graphState);
}

/**
 * 根据 reflection 结果更新压缩信号
 *
 * 规则：
 *  - highValue（保留）：confidence >= 0.7 OR risk >= 0.5 OR issuesFound.length >= 1 OR corrections.length >= 1
 *  - compressible（可压缩）：confidence < 0.5 AND risk < 0.3 AND issuesFound.length === 0
 *  - 其余：默认保留
 */
export function updateCompressionSignal(graphState: GraphReflectionState): void {
  const highValue: string[] = [];
  const compressible: string[] = [];

  graphState.architectureNodes.forEach((node, id) => {
    if (node.status !== 'completed') return;
    const conf = node.confidence || 0;
    const risk = node.riskScore || 0;
    const hasIssues = (node.issuesFound?.length || 0) > 0;
    const hasCorrections = (node.corrections?.length || 0) > 0;

    if (conf >= 0.7 || risk >= 0.5 || hasIssues || hasCorrections) {
      highValue.push(id);
    } else if (conf < 0.5 && risk < 0.3) {
      compressible.push(id);
    }
  });

  graphState.compressionSignal = {
    highValueNodes: highValue,
    compressibleNodes: compressible,
  };
}

/**
 * 标记回退：将回退后的节点重置为 rerun
 */
export function markRollback(graphState: GraphReflectionState, rollbackToStep: StepPhase): void {
  graphState.rollbackCount += 1;
  const node = graphState.architectureNodes.get(rollbackToStep);
  if (node) {
    node.status = 'rerun';
  }
  // S4 本身也重置
  const s4 = graphState.architectureNodes.get('S4_VALIDATE');
  if (s4 && s4.status === 'completed') {
    s4.status = 'rerun';
  }
}

// ============================================================
// 生成 graph 感知的质量摘要
// ============================================================

/**
 * 从 graph 状态生成结构化摘要，用于前端展示
 */
export function buildGraphSummary(
  graphState: GraphReflectionState,
): {
  totalNodes: number;
  avgConfidence: number;
  maxRisk: number;
  completedRatio: number;
  highValueCount: number;
  compressibleCount: number;
  rollbackCount: number;
  modules: { id: string; name: string; status: string; avgConfidence: number; maxRisk: number }[];
  nodeStatuses: { id: string; status: string; confidence?: number; risk?: number; issues: string[] }[];
} {
  const modules = graphState.blueprintNodes
    .filter((bp) => bp.nodes.length > 0 || bp.status !== 'incomplete')
    .map((bp) => ({
      id: bp.id,
      name: bp.name,
      status: bp.status,
      avgConfidence: bp.avgConfidence,
      maxRisk: bp.maxRisk,
    }));

  const nodeStatuses = Array.from(graphState.architectureNodes.values())
    .map((n) => ({
      id: n.id,
      status: n.status,
      confidence: n.confidence,
      risk: n.riskScore,
      issues: n.issuesFound || [],
    }));

  return {
    totalNodes: graphState.totalNodes,
    avgConfidence: graphState.cumulativeConfidence,
    maxRisk: graphState.cumulativeRisk,
    completedRatio: graphState.totalNodes > 0 ? graphState.completedNodes / graphState.totalNodes : 0,
    highValueCount: graphState.compressionSignal.highValueNodes.length,
    compressibleCount: graphState.compressionSignal.compressibleNodes.length,
    rollbackCount: graphState.rollbackCount,
    modules,
    nodeStatuses,
  };
}

// ============================================================
// 辅助：estimateTokens（用于 token 估算）
// ============================================================

export function estimateTokens(text: string): number {
  if (!text) return 0;
  // 简化：中文 1 char ≈ 1.5 tokens，英文 4 chars ≈ 1 token
  const chineseChars = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
  const rest = text.length - chineseChars;
  return Math.round(chineseChars * 1.5 + rest / 4);
}

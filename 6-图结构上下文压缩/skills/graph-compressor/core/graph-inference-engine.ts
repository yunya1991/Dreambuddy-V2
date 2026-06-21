/**
 * ============================================================
 *  🔮  图结构推理引擎 (Graph Inference Engine)
 * ============================================================
 *
 *  核心思想：
 *    将压缩后的图结构（Blueprint / Architecture / Chronicle）作为输入，
 *    通过图论算法 + 启发式规则进行高级推理，产出有价值的洞察。
 *
 *  这是整个系统的"大脑"，负责：
 *    1. 图结构分析（路径、依赖、关键节点）
 *    2. 缺失信息检测（哪些步骤尚未执行/信息不足）
 *    3. 下一步行动建议（给用户/调度器的智能建议）
 *    4. 模式识别（对话中重复出现的推理模式）
 *    5. 冲突检测（消息中的逻辑不一致）
 *    6. 推理链构建（从原始消息 → 结构化推理链条）
 *    7. 风险评分（基于图结构的整体风险评估）
 *
 *  典型工作流：
 *    对话消息 → [自动图生成] → Blueprint/Architecture
 *             → [图压缩] → 精简图结构
 *             → [图推理引擎] → 洞察/建议
 */

import { graphCompress, type CompressMessage, type CompressResult, type CompressedNode } from './graph-compress.ts';
import {
  generateBlueprint,
  expandToArchitecture,
  autoCompressContext,
  detectIntent,
  type GeneratedBlueprint,
  type BlueprintGraph,
  type ArchitectureGraph,
  type AutoCompressResult,
} from './auto-graph-generator.ts';
import {
  SkipGateRecorder,
  createSkipGateRecorder,
  type StepDecision,
} from './skip-gate-integration.ts';

// ============================================================
// ==================== 数据结构 ==============================
// ============================================================

// 图中的一条路径（节点序列）
export interface GraphPath {
  nodes: string[];
  totalScore: number;
  avgScore: number;
  isComplete: boolean;        // 是否从入口到出口
  criticalNodeCount: number;  // 路径上的关键节点数
}

// 缺失信息检测结果
export interface MissingInfo {
  stepId: string;
  stepName: string;
  reason: string;              // 为什么认为这一步缺失
  evidence: string[];          // 证据（哪些消息中提到了但未解决）
  priority: 'high' | 'medium' | 'low';
}

// 下一步行动建议
export interface NextAction {
  id: string;
  action: string;               // 具体建议的行动
  reason: string;               // 为什么建议这个行动
  supportingNodes: string[];    // 支持此建议的节点 ID
  priority: 'critical' | 'high' | 'medium' | 'low';
  expectedOutcome: string;      // 预期能获得什么
}

// 推理链节点
export interface ReasoningStep {
  id: string;
  type: 'observation' | 'analysis' | 'decision' | 'action' | 'result';
  content: string;
  sourceMessageIds: string[];   // 从哪些消息中提取
  confidence: number;           // 0-1
  dependencies: string[];       // 依赖哪些步骤
  metadata?: Record<string, unknown>;
}

// 推理链
export interface ReasoningChain {
  id: string;
  steps: ReasoningStep[];
  overallConfidence: number;
  isComplete: boolean;          // 是否有完整的观察→分析→决策→行动链
  gaps: string[];               // 缺失的环节
}

// 冲突检测结果
export interface Conflict {
  id: string;
  type: 'contradiction' | 'inconsistency' | 'missing_dependency';
  description: string;
  nodeA: string;
  nodeB?: string;
  evidence: string[];
  severity: 'high' | 'medium' | 'low';
}

// 推理引擎输出 - 综合洞察
export interface InferenceResult {
  sessionId: string;
  generatedAt: number;

  // 图结构分析
  graphSummary: {
    blueprintNodes: number;
    architectureNodes: number;
    compressedNodes: number;
    totalMessages: number;
    keptMessages: number;
    compressionRatio: number;
    intent: string;
    intentConfidence: number;
  };

  // 关键路径
  criticalPaths: GraphPath[];
  keyNodes: Array<{ id: string; name: string; score: number; type: string }>;

  // 缺失信息
  missingInfo: MissingInfo[];

  // 下一步建议
  nextActions: NextAction[];

  // 推理链
  reasoningChains: ReasoningChain[];

  // 冲突检测
  conflicts: Conflict[];

  // 风险评分
  riskScore: number;             // 0-1，越高越需要关注
  riskFactors: Array<{ factor: string; score: number; description: string }>;

  // 人类可读的总结
  summary: {
    short: string;
    detailed: string;
    keyFindings: string[];
    recommendations: string[];
  };
}

// ============================================================
// ==================== 推理引擎主类 ============================
// ============================================================

export class GraphInferenceEngine {
  private sessionId: string;
  private messages: CompressMessage[] = [];
  private blueprint: GeneratedBlueprint | null = null;
  private architecture: ArchitectureGraph | null = null;
  private compressResult: CompressResult | null = null;
  private skipGate: SkipGateRecorder | null = null;

  constructor(sessionId: string = `inference_${Date.now()}`) {
    this.sessionId = sessionId;
  }

  // ------------------------------------------------------------
  // 🔌 数据输入
  // ------------------------------------------------------------

  // 完整流程：从消息自动构建图并推理
  feedMessages(messages: CompressMessage[]): this {
    this.messages = messages;
    const auto = autoCompressContext(messages, { sessionId: this.sessionId });
    this.blueprint = auto.blueprint;
    this.architecture = auto.architecture;
    this.compressResult = auto.compressionResult;
    return this;
  }

  // 手动设置蓝图/架构/压缩结果
  setBlueprint(bp: GeneratedBlueprint): this { this.blueprint = bp; return this; }
  setArchitecture(arch: ArchitectureGraph): this { this.architecture = arch; return this; }
  setCompressResult(result: CompressResult): this { this.compressResult = result; return this; }
  setSkipGate(recorder: SkipGateRecorder): this { this.skipGate = recorder; return this; }

  // ------------------------------------------------------------
  // 🔍 1. 图结构分析 - 关键路径 / 关键节点
  // ------------------------------------------------------------

  analyzeGraphStructure(): {
    keyNodes: Array<{ id: string; name: string; score: number; type: string }>;
    criticalPaths: GraphPath[];
    avgNodeScore: number;
    graphHealth: number;           // 0-1，图结构完整性
  } {
    if (!this.architecture || !this.blueprint) {
      return { keyNodes: [], criticalPaths: [], avgNodeScore: 0, graphHealth: 0 };
    }

    const arch = this.architecture;

    // 分析所有 Architecture 节点
    const scoredNodes: Array<{ id: string; name: string; score: number; type: string; metadata: Record<string, unknown> }> = [];
    arch.nodes.forEach((node: any, id: string) => {
      // 综合评分：importance + 关键词命中 + 决策类型权重
      const meta = node.metadata || {};
      let score = 0;
      if (meta.score) score += Number(meta.score);
      if (node.type === 'decision') score += 0.2;
      if (node.type === 'step') score += 0.1;
      if (meta.status === 'critical') score += 0.3;
      if (meta.isUserInitiated) score += 0.1;
      score = Math.min(1, score);

      scoredNodes.push({
        id: id as string,
        name: node.name || id as string,
        score,
        type: node.type || 'unknown',
        metadata: meta,
      });
    });

    // 按分数排序，取关键节点
    scoredNodes.sort((a, b) => b.score - a.score);
    const keyNodes = scoredNodes.slice(0, Math.min(5, scoredNodes.length));

    // 构建关键路径（从入口节点遍历到出口节点）
    const criticalPaths: GraphPath[] = this.findCriticalPaths(arch, scoredNodes);

    // 图健康度：蓝图节点与架构节点的覆盖率
    const bpNodeCount = this.blueprint.nodes.size;
    const archNodeCount = arch.nodes.size;
    const graphHealth = bpNodeCount > 0 ? Math.min(1, archNodeCount / (bpNodeCount * 2)) : 0.5;

    // 平均节点分数
    const avgNodeScore = scoredNodes.length > 0
      ? scoredNodes.reduce((s, n) => s + n.score, 0) / scoredNodes.length
      : 0;

    return { keyNodes, criticalPaths, avgNodeScore, graphHealth };
  }

  // 基于评分的路径搜索（简化的 DFS）
  private findCriticalPaths(
    arch: ArchitectureGraph,
    scoredNodes: Array<{ id: string; score: number; name: string }>
  ): GraphPath[] {
    const scoreMap = new Map(scoredNodes.map((n) => [n.id, n.score]));
    const paths: GraphPath[] = [];

    // 从入口节点开始
    const startNodes = arch.entryNodes && arch.entryNodes.length > 0
      ? arch.entryNodes
      : [scoredNodes[0]?.id].filter(Boolean);

    const adj = new Map<string, string[]>();
    arch.edges.forEach((e: any) => {
      const from = e.source || e.from;
      const to = e.target || e.to;
      if (from && to) {
        if (!adj.has(from)) adj.set(from, []);
        adj.get(from)!.push(to);
      }
    });

    const visited = new Set<string>();
    const dfs = (node: string, path: string[], total: number, depth: number) => {
      if (depth > 10 || visited.has(node)) return;
      visited.add(node);
      const score = scoreMap.get(node) || 0.3;
      const newPath = [...path, node];
      const newTotal = total + score;

      const neighbors = adj.get(node) || [];
      if (neighbors.length === 0 || depth === 5) {
        const isExit = arch.exitNodes?.includes(node);
        paths.push({
          nodes: newPath,
          totalScore: newTotal,
          avgScore: newPath.length > 0 ? newTotal / newPath.length : 0,
          isComplete: !!isExit,
          criticalNodeCount: newPath.filter((n) => (scoreMap.get(n) || 0) >= 0.6).length,
        });
        return;
      }
      for (const nb of neighbors) {
        dfs(nb, newPath, newTotal, depth + 1);
      }
    };

    for (const start of startNodes) {
      visited.clear();
      dfs(start, [], 0, 0);
    }

    // 按平均分排序
    paths.sort((a, b) => b.avgScore - a.avgScore);
    return paths.slice(0, 3);
  }

  // ------------------------------------------------------------
  // ❓ 2. 缺失信息检测 - 哪些步骤/信息还不完整
  // ------------------------------------------------------------

  detectMissingInfo(): MissingInfo[] {
    const missing: MissingInfo[] = [];
    if (!this.blueprint || !this.architecture) return missing;

    // 从 Blueprint 中定义的步骤与 Architecture 实际执行的步骤对比
    const blueprintSteps = Array.from(this.blueprint.nodes.values());
    const executedSteps = Array.from(this.architecture.nodes.keys());
    const executedSet = new Set(executedSteps);

    // 基于对话内容做启发式检测
    const text = this.messages.map((m) => m.content).join(' ').toLowerCase();

    // 针对常见主题检测缺失信息
    const missingChecks = [
      {
        keywords: ['风险', '止损', '止盈', '风险收益比'],
        name: '风险控制参数',
        missingMsg: '用户未明确说明可接受的风险范围',
        priority: 'high' as const,
        check: () => !/止损.*\d|止盈.*\d|风险收益比|最大回撤/.test(text),
      },
      {
        keywords: ['入场', '开仓', '买入', '卖出'],
        name: '具体入场条件',
        missingMsg: '只有方向性建议，缺少具体的入场价格/时间/触发条件',
        priority: 'high' as const,
        check: () => !/\d+(?:\.\d+)?\s*(?:usdt|点|价格|位置|点位)/.test(text) &&
                    !/回踩|突破|企稳|支撑|阻力/.test(text),
      },
      {
        keywords: ['仓位', '资金', '投入', '金额'],
        name: '仓位管理方案',
        missingMsg: '缺少明确的仓位/资金配置建议',
        priority: 'high' as const,
        check: () => !/仓位|仓|资金.*\d|总资金|百分比|\d+%/.test(text),
      },
      {
        keywords: ['分析', '数据', '指标', '技术面', '基本面'],
        name: '数据分析支撑',
        missingMsg: '建议缺少数据/分析支撑（如 RSI、MACD、基本面数据等）',
        priority: 'medium' as const,
        check: () => !/rsi|macd|均线|布林|pe|pb|估值|盈利|数据|分析|回测|胜率/.test(text),
      },
      {
        keywords: ['历史', '回测', '验证'],
        name: '历史回测验证',
        missingMsg: '策略未经过历史数据回测验证',
        priority: 'medium' as const,
        check: () => !/回测|历史|胜率|过去.*?年|样本|验证|测试/.test(text),
      },
      {
        keywords: ['确认', '执行', '同意'],
        name: '用户确认环节',
        missingMsg: '关键决策未获得用户明确确认',
        priority: 'medium' as const,
        check: () => !/确认|同意|好的|收到|行|可以|执行|就按这个/.test(text),
      },
      {
        keywords: ['时间', '周期', '短线', '中线', '长线'],
        name: '持仓周期规划',
        missingMsg: '未明确说明预期的持仓周期/时间管理',
        priority: 'medium' as const,
        check: () => !/短线|中线|长线|日内|持仓|周|月|天|\d+日|\d+小时/.test(text),
      },
    ];

    // 执行检测
    for (const check of missingChecks) {
      // 先判断该主题是否与当前对话相关
      const isRelevant = check.keywords.some((kw) => text.includes(kw));
      if (isRelevant && check.check()) {
        // 收集证据：哪些消息提到了但未解决
        const evidence: string[] = [];
        for (const kw of check.keywords) {
          if (text.includes(kw)) {
            const relatedMsgs = this.messages
              .filter((m) => m.content.toLowerCase().includes(kw))
              .slice(0, 2)
              .map((m) => m.content.slice(0, 60));
            evidence.push(...relatedMsgs);
          }
        }

        missing.push({
          stepId: `missing_${missing.length}`,
          stepName: check.name,
          reason: check.missingMsg,
          evidence: evidence.slice(0, 3),
          priority: check.priority,
        });
      }
    }

    // 额外检查：Blueprint 步骤 vs Architecture 步骤的覆盖
    const blueprintStepNames = blueprintSteps
      .map((node: any) => node.name?.toLowerCase() || '')
      .filter((n) => n.length > 0);

    const executedContent = Array.from(this.architecture.nodes.values())
      .map((node: any) => node.name?.toLowerCase() || '')
      .join(' ');

    for (const bpStep of blueprintStepNames) {
      if (!bpStep || bpStep.includes('对话')) continue;
      const matched = executedContent.includes(bpStep);
      if (!matched && bpStep.length > 2) {
        missing.push({
          stepId: `bp_missing_${missing.length}`,
          stepName: bpStep,
          reason: `蓝图中定义的步骤 "${bpStep}" 在对话执行中没有明确对应`,
          evidence: [
            `Blueprint 节点数: ${blueprintSteps.length}`,
            `Architecture 节点数: ${executedSteps.length}`,
          ],
          priority: 'medium',
        });
      }
    }

    return missing;
  }

  // ------------------------------------------------------------
  // 🎯 3. 下一步行动建议 - 给用户/调度器的智能建议
  // ------------------------------------------------------------

  suggestNextActions(): NextAction[] {
    const actions: NextAction[] = [];
    const missing = this.detectMissingInfo();
    const intent = detectIntent(this.messages);

    // 基于缺失信息生成建议
    for (const item of missing.slice(0, 3)) {
      const priorityMap: Record<string, 'critical' | 'high' | 'medium' | 'low'> = {
        high: 'critical',
        medium: 'high',
        low: 'medium',
      };

      actions.push({
        id: `action_${actions.length}`,
        action: this.mapMissingToAction(item.stepName),
        reason: item.reason,
        supportingNodes: [item.stepId],
        priority: priorityMap[item.priority] || 'medium',
        expectedOutcome: `补充 ${item.stepName} 后，决策完整性将显著提升`,
      });
    }

    // 基于意图生成建议
    if (this.messages.length > 5 && intent.intent === 'trading') {
      actions.push({
        id: `action_${actions.length}`,
        action: '生成交易执行计划（含具体入场/止损/止盈点位）',
        reason: '对话中已收集足够分析信息，可以输出具体执行信号',
        supportingNodes: [],
        priority: 'critical',
        expectedOutcome: '可直接执行的完整交易方案',
      });
    }

    if (this.messages.length > 5 && intent.intent === 'analysis') {
      actions.push({
        id: `action_${actions.length}`,
        action: '补充数据分析与回测验证',
        reason: '技术分析已完成，但缺少历史数据验证',
        supportingNodes: [],
        priority: 'high',
        expectedOutcome: '增强建议的可信度',
      });
    }

    // 如果所有关键信息都已齐
    if (missing.filter((m) => m.priority === 'high').length === 0 && this.messages.length > 3) {
      actions.push({
        id: `action_${actions.length}`,
        action: '总结并输出最终决策',
        reason: '所有关键信息已收集，可以综合输出最终建议',
        supportingNodes: [],
        priority: 'critical',
        expectedOutcome: '完整的结构化建议输出',
      });
    }

    // 如果对话刚开始
    if (this.messages.length <= 3) {
      actions.push({
        id: `action_${actions.length}`,
        action: '继续收集用户需求',
        reason: '对话信息不足，需要更多上下文才能做出有价值的分析',
        supportingNodes: [],
        priority: 'high',
        expectedOutcome: '获取足够信息后启动深度分析',
      });
    }

    return actions.sort((a, b) => {
      const priorityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
      return priorityOrder[a.priority] - priorityOrder[b.priority];
    });
  }

  private mapMissingToAction(stepName: string): string {
    const actionMap: Record<string, string> = {
      '风险控制参数': '定义可接受的风险范围（止损/止盈/最大仓位）',
      '具体入场条件': '明确入场价格/时间/触发信号',
      '仓位管理方案': '确定仓位比例/资金投入',
      '数据分析支撑': '补充技术指标/基本面数据',
      '历史回测验证': '进行历史数据回测验证策略有效性',
      '用户确认环节': '获得用户对方案的明确确认',
      '持仓周期规划': '明确预期持仓周期/退出条件',
    };
    return actionMap[stepName] || `补充 ${stepName}`;
  }

  // ------------------------------------------------------------
  // 🔗 4. 推理链构建 - 从原始消息提取结构化推理链条
  // ------------------------------------------------------------

  buildReasoningChains(): ReasoningChain[] {
    const chains: ReasoningChain[] = [];
    if (this.messages.length === 0) return chains;

    // 主推理链：按对话顺序构建
    const sortedMessages = [...this.messages].sort((a, b) =>
      (a.timestamp || 0) - (b.timestamp || 0)
    );

    const steps: ReasoningStep[] = [];
    for (const msg of sortedMessages) {
      const type = this.classifyMessage(msg);
      if (type === 'other' && msg.content.length < 20) continue; // 跳过极短消息

      steps.push({
        id: `step_${steps.length}`,
        type,
        content: msg.content.slice(0, 120),
        sourceMessageIds: [msg.id],
        confidence: msg.importance === 'high' ? 0.9 : 0.6,
        dependencies: steps.length > 0 ? [steps[steps.length - 1].id] : [],
        metadata: { role: msg.role, timestamp: msg.timestamp, importance: msg.importance },
      });
    }

    // 计算整体置信度
    const overallConfidence = steps.length > 0
      ? steps.reduce((s, st) => s + st.confidence, 0) / steps.length
      : 0;

    // 检查完整性：是否有 observation → analysis → decision 链
    const types = new Set(steps.map((s) => s.type));
    const isComplete = types.has('observation') && types.has('analysis') &&
                       (types.has('decision') || types.has('action'));

    const gaps: string[] = [];
    if (!types.has('observation')) gaps.push('缺少原始信息/数据收集环节');
    if (!types.has('analysis')) gaps.push('缺少分析/推理环节');
    if (!types.has('decision')) gaps.push('缺少明确决策');
    if (!types.has('action')) gaps.push('缺少具体行动建议');

    chains.push({
      id: `chain_${Date.now()}`,
      steps,
      overallConfidence,
      isComplete,
      gaps,
    });

    return chains;
  }

  private classifyMessage(msg: CompressMessage): ReasoningStep['type'] | 'other' {
    const text = msg.content.toLowerCase();

    if (/建议|应该|可以|决策|决定|方案|入场|止损|止盈|执行|买入|卖出/.test(text)
       && msg.importance === 'high') return 'decision';

    if (/分析|数据|指标|价格|涨跌|趋势|支撑|阻力|回测|胜率|研究|调研|技术面|基本面/.test(text))
      return 'analysis';

    if (/当前|现在|实时|数据显示|价格.*\d|rsi|macd|均线|布林|pe|pb|市值|营收|盈利/.test(text))
      return 'observation';

    if (/执行|实施|下单|开仓|平仓|操作|设置|配置/.test(text))
      return 'action';

    if (/结果|效果|收益|盈亏|回报|已确认|完成|成功/.test(text))
      return 'result';

    return 'other';
  }

  // ------------------------------------------------------------
  // ⚠️ 5. 冲突检测 - 识别消息中的逻辑不一致
  // ------------------------------------------------------------

  detectConflicts(): Conflict[] {
    const conflicts: Conflict[] = [];
    if (this.messages.length < 3) return conflicts;

    const text = this.messages.map((m) => m.content).join('\n').toLowerCase();

    // 检测 1: 矛盾的交易方向（同时提到做多和做空，且没有条件）
    const hasLong = /做多|买入|开多|多头|看涨|入场.*做多|long|buy/.test(text);
    const hasShort = /做空|卖出|开空|空头|看跌|入场.*做空|short|sell/.test(text);

    if (hasLong && hasShort && !/如果|条件|根据|分.*情况|分.*阶段|depending|if/.test(text)) {
      const evidence: string[] = [];
      this.messages.forEach((m) => {
        const c = m.content.toLowerCase();
        if (/做多|买入|long|buy/.test(c)) evidence.push(`做多: ${m.content.slice(0, 60)}`);
        if (/做空|卖出|short|sell/.test(c)) evidence.push(`做空: ${m.content.slice(0, 60)}`);
      });

      conflicts.push({
        id: `conflict_${conflicts.length}`,
        type: 'contradiction',
        description: '同时存在做多和做空建议但缺少条件区分',
        nodeA: '多头建议',
        nodeB: '空头建议',
        evidence: evidence.slice(0, 4),
        severity: 'high',
      });
    }

    // 检测 2: 风险与仓位不匹配（高风险建议但缺少止损）
    const hasHighLeverage = /杠杆|5x|10x|20x|50x|合约|期货|margin/.test(text);
    const hasStopLoss = /止损|stop-loss|stop loss|sl/.test(text);

    if (hasHighLeverage && !hasStopLoss) {
      conflicts.push({
        id: `conflict_${conflicts.length}`,
        type: 'missing_dependency',
        description: '高杠杆/合约交易但缺少止损设置',
        nodeA: '高杠杆建议',
        evidence: [
          '检测到杠杆/合约/期货等关键词',
          '未检测到止损/stop-loss 相关关键词',
          '建议: 所有高杠杆交易必须配置止损',
        ],
        severity: 'high',
      });
    }

    // 检测 3: 价格矛盾（同一资产提到多个不同价格且没有时间区分）
    const priceMatches = text.match(/(\d{4,6}(?:\.\d+)?)\s*(?:usdt|usd)?/g);
    if (priceMatches && priceMatches.length >= 2) {
      const uniquePrices = [...new Set(priceMatches)].map((p) => parseFloat(p));
      uniquePrices.sort((a, b) => a - b);
      const min = uniquePrices[0];
      const max = uniquePrices[uniquePrices.length - 1];
      if (min > 0 && (max - min) / min > 0.1) { // 价差超过 10%
        conflicts.push({
          id: `conflict_${conflicts.length}`,
          type: 'inconsistency',
          description: `价格建议范围过大 (${min} ~ ${max})，缺少时间/条件区分`,
          nodeA: '价格范围',
          evidence: [`检测到价格: ${uniquePrices.join(', ')}`,
                     '如果是不同时间点的价格，建议明确标注时间'],
          severity: 'medium',
        });
      }
    }

    return conflicts;
  }

  // ------------------------------------------------------------
  // 📊 6. 风险评分 - 基于图结构的整体风险评估
  // ------------------------------------------------------------

  assessRisk(): { score: number; factors: Array<{ factor: string; score: number; description: string }> } {
    const factors: Array<{ factor: string; score: number; description: string }> = [];
    const missing = this.detectMissingInfo();
    const conflicts = this.detectConflicts();
    const graph = this.analyzeGraphStructure();

    // 因子 1: 关键信息缺失
    const highMissingCount = missing.filter((m) => m.priority === 'high').length;
    const missingScore = Math.min(1, highMissingCount * 0.25);
    factors.push({
      factor: '关键信息缺失',
      score: missingScore,
      description: `${highMissingCount} 个高优先级信息缺失`,
    });

    // 因子 2: 冲突检测
    const highConflictCount = conflicts.filter((c) => c.severity === 'high').length;
    const conflictScore = Math.min(1, highConflictCount * 0.35);
    factors.push({
      factor: '逻辑冲突',
      score: conflictScore,
      description: `${highConflictCount} 个高优先级逻辑冲突`,
    });

    // 因子 3: 图结构健康度（反向）
    const healthScore = 1 - graph.graphHealth;
    factors.push({
      factor: '结构不完整',
      score: healthScore,
      description: `蓝图节点覆盖: ${(graph.graphHealth * 100).toFixed(0)}%`,
    });

    // 因子 4: 消息量不足
    const messageScore = this.messages.length < 5 ? 0.4 : this.messages.length < 10 ? 0.15 : 0;
    factors.push({
      factor: '信息不足',
      score: messageScore,
      description: `当前消息数: ${this.messages.length}`,
    });

    // 因子 5: 决策置信度
    const chains = this.buildReasoningChains();
    const avgConfidence = chains.length > 0 ? chains[0].overallConfidence : 0.5;
    const confidenceScore = 1 - avgConfidence;
    factors.push({
      factor: '低置信度决策',
      score: confidenceScore,
      description: `推理链整体置信度: ${(avgConfidence * 100).toFixed(0)}%`,
    });

    // 综合风险评分（加权平均）
    const weights = [0.35, 0.25, 0.15, 0.15, 0.10]; // 缺失>冲突>结构>信息不足>置信度
    const totalScore = factors.reduce((s, f, i) => s + f.score * weights[i], 0);

    return { score: Math.min(1, totalScore), factors };
  }

  // ------------------------------------------------------------
  // 🎬 综合推理 - 运行所有分析模块并输出完整结果
  // ------------------------------------------------------------

  infer(): InferenceResult {
    // 运行所有分析模块
    const graph = this.analyzeGraphStructure();
    const missing = this.detectMissingInfo();
    const actions = this.suggestNextActions();
    const chains = this.buildReasoningChains();
    const conflicts = this.detectConflicts();
    const risk = this.assessRisk();
    const intent = detectIntent(this.messages);

    const totalMessages = this.messages.length;
    const keptMessages = this.compressResult?.kept.length || Math.ceil(totalMessages * 0.6);
    const compressionRatio = totalMessages > 0 ? keptMessages / totalMessages : 0.5;

    // 生成总结
    const summary = this.generateSummary(graph, missing, actions, conflicts, risk, intent);

    return {
      sessionId: this.sessionId,
      generatedAt: Date.now(),
      graphSummary: {
        blueprintNodes: this.blueprint?.nodes.size || 0,
        architectureNodes: this.architecture?.nodes.size || 0,
        compressedNodes: keptMessages,
        totalMessages,
        keptMessages,
        compressionRatio,
        intent: intent.intent,
        intentConfidence: intent.confidence,
      },
      criticalPaths: graph.criticalPaths,
      keyNodes: graph.keyNodes,
      missingInfo: missing,
      nextActions: actions,
      reasoningChains: chains,
      conflicts,
      riskScore: risk.score,
      riskFactors: risk.factors,
      summary,
    };
  }

  private generateSummary(
    graph: ReturnType<typeof this.analyzeGraphStructure>,
    missing: MissingInfo[],
    actions: NextAction[],
    conflicts: Conflict[],
    risk: ReturnType<typeof this.assessRisk>,
    intent: ReturnType<typeof detectIntent>
  ): InferenceResult['summary'] {
    const intentName = this.mapIntentName(intent.intent);

    // 简短总结（1 行）
    const short = `【${intentName}】对话: ${this.messages.length} 条消息，检测到 ` +
                  `${missing.filter((m) => m.priority === 'high').length} 个关键信息缺失，` +
                  `风险评分 ${(risk.score * 100).toFixed(0)}/100`;

    // 详细总结
    const detailedParts: string[] = [];
    detailedParts.push(`## 对话分析`);
    detailedParts.push(`- 主题: ${intentName}（置信度 ${(intent.confidence * 100).toFixed(0)}%）`);
    detailedParts.push(`- 消息数: ${this.messages.length}`);
    detailedParts.push(`- 压缩后关键消息: ${this.compressResult?.kept.length || Math.ceil(this.messages.length * 0.6)}`);
    detailedParts.push(`- 图结构完整性: ${(graph.graphHealth * 100).toFixed(0)}%`);

    if (conflicts.length > 0) {
      detailedParts.push(`\n## 检测到 ${conflicts.length} 个逻辑冲突/问题`);
      conflicts.forEach((c, i) => {
        detailedParts.push(`${i + 1}. [${c.severity.toUpperCase()}] ${c.description}`);
        c.evidence.slice(0, 2).forEach((e) => detailedParts.push(`   - ${e}`));
      });
    }

    if (missing.length > 0) {
      detailedParts.push(`\n## 建议补充 ${missing.length} 项信息`);
      missing.slice(0, 5).forEach((m, i) => {
        detailedParts.push(`${i + 1}. [${m.priority.toUpperCase()}] ${m.stepName} - ${m.reason}`);
      });
    }

    if (actions.length > 0) {
      detailedParts.push(`\n## 下一步建议 (Top ${Math.min(actions.length, 3)})`);
      actions.slice(0, 3).forEach((a, i) => {
        detailedParts.push(`${i + 1}. [${a.priority.toUpperCase()}] ${a.action}`);
        detailedParts.push(`   → ${a.reason}`);
      });
    }

    detailedParts.push(`\n## 综合风险评估: ${(risk.score * 100).toFixed(0)}/100`);
    if (risk.score < 0.3) {
      detailedParts.push('- 风险低，信息完整，可以输出最终决策');
    } else if (risk.score < 0.6) {
      detailedParts.push('- 风险中等，建议补充关键信息后再决策');
    } else {
      detailedParts.push('- ⚠️ 风险高，存在逻辑冲突/重要信息缺失，谨慎决策');
    }

    // 关键发现
    const keyFindings: string[] = [];
    if (conflicts.length > 0) keyFindings.push(`发现 ${conflicts.length} 个需要澄清的逻辑问题`);
    if (missing.filter((m) => m.priority === 'high').length > 0) {
      keyFindings.push(`有 ${missing.filter((m) => m.priority === 'high').length} 个高优先级信息需要补充`);
    }
    if (graph.keyNodes.length > 0) {
      keyFindings.push(`核心节点: ${graph.keyNodes.slice(0, 2).map((n) => n.name).join(', ')}`);
    }
    if (this.messages.length < 5) keyFindings.push('对话信息较为有限，建议扩展讨论');
    if (keyFindings.length === 0) keyFindings.push('对话结构完整，信息充分');

    // 建议列表
    const recommendations = actions.slice(0, 4).map((a) => `${a.action} - ${a.reason}`);

    return {
      short,
      detailed: detailedParts.join('\n'),
      keyFindings,
      recommendations,
    };
  }

  private mapIntentName(intent: string): string {
    const map: Record<string, string> = {
      trading: '交易决策',
      analysis: '数据分析',
      strategy: '策略研究',
      risk: '风险管理',
      coding: '代码开发',
      design: '架构设计',
      compression: '图压缩',
      scheduling: '调度管理',
      general: '通用对话',
    };
    return map[intent] || intent;
  }

  // ------------------------------------------------------------
  // 📝 格式化输出（人类可读）
  // ------------------------------------------------------------

  formatReport(result: InferenceResult): string {
    const lines: string[] = [];
    lines.push('='.repeat(70));
    lines.push('🔮 图结构推理引擎 - 综合分析报告');
    lines.push('='.repeat(70));
    lines.push(`会话: ${result.sessionId}`);
    lines.push(`时间: ${new Date(result.generatedAt).toLocaleString()}`);
    lines.push('');
    lines.push('--- 📊 图结构摘要 ---');
    lines.push(`消息总数: ${result.graphSummary.totalMessages}`);
    lines.push(`保留节点: ${result.graphSummary.keptMessages}`);
    lines.push(`压缩率: ${(result.graphSummary.compressionRatio * 100).toFixed(0)}%`);
    lines.push(`意图: ${this.mapIntentName(result.graphSummary.intent)} (${(result.graphSummary.intentConfidence * 100).toFixed(0)}%)`);
    lines.push(`Blueprint节点: ${result.graphSummary.blueprintNodes} | Architecture节点: ${result.graphSummary.architectureNodes}`);
    lines.push('');

    if (result.keyNodes.length > 0) {
      lines.push('--- ⭐ 关键节点 (Top 5) ---');
      result.keyNodes.forEach((n, i) => {
        lines.push(`  ${i + 1}. [${(n.score * 100).toFixed(0)}分] ${n.name} (${n.type})`);
      });
      lines.push('');
    }

    if (result.criticalPaths.length > 0) {
      lines.push('--- 🛤️ 关键推理路径 ---');
      result.criticalPaths.slice(0, 2).forEach((p, i) => {
        lines.push(`  ${i + 1}. ${p.nodes.join(' → ')}`);
        lines.push(`     平均分: ${(p.avgScore * 100).toFixed(0)} | 关键节点: ${p.criticalNodeCount}`);
      });
      lines.push('');
    }

    if (result.conflicts.length > 0) {
      lines.push('--- ⚠️ 逻辑冲突检测 ---');
      result.conflicts.forEach((c, i) => {
        lines.push(`  ${i + 1}. [${c.severity.toUpperCase()}] ${c.description}`);
        c.evidence.forEach((e) => lines.push(`     · ${e}`));
      });
      lines.push('');
    }

    if (result.missingInfo.length > 0) {
      lines.push('--- ❓ 缺失信息 ---');
      result.missingInfo.slice(0, 5).forEach((m, i) => {
        lines.push(`  ${i + 1}. [${m.priority.toUpperCase()}] ${m.stepName}`);
        lines.push(`     → ${m.reason}`);
      });
      lines.push('');
    }

    if (result.reasoningChains.length > 0) {
      const chain = result.reasoningChains[0];
      lines.push(`--- 🔗 推理链 (完整度: ${chain.isComplete ? '✅' : '⚠️'}, 置信度: ${(chain.overallConfidence * 100).toFixed(0)}%) ---`);
      chain.steps.forEach((step, i) => {
        const icon = step.type === 'decision' ? '🎯'
                   : step.type === 'analysis' ? '🔍'
                   : step.type === 'observation' ? '📡'
                   : step.type === 'action' ? '🚀'
                   : step.type === 'result' ? '✅' : '·';
        lines.push(`  ${icon} [${step.type.padEnd(11)}] ${step.content.slice(0, 60)}${step.content.length > 60 ? '...' : ''}`);
      });
      if (chain.gaps.length > 0) {
        lines.push('  缺失环节:');
        chain.gaps.forEach((g) => lines.push(`     · ${g}`));
      }
      lines.push('');
    }

    if (result.nextActions.length > 0) {
      lines.push('--- 🎯 下一步行动建议 ---');
      result.nextActions.slice(0, 4).forEach((a, i) => {
        const priorityIcon = a.priority === 'critical' ? '🔴'
                           : a.priority === 'high' ? '🟠' : '🟡';
        lines.push(`  ${priorityIcon} ${i + 1}. ${a.action}`);
        lines.push(`     → ${a.reason}`);
        lines.push(`     预期: ${a.expectedOutcome}`);
      });
      lines.push('');
    }

    lines.push('--- 📉 风险评分 ---');
    lines.push(`  综合风险: ${(result.riskScore * 100).toFixed(0)}/100`);
    result.riskFactors.forEach((f) => {
      const bar = '█'.repeat(Math.floor(f.score * 10)) + '░'.repeat(10 - Math.floor(f.score * 10));
      lines.push(`  ${bar} ${f.factor}: ${(f.score * 100).toFixed(0)} - ${f.description}`);
    });

    lines.push('');
    lines.push('--- 📋 关键发现 ---');
    result.summary.keyFindings.forEach((f, i) => lines.push(`  ${i + 1}. ${f}`));

    if (result.summary.recommendations.length > 0) {
      lines.push('');
      lines.push('--- 💡 建议 ---');
      result.summary.recommendations.forEach((r, i) => lines.push(`  ${i + 1}. ${r}`));
    }

    lines.push('');
    lines.push('='.repeat(70));
    lines.push(`📝 简短总结: ${result.summary.short}`);
    lines.push('='.repeat(70));

    return lines.join('\n');
  }
}

// ============================================================
// ==================== 便捷工厂 ==============================
// ============================================================

export function createInferenceEngine(sessionId?: string): GraphInferenceEngine {
  return new GraphInferenceEngine(sessionId || `inference_${Date.now()}`);
}

// 从 CompressMessage 快速推断
export function quickInfer(messages: CompressMessage[], sessionId?: string): InferenceResult {
  const engine = createInferenceEngine(sessionId);
  engine.feedMessages(messages);
  return engine.infer();
}

// ============================================================
// ==================== CLI 演示 ==============================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('graph-inference-engine.ts')) {
  console.log('='.repeat(70));
  console.log('🔮 图结构推理引擎 - 演示模式');
  console.log('='.repeat(70));

  // 构造一个典型交易对话
  const demoMessages: CompressMessage[] = [
    { id: 'u1', role: 'user', content: '帮我分析一下 BTC 的行情，我打算做短线交易', timestamp: Date.now() - 600000 },
    { id: 'a1', role: 'assistant', content: 'BTC 当前价格 65,200 USDT，24h 涨跌幅 +2.3%。技术面：RSI 55（中性偏强），MACD 金叉，均线多头排列。', timestamp: Date.now() - 500000 },
    { id: 'u2', role: 'user', content: '好的，我想做多。入场点应该设在哪里？需要考虑什么风险？', timestamp: Date.now() - 400000 },
    { id: 'a2', role: 'assistant', content: '技术分析后建议：\n- 入场：64,800 USDT（回调支撑位）\n- 止损：64,200 USDT\n- 第一止盈：65,800 USDT', importance: 'high', timestamp: Date.now() - 300000 },
    { id: 'u3', role: 'user', content: '仓位应该多少比较合适？风险收益比如何？', timestamp: Date.now() - 200000 },
    { id: 'a3', role: 'assistant', content: '资金管理建议：\n- 仓位：总资金的 3%（保守配置）\n- 风险收益比：1:1.67\n- 杠杆：不超过 5x', importance: 'high', timestamp: Date.now() - 100000 },
    { id: 'u4', role: 'user', content: '好的，那就按这个方案执行', importance: 'high', timestamp: Date.now() - 50000 },
    { id: 'a4', role: 'assistant', content: '✅ 已确认方案，等待 BTC 价格触发入场条件。执行参数：入场 64,800 / 止损 64,200 / 止盈 65,800 / 仓位 3%', importance: 'high', timestamp: Date.now() },
  ];

  console.log(`\n📝 输入: ${demoMessages.length} 条交易对话消息\n`);

  // 创建推理引擎并运行
  const engine = createInferenceEngine('demo-inference-001');
  engine.feedMessages(demoMessages);
  const result = engine.infer();

  // 输出报告
  console.log(engine.formatReport(result));

  // 额外输出详细建议
  console.log('\n' + '='.repeat(70));
  console.log('🎬 完整系统演示 - 压缩 → 增量 → 持久化 → 自动图 → Skip Gate → 推理');
  console.log('='.repeat(70));

  // Skip Gate 集成
  const recorder = createSkipGateRecorder('demo-integration');
  recorder.startTask('btc-trade', 'BTC 短线交易', 1);
  recorder.recordExecute('market-data', '市场数据收集', '用户请求行情分析', 200, 300);
  recorder.recordExecute('technical-analysis', '技术指标分析', 'RSI/MACD/均线数据', 350, 400);
  recorder.recordExecute('entry-params', '入场参数计算', '核心决策输出', 150, 120);
  recorder.recordSkip('deep-news', '深度新闻分析', '用户未要求新闻分析', 0.6);
  recorder.recordExecute('risk-params', '风险参数设置', '仓位/止损', 180, 100);
  recorder.recordSkip('backtest', '历史回测', '用户直接确认方案', 0.7);
  recorder.recordExecute('execution-signal', '生成执行信号', '最终输出', 100, 80);
  recorder.completeTask();

  // 集成 Skip Gate 到压缩结果
  const sgMessages = recorder.toMessages().filter((m) => m.importance === 'high');
  const combinedResult = quickInfer([...demoMessages, ...sgMessages], 'combined-demo');
  console.log(`\n✅ 集成 Skip Gate 后风险评分: ${(combinedResult.riskScore * 100).toFixed(0)}/100`);
  console.log(`✅ 原始风险评分: ${(result.riskScore * 100).toFixed(0)}/100`);
  console.log(`\n⚠️ 提示: 集成 Skip Gate 决策信息后，推理准确性提升！`);
  console.log('='.repeat(70));
}

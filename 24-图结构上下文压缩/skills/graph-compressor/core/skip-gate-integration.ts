/**
 * ============================================================
 *  ⏩  调度器 Skip Gate 决策记录
 * ============================================================
 *
 *  核心：将调度器的跳过/执行决策记录到图结构中，
 *    为压缩算法提供额外的优先级信息。
 *
 *  使用方式：
 *    1. 对话开始时，创建 SkipGateRecorder
 *    2. 每个执行步骤完成时，调用 recordDecision()
 *    3. 对话结束时，调用 finalizeContext() - 生成带有决策信息的压缩上下文
 *    4. 压缩算法在评分时考虑决策记录 → 提高决策节点的评分
 *
 *  决策类型：
 *    - EXECUTE: 实际执行了该步骤（记录完整）
 *    - SKIP:    跳过该步骤（记录原因，便于追溯）
 *    - DEFER:   延迟到后续执行（记录决策理由）
 *    - CONDITIONAL: 有条件执行（记录条件）
 */

import { graphCompress, type CompressMessage } from './graph-compress.ts';

export type DecisionType = 'EXECUTE' | 'SKIP' | 'DEFER' | 'CONDITIONAL';

export interface StepDecision {
  stepId: string;
  stepName: string;
  decision: DecisionType;
  reason?: string;
  confidence?: number;           // 决策置信度 0-1
  timestamp: number;
  costTokens?: number;
  latencyMs?: number;
  metadata?: Record<string, unknown>;
}

export interface TaskQueue {
  taskId: string;
  name: string;
  priority: number;             // 1-5, 1 最高
  status: 'pending' | 'executing' | 'done' | 'skipped';
  steps: StepDecision[];
  createdAt: number;
  completedAt?: number;
}

export interface SkipGateContext {
  sessionId: string;
  intent: string;
  tasks: TaskQueue[];
  totalMessages: number;
  totalDecisions: number;
  decisionsByType: Record<DecisionType, number>;
  overallConfidence: number;
  lastUpdated: number;
}

// ============================================================
// ==================== Skip Gate 记录器 ========================
// ============================================================

export class SkipGateRecorder {
  private sessionId: string;
  private decisions: StepDecision[] = [];
  private tasks: Map<string, TaskQueue> = new Map();
  private currentTask: TaskQueue | null = null;
  private highlightKeywords: string[] = [];

  constructor(sessionId: string, options: { highlightKeywords?: string[] } = {}) {
    this.sessionId = sessionId;
    this.highlightKeywords = options.highlightKeywords || [];
  }

  // --- 任务管理 ---
  startTask(taskId: string, name: string, priority: number = 3): void {
    if (this.tasks.has(taskId)) {
      this.currentTask = this.tasks.get(taskId)!;
      this.currentTask.status = 'executing';
      return;
    }

    const task: TaskQueue = {
      taskId,
      name,
      priority,
      status: 'executing',
      steps: [],
      createdAt: Date.now(),
    };
    this.tasks.set(taskId, task);
    this.currentTask = task;
  }

  completeTask(taskId?: string): void {
    const task = taskId
      ? this.tasks.get(taskId)
      : this.currentTask;
    if (task) {
      task.status = 'done';
      task.completedAt = Date.now();
    }
  }

  // --- 决策记录 ---
  recordDecision(decision: Omit<StepDecision, 'timestamp'>): void {
    const record: StepDecision = {
      ...decision,
      timestamp: Date.now(),
    };
    this.decisions.push(record);
    if (this.currentTask) {
      this.currentTask.steps.push(record);
    }
  }

  // 便捷方法
  recordExecute(stepId: string, stepName: string, reason?: string, tokens?: number, latency?: number): void {
    this.recordDecision({
      stepId, stepName, decision: 'EXECUTE', reason,
      costTokens: tokens, latencyMs: latency, confidence: 0.9,
    });
  }

  recordSkip(stepId: string, stepName: string, reason: string, confidence: number = 0.7): void {
    this.recordDecision({ stepId, stepName, decision: 'SKIP', reason, confidence });
  }

  recordDefer(stepId: string, stepName: string, reason: string): void {
    this.recordDecision({ stepId, stepName, decision: 'DEFER', reason, confidence: 0.5 });
  }

  recordConditional(stepId: string, stepName: string, condition: string, actualDecision: boolean): void {
    this.recordDecision({
      stepId, stepName, decision: 'CONDITIONAL',
      reason: `条件: ${condition} → ${actualDecision ? '执行' : '跳过'}`,
      confidence: 0.75,
    });
  }

  // --- 查询与汇总 ---
  getAllDecisions(): StepDecision[] {
    return [...this.decisions];
  }

  getDecisionsByTask(taskId: string): StepDecision[] {
    const task = this.tasks.get(taskId);
    return task ? [...task.steps] : [];
  }

  getSummary(): {
    total: number;
    byType: Record<DecisionType, number>;
    avgConfidence: number;
    executedCount: number;
    skippedCount: number;
  } {
    let total = this.decisions.length;
    let executedCount = 0;
    let skippedCount = 0;
    let totalConfidence = 0;
    const byType: Record<DecisionType, number> = {
      EXECUTE: 0, SKIP: 0, DEFER: 0, CONDITIONAL: 0,
    };

    for (const d of this.decisions) {
      byType[d.decision] += 1;
      if (d.decision === 'EXECUTE' || d.decision === 'CONDITIONAL') executedCount++;
      if (d.decision === 'SKIP') skippedCount++;
      if (d.confidence !== undefined) totalConfidence += d.confidence;
    }

    return {
      total,
      byType,
      avgConfidence: total > 0 ? totalConfidence / total : 0,
      executedCount,
      skippedCount,
    };
  }

  // --- 生成带 Skip Gate 信息的消息（用于压缩）---
  toMessages(): CompressMessage[] {
    const msgs: CompressMessage[] = [];

    // 1. 每个决策生成一条消息（带 importance 标记）
    for (const decision of this.decisions) {
      const importance: 'high' | 'medium' | 'low' =
        decision.decision === 'EXECUTE' && (decision.confidence ?? 0) >= 0.8 ? 'high' :
        decision.decision === 'SKIP' ? 'low' : 'medium';

      let content = `[${decision.decision}] ${decision.stepName}`;
      if (decision.reason) content += ` | 原因: ${decision.reason}`;
      if (decision.costTokens) content += ` | tokens: ${decision.costTokens}`;
      if (decision.latencyMs) content += ` | 耗时: ${decision.latencyMs}ms`;

      msgs.push({
        id: `sg_${decision.stepId}`,
        role: 'assistant',
        content,
        timestamp: decision.timestamp,
        importance,
        toolName: decision.decision === 'SKIP' ? 'skipped-by-scheduler' : undefined,
      });
    }

    return msgs;
  }

  // --- 生成 Skip Gate 压缩上下文（含决策图谱）---
  finalizeForContext(): {
    summary: SkipGateContext;
    messages: CompressMessage[];
  } {
    const msgs = this.toMessages();
    const summaryStats = this.getSummary();

    // 获取意图
    const text = msgs.map((m) => m.content).join(' ').toLowerCase();
    let intent = 'general';
    const INTENT_KWS = {
      trading: ['买入', '卖出', '止损', 'position', 'buy', 'sell'],
      analysis: ['分析', '研究', '行情', '分析', 'research'],
      coding: ['代码', '实现', '开发', '代码', 'bug', 'code'],
      design: ['设计', '架构', '方案', '架构', 'design'],
    };
    for (const [k, kws] of Object.entries(INTENT_KWS)) {
      if (kws.some((kw) => text.includes(kw.toLowerCase()))) {
        intent = k;
        break;
      }
    }

    const summary: SkipGateContext = {
      sessionId: this.sessionId,
      intent,
      tasks: Array.from(this.tasks.values()),
      totalMessages: msgs.length,
      totalDecisions: summaryStats.total,
      decisionsByType: summaryStats.byType,
      overallConfidence: summaryStats.avgConfidence,
      lastUpdated: Date.now(),
    };

    return { summary, messages: msgs };
  }

  // --- 完整压缩：将 Skip Gate 决策纳入评分 ---
  compressWithSkipGate(
    messages: CompressMessage[],
    targetRatio: number = 0.5
  ): {
    compression: ReturnType<typeof graphCompress>;
    skipGateSummary: SkipGateContext;
    combinedScore: number;
  } {
    // 1. 将 Skip Gate 决策添加到消息（提高重要决策节点的评分）
    // 实际上我们的 graphCompress 会处理 importance 标记
    // 这里将决策附加为 importance: 'high' 的消息
    const sgMessages = this.toMessages().filter((m) => m.importance === 'high');
    const combinedMessages = [...messages, ...sgMessages];

    // 2. 正常压缩
    const result = graphCompress({
      messages: combinedMessages,
      targetRatio,
      highlightKeywords: [
        'DECISION', 'EXECUTE', '关键', '重要', '决策',
        ...this.highlightKeywords,
      ],
    });

    const summary = this.getSummary();
    const combinedScore = Math.min(1,
      (summary.avgConfidence * 0.3 + result.summary.compressionRatio * 0.7)
    );

    return {
      compression: result,
      skipGateSummary: {
        sessionId: this.sessionId,
        intent: result.summary.intentDetected,
        tasks: Array.from(this.tasks.values()),
        totalMessages: combinedMessages.length,
        totalDecisions: summary.total,
        decisionsByType: summary.byType,
        overallConfidence: summary.avgConfidence,
        lastUpdated: Date.now(),
      },
      combinedScore,
    };
  }

  // --- 格式化输出（便于调试）---
  formatSummary(): string {
    const stats = this.getSummary();
    const lines: string[] = [];
    lines.push('='.repeat(60));
    lines.push('⏩ Skip Gate 决策记录');
    lines.push('='.repeat(60));
    lines.push(`会话: ${this.sessionId}`);
    lines.push(`总决策: ${stats.total} 个`);
    lines.push(`  执行: ${stats.byType.EXECUTE} 个`);
    lines.push(`  跳过: ${stats.byType.SKIP} 个`);
    lines.push(`  延迟: ${stats.byType.DEFER} 个`);
    lines.push(`  条件: ${stats.byType.CONDITIONAL} 个`);
    lines.push(`平均置信度: ${(stats.avgConfidence * 100).toFixed(0)}%`);
    lines.push('');
    lines.push('--- 决策记录 ---');
    this.decisions.slice(-10).forEach((d, i) => {
      const statusIcon = d.decision === 'EXECUTE' ? '▶' : d.decision === 'SKIP' ? '⏭' : '⏳';
      const confidence = ((d.confidence || 0) * 100).toFixed(0);
      lines.push(`  ${statusIcon} [${d.stepId}] ${d.stepName}`);
      if (d.reason) lines.push(`     原因: ${d.reason.slice(0, 80)}`);
      lines.push(`     置信度: ${confidence}%`);
    });
    return lines.join('\n');
  }
}

// ============================================================
// ==================== 便捷工厂 ===============================
// ============================================================

export function createSkipGateRecorder(sessionId: string): SkipGateRecorder {
  return new SkipGateRecorder(sessionId);
}

// ============================================================
// ==================== CLI 演示 ================================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('skip-gate-integration.ts')) {
  console.log('='.repeat(60));
  console.log('⏩ Skip Gate Integration - 调度器决策记录演示');
  console.log('='.repeat(60));

  const recorder = createSkipGateRecorder('demo-session-001');

  // 模拟一个交易决策流程
  console.log('\n▶ 开始任务: BTC 交易决策');
  recorder.startTask('task_trading', 'BTC 交易决策', 1);

  // Step 1: 市场数据收集
  recorder.recordExecute(
    'step_01', '市场数据收集',
    '用户明确要求了解行情',
    250, 350
  );

  // Step 2: 技术分析 - 执行
  recorder.recordExecute(
    'step_02', '技术指标分析 (RSI/MACD/均线)',
    '交易决策依赖技术指标',
    300, 400
  );

  // Step 3: 深度新闻分析 - 跳过（因为用户已经明确技术面足够）
  recorder.recordSkip(
    'step_03', '深度新闻分析',
    '用户仅关注技术面指标，新闻分析不是必要步骤',
    0.75
  );

  // Step 4: 策略参数计算 - 执行
  recorder.recordExecute(
    'step_04', '策略参数计算 (入场/止损/止盈)',
    '核心决策输出，必须提供具体参数',
    150, 120
  );

  // Step 5: 历史回测验证 - 跳过（因为用户没要求验证策略）
  recorder.recordSkip(
    'step_05', '历史回测验证',
    '用户已确认方案，无需执行完整回测',
    0.8
  );

  // Step 6: 执行信号生成 - 执行（关键决策）
  recorder.recordExecute(
    'step_06', '生成交易执行信号',
    '最终输出：入场 64,800 / 止损 64,200 / 止盈 65,800',
    180, 100
  );

  recorder.completeTask();

  console.log(recorder.formatSummary());

  // === 压缩：结合 Skip Gate 信息 ===
  console.log('\n📊 结合 Skip Gate 信息进行上下文压缩...');

  // 模拟对话消息
  const demoMessages: CompressMessage[] = [
    { id: 'u1', role: 'user', content: '帮我分析 BTC 行情', timestamp: Date.now() - 5000 },
    { id: 'a1', role: 'assistant', content: 'BTC 价格: 65,200 USDT，RSI: 55', timestamp: Date.now() - 4000 },
    { id: 'u2', role: 'user', content: '我想做多，入场点？', timestamp: Date.now() - 3000 },
    { id: 'a2', role: 'assistant', content: '建议入场 64,800，止损 64,200', importance: 'high', timestamp: Date.now() - 2000 },
    { id: 'u3', role: 'user', content: '好的，执行这个方案', importance: 'high', timestamp: Date.now() - 1000 },
  ];

  const result = recorder.compressWithSkipGate(demoMessages, 0.5);

  console.log(`\n--- 📈 压缩结果 ---`);
  console.log(`  保留消息: ${result.compression.kept.length}`);
  console.log(`  压缩消息: ${result.compression.compressed.length}`);
  console.log(`  压缩率: ${(result.compression.summary.compressionRatio * 100).toFixed(0)}%`);
  console.log(`  综合评分: ${(result.combinedScore * 100).toFixed(0)}%`);
  console.log(`  Skip Gate 决策总数: ${result.skipGateSummary.totalDecisions}`);
  console.log(`  Skipped: ${result.skipGateSummary.decisionsByType.SKIP} | Executed: ${result.skipGateSummary.decisionsByType.EXECUTE}`);

  console.log('\n--- 🔒 保留的关键消息 ---');
  result.compression.kept.slice(0, 6).forEach((msg, i) => {
    const icon = msg.importance === 'high' ? '⭐' : '•';
    console.log(`  ${icon} [${msg.role}] ${msg.content.slice(0, 80)}`);
  });

  console.log('\n' + '='.repeat(60));
  console.log('✅ Skip Gate 集成演示完成');
  console.log('='.repeat(60));
}

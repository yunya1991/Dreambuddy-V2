/**
 * /api/orchestrate - 双维度编排架构 API 路由
 *
 * 功能:
 * - POST: 执行完整的编排流程
 *   - 接收用户请求 → 识别意图 → 选择思维链
 *   → 执行步骤 → 交叉验证 → 返回结果
 * - GET: 获取已注册技能的元信息和编排器状态
 *
 * 核心理念: 作为前端与双维度编排器的桥梁，统一调用入口
 */

import { NextRequest, NextResponse } from 'next/server';

// 从图压缩模块导入编排器相关功能
import {
  ExecutionPlanner,
  ensureRegistryInitialized,
  getSkillsSummary,
  createDefaultContext,
  createSuccessResult,
  createFailureResult,
} from '@yunya/graph-context-compressor';

// ============================================================
// 类型定义
// ============================================================

interface OrchestrateRequest {
  sessionId?: string;
  userRequest: string;
  intent?: 'market_query' | 'deep_analysis' | 'execute_trade' | 'strategy_verify' | 'risk_alert';
  symbol?: string;
  complexity?: 'quick' | 'standard' | 'deep';
  tradingMode?: 'ai_skill' | 'classic' | 'hybrid';
  chainWeights?: {
    s_chain: number;
    c_chain: number;
    f_chain: number;
  };
  maxLatencyMs?: number;
}

interface OrchestrateResponse {
  success: boolean;
  planId: string;
  sessionId: string;
  totalTokensUsed: number;
  totalLatencyMs: number;
  overallConfidence: number;

  // 执行步骤详情
  steps?: Array<{
    stepId: string;
    stage: string;
    chain: string;
    status: string;
    answer: string;
    confidence: number;
    skillsCalled: Array<{
      skillId: string;
      skillName: string;
      confidence: number;
      latencyMs?: number;
    }>;
    decision?: string;
  }>;

  // 交叉验证结果
  crossValidationResults?: Array<{
    nodeId: string;
    signals?: Array<{
      chain: string;
      direction: string;
      confidence: number;
      reasoning?: string;
    }>;
    consensus?: {
      direction: string;
      overallConfidence: number;
      agreementLevel: string;
    };
    conflicts?: Array<{
      type: string;
      description: string;
    }>;
    recommendedAction?: string;
  }>;

  // 最终结论
  conclusion?: {
    direction: string;
    confidence: number;
    keyDecisionPoints: string[];
    reasoningPath: string[];
    nextSteps?: Array<{
      action: string;
      reasoning: string;
      estimatedConfidence?: number;
    }>;
  };

  // 图架构压缩数据（可用于前端可视化）
  graphData?: {
    nodes: Array<{
      id: string;
      type: string;
      name: string;
      level: string;
      status: string;
      tokens: number;
      summary: string;
      metadata: Record<string, unknown>;
    }>;
    edges: Array<{
      from: string;
      to: string;
      type: string;
    }>;
    stats: {
      totalNodes: number;
      avgConfidence: number;
      executionTime: number;
    };
  };

  // 错误信息
  error?: string;
  errorType?: 'validation_error' | 'execution_error' | 'timeout_error';
}

// ============================================================
// 辅助函数
// ============================================================

/**
 * 自动识别用户请求的意图类型
 */
function detectIntent(userRequest: string): OrchestrateRequest['intent'] {
  const lower = userRequest.toLowerCase();

  if (lower.includes('买') || lower.includes('卖') || lower.includes('交易') || lower.includes('execute')) {
    return 'execute_trade';
  }

  if (lower.includes('分析') || lower.includes('研究') || lower.includes('深度') || lower.includes('deep')) {
    return 'deep_analysis';
  }

  if (lower.includes('风险') || lower.includes('警戒') || lower.includes('alert')) {
    return 'risk_alert';
  }

  if (lower.includes('验证') || lower.includes('策略') || lower.includes('verify')) {
    return 'strategy_verify';
  }

  return 'market_query';
}

/**
 * 根据复杂度级别决定权重
 */
function getDefaultWeights(
  tradingMode: OrchestrateRequest['tradingMode']
): NonNullable<OrchestrateRequest['chainWeights']> {
  switch (tradingMode) {
    case 'classic':
      return { s_chain: 0.1, c_chain: 0.8, f_chain: 0.1 };
    case 'hybrid':
      return { s_chain: 0.45, c_chain: 0.35, f_chain: 0.2 };
    case 'ai_skill':
    default:
      return { s_chain: 0.7, c_chain: 0.2, f_chain: 0.1 };
  }
}

// ============================================================
// POST - 执行编排
// ============================================================

export async function POST(request: NextRequest): Promise<NextResponse<OrchestrateResponse>> {
  const startTime = Date.now();

  try {
    // 1. 解析请求
    const body: OrchestrateRequest = await request.json();

    // 2. 验证必填字段
    if (!body.userRequest || body.userRequest.trim() === '') {
      return NextResponse.json(
        {
          success: false,
          planId: `error_${Date.now()}`,
          sessionId: body.sessionId || 'anonymous',
          totalTokensUsed: 0,
          totalLatencyMs: Date.now() - startTime,
          overallConfidence: 0,
          error: 'userRequest 不能为空',
          errorType: 'validation_error',
        },
        { status: 400 }
      );
    }

    // 3. 初始化注册表（确保技能已注册）
    ensureRegistryInitialized();

    // 4. 构建执行上下文
    const sessionId = body.sessionId || `session_${Date.now()}`;
    const intent = body.intent || detectIntent(body.userRequest);
    const complexity = body.complexity || 'standard';
    const tradingMode = body.tradingMode || 'hybrid';
    const chainWeights = body.chainWeights || getDefaultWeights(tradingMode);

    // 5. 创建并执行规划器
    const planner = new ExecutionPlanner();

    const plannerContext = {
      sessionId,
      userRequest: body.userRequest,
      intent,
      symbol: body.symbol,
      complexity,
      tradingMode,
      chainWeights,
      maxLatencyMs: body.maxLatencyMs || 30000,
      budgetTokens: 5000,
      userRole: 'USER' as const,
      priorHistory: [],
    };

    // 6. 执行编排
    const result = await planner.execute(plannerContext);

    // 7. 构建响应
    const response: OrchestrateResponse = {
      success: result.success,
      planId: result.planId,
      sessionId,
      totalTokensUsed: result.totalTokensUsed,
      totalLatencyMs: Date.now() - startTime,
      overallConfidence: result.overallConfidence,
    };

    // 8. 添加步骤详情
    if (result.steps && result.steps.length > 0) {
      response.steps = result.steps.map(step => ({
        stepId: step.stepId,
        stage: step.stage,
        chain: step.chain,
        status: step.status,
        answer: step.answer,
        confidence: step.confidence,
        skillsCalled: (step.skillsCalled || []).map(sc => ({
          skillId: sc.skillId,
          skillName: sc.skillName,
          confidence: sc.result?.confidence || 0,
          latencyMs: sc.latencyMs,
          output: sc.result?.outputs || null,
        })),
        decision: step.decision,
      }));
    }

    // 9. 添加交叉验证结果
    if (result.crossValidationResults && result.crossValidationResults.length > 0) {
      response.crossValidationResults = result.crossValidationResults.map(cv => ({
        nodeId: cv.nodeId,
        signals: cv.signals?.map(s => ({
          chain: s.chain,
          direction: s.direction,
          confidence: s.confidence,
          reasoning: s.reasoning,
        })),
        consensus: cv.consensus
          ? {
              direction: cv.consensus.direction,
              overallConfidence: cv.consensus.overallConfidence,
              agreementLevel: cv.consensus.agreementLevel,
            }
          : undefined,
        conflicts: cv.conflicts?.slice(0, 10),
        recommendedAction: cv.recommendedAction,
      }));
    }

    // 10. 添加结论
    if (result.conclusion) {
      response.conclusion = {
        direction: result.conclusion.direction,
        confidence: result.conclusion.confidence,
        keyDecisionPoints: result.conclusion.keyDecisionPoints || [],
        reasoningPath: result.conclusion.reasoningPath || [],
        nextSteps: result.conclusion.nextSteps,
      };
    }

    // 11. 构建图架构数据（用于前端可视化）
    const nodes = [];
    const edges = [];

    // 添加步骤节点
    if (result.steps) {
      let prevNodeId: string | null = null;

      for (const step of result.steps) {
        const node = {
          id: step.stepId,
          type: 'thinking-step',
          name: step.stepId,
          level: step.chain,
          status: step.status,
          tokens: step.tokensUsed || 0,
          summary: step.answer.slice(0, 200),
          metadata: {
            stage: step.stage,
            chain: step.chain,
            confidence: step.confidence,
            decision: step.decision,
            skillsCalled: step.skillsCalled?.map(s => s.skillId) || [],
          },
        };
        nodes.push(node);

        if (prevNodeId) {
          edges.push({
            from: prevNodeId,
            to: step.stepId,
            type: 'sequence',
          });
        }
        prevNodeId = step.stepId;
      }
    }

    // 添加交叉验证节点
    if (result.crossValidationResults) {
      for (const cv of result.crossValidationResults) {
        nodes.push({
          id: cv.nodeId,
          type: 'cross-validation',
          name: cv.nodeId,
          level: 'X',
          status: cv.recommendedAction === 'proceed' ? 'completed' : 'pending',
          tokens: 0,
          summary: cv.consensus
            ? `共识: ${cv.consensus.direction} (${cv.consensus.overallConfidence}%)`
            : '交叉验证',
          metadata: {
            consensus: cv.consensus,
            conflicts: cv.conflicts,
            recommendedAction: cv.recommendedAction,
          },
        });
      }
    }

    response.graphData = {
      nodes,
      edges,
      stats: {
        totalNodes: nodes.length,
        avgConfidence: response.overallConfidence,
        executionTime: response.totalLatencyMs,
      },
    };

    return NextResponse.json(response, { status: 200 });

  } catch (error) {
    console.error('[orchestrate] 执行失败:', error);

    return NextResponse.json(
      {
        success: false,
        planId: `error_${Date.now()}`,
        sessionId: 'anonymous',
        totalTokensUsed: 0,
        totalLatencyMs: Date.now() - startTime,
        overallConfidence: 0,
        error: error instanceof Error ? error.message : 'Unknown error',
        errorType: 'execution_error',
      },
      { status: 500 }
    );
  }
}

// ============================================================
// GET - 获取编排器状态和技能元信息
// ============================================================

export async function GET(): Promise<NextResponse> {
  try {
    // 初始化注册表
    ensureRegistryInitialized();

    // 获取技能概览
    const skills = getSkillsSummary();

    // 按链分组
    const skillsByChain = {
      A: skills.filter(s => s.chain === 'A'),
      C: skills.filter(s => s.chain === 'C'),
      F: skills.filter(s => s.chain === 'F'),
    };

    // 按分类分组
    const skillsByCategory: Record<string, typeof skills> = {};
    for (const skill of skills) {
      if (!skillsByCategory[skill.category]) {
        skillsByCategory[skill.category] = [];
      }
      skillsByCategory[skill.category].push(skill);
    }

    return NextResponse.json({
      success: true,
      status: 'operational',
      version: '1.0.0',
      totalSkills: skills.length,
      skillsByChain,
      skillsByCategory,
      // 支持的意图类型
      supportedIntents: [
        { id: 'market_query', description: '市场行情查询' },
        { id: 'deep_analysis', description: '深度分析' },
        { id: 'execute_trade', description: '执行交易' },
        { id: 'strategy_verify', description: '策略验证' },
        { id: 'risk_alert', description: '风险预警' },
      ],
      // 支持的交易模式
      supportedTradingModes: [
        { id: 'ai_skill', description: 'AI 技能驱动模式' },
        { id: 'classic', description: '经典指标系统模式' },
        { id: 'hybrid', description: '混合模式（推荐）' },
      ],
      // 思维阶段定义
      thinkingStages: [
        { id: 'research', name: '调研' },
        { id: 'analysis', name: '分析' },
        { id: 'design', name: '设计' },
        { id: 'validate', name: '验证' },
        { id: 'execute', name: '执行' },
      ],
    }, { status: 200 });

  } catch (error) {
    console.error('[orchestrate] GET 失败:', error);
    return NextResponse.json(
      {
        success: false,
        status: 'error',
        error: error instanceof Error ? error.message : 'Unknown error',
      },
      { status: 500 }
    );
  }
}

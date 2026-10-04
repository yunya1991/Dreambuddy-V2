/**
 * Blueprint 注册表（跨 Session 复用）
 *
 * 设计：
 *   1. 基于用户意图的关键词哈希 → 路由到预定义或动态生成的 Blueprint
 *   2. 预定义 Blueprint 涵盖常见意图：经典交易、深度分析、持仓管理、信号执行 等
 *   3. 动态生成的 Blueprint 会被缓存，同类意图下一次对话可以直接复用
 *   4. 统计每个 Blueprint 的使用次数、平均耗时、平均压缩率 → 用于 A/B 测试
 */

import { BlueprintGraph, ANode, ArchitectureGraph } from './types';

export interface BlueprintTemplate {
  id: string;
  name: string;
  intentKeywords: string[];
  blueprint: BlueprintGraph;
  architectureFactory: () => ArchitectureGraph;
  stats: {
    useCount: number;
    avgCompressionRatio: number;
    avgLatencyMs: number;
    createdAt: number;
    lastUsedAt: number;
  };
}

// 深克隆工具（正确处理 Map）
function cloneArchitecture(arch: ArchitectureGraph): ArchitectureGraph {
  const clonedNodes = new Map();
  arch.nodes.forEach((node, id) => clonedNodes.set(id, { ...node, metadata: { ...node.metadata } }));
  return {
    ...arch,
    nodes: clonedNodes,
    edges: arch.edges.map((e) => ({ ...e, dataFlow: { ...e.dataFlow } })),
    id: `${arch.id}_clone_${Date.now()}`,
  };
}

function cloneBlueprint(bp: BlueprintGraph): BlueprintGraph {
  const clonedNodes = new Map();
  bp.nodes.forEach((node, id) => clonedNodes.set(id, { ...node, metadata: { ...node.metadata } }));
  return {
    ...bp,
    nodes: clonedNodes,
    edges: bp.edges.map((e) => ({ ...e, dataFlow: { ...e.dataFlow } })),
  };
}

// ==================== 核心注册表 ====================

class BlueprintRegistry {
  private templates = new Map<string, BlueprintTemplate>();
  private intentIndex = new Map<string, string[]>(); // 关键词 → templateId[]

  constructor() {
    this.register(this.buildClassicTradingTemplate());
    this.register(this.buildDeepAnalysisTemplate());
    this.register(this.buildSignalExecutionTemplate());
    this.register(this.buildPortfolioManagementTemplate());
  }

  // -------- 注册 --------
  register(template: BlueprintTemplate) {
    this.templates.set(template.id, template);
    template.intentKeywords.forEach((kw) => {
      const key = kw.toLowerCase();
      const existing = this.intentIndex.get(key) || [];
      if (!existing.includes(template.id)) existing.push(template.id);
      this.intentIndex.set(key, existing);
    });
  }

  // -------- 路由：根据用户意图找最匹配的 Blueprint --------
  routeByIntent(intent: string): BlueprintTemplate | null {
    if (!intent) return null;
    const lower = intent.toLowerCase();
    const scores = new Map<string, number>();

    // 关键词匹配：匹配的关键词越多，得分越高
    this.intentIndex.forEach((templateIds, keyword) => {
      if (lower.includes(keyword)) {
        templateIds.forEach((id) => {
          scores.set(id, (scores.get(id) || 0) + 1);
        });
      }
    });

    // 取最高得分的模板
    let bestId: string | null = null;
    let bestScore = 0;
    scores.forEach((s, id) => {
      if (s > bestScore) { bestScore = s; bestId = id; }
    });

    if (bestId && bestScore > 0) {
      const tpl = this.templates.get(bestId)!;
      this.touch(tpl);
      return tpl;
    }
    return null;
  }

  // -------- 统计反馈 --------
  recordUsage(templateId: string, outcome: { compressionRatio: number; latencyMs: number }) {
    const tpl = this.templates.get(templateId);
    if (!tpl) return;
    const n = tpl.stats.useCount + 1;
    tpl.stats.avgCompressionRatio =
      (tpl.stats.avgCompressionRatio * (n - 1) + outcome.compressionRatio) / n;
    tpl.stats.avgLatencyMs =
      (tpl.stats.avgLatencyMs * (n - 1) + outcome.latencyMs) / n;
    tpl.stats.useCount = n;
    tpl.stats.lastUsedAt = Date.now();
  }

  // -------- 访问器 --------
  getTemplate(id: string): BlueprintTemplate | undefined {
    const tpl = this.templates.get(id);
    if (tpl) this.touch(tpl);
    return tpl;
  }

  listAll(): { id: string; name: string; useCount: number; avgRatio: number }[] {
    const result: { id: string; name: string; useCount: number; avgRatio: number }[] = [];
    this.templates.forEach((tpl) => {
      result.push({
        id: tpl.id,
        name: tpl.name,
        useCount: tpl.stats.useCount,
        avgRatio: tpl.stats.avgCompressionRatio,
      });
    });
    return result;
  }

  // -------- 动态注册：从已有执行历史中学习 Blueprint --------
  registerFromExecution(
    id: string,
    name: string,
    intentKeywords: string[],
    bp: BlueprintGraph,
    arch: ArchitectureGraph
  ): BlueprintTemplate {
    const tpl: BlueprintTemplate = {
      id,
      name,
      intentKeywords,
      blueprint: bp,
      architectureFactory: () => cloneArchitecture(arch),
      stats: { useCount: 0, avgCompressionRatio: 1, avgLatencyMs: 0, createdAt: Date.now(), lastUsedAt: Date.now() },
    };
    this.register(tpl);
    return tpl;
  }

  private touch(tpl: BlueprintTemplate) {
    tpl.stats.lastUsedAt = Date.now();
  }

  // ==================== 预定义模板 ====================

  private buildClassicTradingTemplate(): BlueprintTemplate {
    const rootId = 'classic-trading-root';
    const bp: BlueprintGraph = {
      id: 'blueprint-classic-trading',
      name: '经典交易',
      version: 'v1',
      nodes: new Map(),
      edges: [],
      rootId,
      createdAt: Date.now(),
    };
    const modules = [
      { id: 'market-analysis', name: '市场分析', desc: '整体行情 / 趋势判断' },
      { id: 'coin-selection', name: '代币筛选', desc: '基于经典指标的择币' },
      { id: 'entry-signal', name: '入场信号', desc: '技术指标入场点识别' },
      { id: 'risk-gating', name: '风险管理', desc: '止损 / 止盈 / 仓位控制' },
      { id: 'exit-signal', name: '离场信号', desc: '离场条件判断' },
      { id: 'execution', name: '执行决策', desc: '最终执行建议' },
    ];
    bp.nodes.set(rootId, { id: rootId, type: 'service', name: '经典交易服务', description: '整合经典指标的端到端交易流程', metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' } });
    modules.forEach((m) => {
      bp.nodes.set(m.id, {
        id: m.id,
        type: 'module',
        name: m.name,
        description: m.desc,
        metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
        children: [],
      });
      bp.edges.push({
        source: rootId,
        target: m.id,
        dataFlow: { type: 'delegate', schema: 'none', description: `调用 ${m.name}` },
      });
    });

    const arch: ArchitectureGraph = {
      id: 'arch-classic-trading',
      blueprintId: bp.id,
      nodes: new Map(),
      edges: [],
      entryPoint: 'step-market',
    };
    const steps: [string, string, string, string][] = [
      ['step-market', 'step', '市场分析', 'market-analysis'],
      ['step-coin', 'step', '代币筛选', 'coin-selection'],
      ['step-entry', 'step', '入场信号识别', 'entry-signal'],
      ['step-risk', 'decision', '风险门控判断', 'risk-gating'],
      ['step-exit', 'step', '离场信号识别', 'exit-signal'],
      ['step-execute', 'decision', '执行决策', 'execution'],
    ];
    steps.forEach(([id, type, name, parentId], idx) => {
      arch.nodes.set(id, {
        id,
        type: type as 'step' | 'decision' | 'parallel',
        name,
        parentNodeId: parentId,
        metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
        requires: idx > 0 ? [steps[idx - 1][0]] : [],
      });
    });

    return {
      id: 'blueprint-classic-trading',
      name: '经典交易',
      intentKeywords: ['经典', '交易', '买入', '卖出', '信号', 'strategy', 'trade', 'classic'],
      blueprint: bp,
      architectureFactory: () => cloneArchitecture(arch),
      stats: { useCount: 0, avgCompressionRatio: 1, avgLatencyMs: 0, createdAt: Date.now(), lastUsedAt: Date.now() },
    };
  }

  private buildDeepAnalysisTemplate(): BlueprintTemplate {
    const bp: BlueprintGraph = {
      id: 'blueprint-deep-analysis',
      name: '深度分析',
      version: 'v1',
      nodes: new Map(),
      edges: [],
      rootId: 'deep-analysis-root',
      createdAt: Date.now(),
    };
    bp.nodes.set('deep-analysis-root', {
      id: 'deep-analysis-root',
      type: 'service',
      name: '深度分析服务',
      description: '多维度市场深度分析',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
    });
    ['macro-analysis', 'technical-analysis', 'fundamental-analysis', 'sentiment-analysis', 'risk-report'].forEach((id, idx) => {
      bp.nodes.set(id, {
        id,
        type: 'module',
        name: ['宏观分析', '技术分析', '基本面分析', '情绪分析', '风险报告'][idx],
        description: '',
        metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
        children: [],
      });
      bp.edges.push({ source: 'deep-analysis-root', target: id, dataFlow: { type: 'delegate', schema: '', description: '' } });
    });

    const arch: ArchitectureGraph = {
      id: 'arch-deep-analysis',
      blueprintId: bp.id,
      nodes: new Map(),
      edges: [],
      entryPoint: 'macro-analysis',
    };
    ['macro-analysis', 'technical-analysis', 'fundamental-analysis', 'sentiment-analysis', 'risk-report'].forEach((id, idx, arr) => {
      arch.nodes.set(id, {
        id,
        type: idx === arr.length - 1 ? 'decision' : 'step',
        name: ['宏观分析', '技术分析', '基本面分析', '情绪分析', '风险报告'][idx],
        parentNodeId: id,
        metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
        requires: idx > 0 ? [arr[idx - 1]] : [],
      });
    });

    return {
      id: 'blueprint-deep-analysis',
      name: '深度分析',
      intentKeywords: ['分析', '研究', '深度', 'research', 'analysis', '报告', 'report'],
      blueprint: bp,
      architectureFactory: () => cloneArchitecture(arch),
      stats: { useCount: 0, avgCompressionRatio: 1, avgLatencyMs: 0, createdAt: Date.now(), lastUsedAt: Date.now() },
    };
  }

  private buildSignalExecutionTemplate(): BlueprintTemplate {
    const bp: BlueprintGraph = {
      id: 'blueprint-signal-execution',
      name: '信号执行',
      version: 'v1',
      nodes: new Map(),
      edges: [],
      rootId: 'signal-exec-root',
      createdAt: Date.now(),
    };
    bp.nodes.set('signal-exec-root', { id: 'signal-exec-root', type: 'service', name: '信号执行', description: '识别信号并指导执行', metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' } });
    ['signal-detect', 'signal-verify', 'signal-plan', 'signal-execute'].forEach((id, idx) => {
      bp.nodes.set(id, { id, type: 'module', name: ['信号检测', '信号验证', '执行计划', '执行决策'][idx], description: '', metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' }, children: [] });
      bp.edges.push({ source: 'signal-exec-root', target: id, dataFlow: { type: 'delegate', schema: '', description: '' } });
    });
    const arch: ArchitectureGraph = {
      id: 'arch-signal', blueprintId: bp.id, nodes: new Map(), edges: [], entryPoint: 'signal-detect',
    };
    ['signal-detect', 'signal-verify', 'signal-plan', 'signal-execute'].forEach((id, idx, arr) => {
      arch.nodes.set(id, { id, type: idx === arr.length - 1 ? 'decision' : 'step', name: id, parentNodeId: id, metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' }, requires: idx > 0 ? [arr[idx - 1]] : [] });
    });
    return {
      id: 'blueprint-signal-execution',
      name: '信号执行',
      intentKeywords: ['信号', 'signal', '执行', 'execute', '入场', '离场'],
      blueprint: bp,
      architectureFactory: () => cloneArchitecture(arch),
      stats: { useCount: 0, avgCompressionRatio: 1, avgLatencyMs: 0, createdAt: Date.now(), lastUsedAt: Date.now() },
    };
  }

  private buildPortfolioManagementTemplate(): BlueprintTemplate {
    const bp: BlueprintGraph = {
      id: 'blueprint-portfolio',
      name: '持仓管理',
      version: 'v1',
      nodes: new Map(),
      edges: [],
      rootId: 'portfolio-root',
      createdAt: Date.now(),
    };
    bp.nodes.set('portfolio-root', { id: 'portfolio-root', type: 'service', name: '持仓管理', description: '管理用户持仓与再平衡', metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' } });
    ['holding-review', 'rebalance-analysis', 'risk-review', 'rebalance-plan'].forEach((id, idx) => {
      bp.nodes.set(id, { id, type: 'module', name: ['持仓审查', '再平衡分析', '风险审查', '再平衡计划'][idx], description: '', metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' }, children: [] });
      bp.edges.push({ source: 'portfolio-root', target: id, dataFlow: { type: 'delegate', schema: '', description: '' } });
    });
    const arch: ArchitectureGraph = {
      id: 'arch-portfolio', blueprintId: bp.id, nodes: new Map(), edges: [], entryPoint: 'holding-review',
    };
    ['holding-review', 'rebalance-analysis', 'risk-review', 'rebalance-plan'].forEach((id, idx, arr) => {
      arch.nodes.set(id, { id, type: idx === arr.length - 1 ? 'decision' : 'step', name: id, parentNodeId: id, metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' }, requires: idx > 0 ? [arr[idx - 1]] : [] });
    });
    return {
      id: 'blueprint-portfolio',
      name: '持仓管理',
      intentKeywords: ['持仓', '仓位', '组合', 'portfolio', '再平衡', 'rebalance', '风险', 'risk'],
      blueprint: bp,
      architectureFactory: () => cloneArchitecture(arch),
      stats: { useCount: 0, avgCompressionRatio: 1, avgLatencyMs: 0, createdAt: Date.now(), lastUsedAt: Date.now() },
    };
  }
}

// 单例
export const blueprintRegistry = new BlueprintRegistry();

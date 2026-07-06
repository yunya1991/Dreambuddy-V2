/**
 * 节点缺失检测 + LLM 驱动搜索补充器
 *
 * 位置: 6-图结构上下文压缩/planner/node-gap-supplementer.ts
 *
 * 设计依据: 用户提出的 Superpower 模式核心流程
 *   "形成完整方案时，有节点注册就直接调用，
 *    如果没有则通过大模型驱动搜索最佳实践完善补充节点，
 *    并后期存入记忆，后期进化时可以验证，丰富技能，增加节点注册表"
 *
 * 工作流程:
 *   1. 检测节点覆盖度（注册表是否足以服务当前意图）
 *   2. 如果存在缺口 → LLM 驱动搜索最佳实践
 *   3. 生成临时 ThinkingStepDefinition 节点供本次执行
 *   4. 将补充节点存入记忆（SupplementMemoryStore）
 *   5. 后期进化：验证、丰富技能、提升为注册节点
 */

import {
  ThinkingStepDefinition,
  ConfidenceThresholds,
} from './step-types.ts';
import {
  SkillChain,
  ThinkStage,
  ExecutionContext,
} from './skill-types.ts';
import {
  IntentType,
} from './planner-types.ts';
import { SkillsRegistry } from './skills-registry';
import {
  SupplementMemoryStore,
  SupplementMemoryEntry,
} from './supplement-memory-store.ts';

// ============================================================
// 类型定义
// ============================================================

/** 能力需求描述 */
export interface CapabilityRequirement {
  /** 能力 ID（如 'risk-quantifier'） */
  capabilityId: string;
  /** 能力名称 */
  name: string;
  /** 能力描述 */
  description: string;
  /** 所需的阶段 */
  stage: ThinkStage;
  /** 所需的链 */
  chain: SkillChain;
  /** 适用的意图 */
  applicableIntents: IntentType[];
  /** 优先级 */
  priority: 'high' | 'medium' | 'low';
  /** 推荐来源 */
  source: 'registry' | 'llm_supplement' | 'memory_recall';
}

/** 节点缺失检测结果 */
export interface NodeGapDetectionResult {
  /** 是否存在缺口 */
  hasGap: boolean;
  /** 缺失的能力需求列表 */
  missingCapabilities: CapabilityRequirement[];
  /** 当前已注册的覆盖能力 */
  coveredCapabilities: CapabilityRequirement[];
  /** 缺口严重程度 */
  severity: 'none' | 'low' | 'medium' | 'high';
  /** 缺口原因 */
  reasons: string[];
}

/** LLM 桥接器接口（用于搜索最佳实践） */
export interface NodeSupplementLLMBridge {
  /**
   * 搜索最佳实践，生成补充节点规格
   *
   * LLM 应基于：
   *   - 当前意图和用户请求
   *   - 缺失的能力需求
   *   - 已有节点的能力边界
   * 返回适合填补缺口的节点定义
   */
  searchBestPractices(params: {
    intent: IntentType;
    userRequest: string;
    missingCapabilities: CapabilityRequirement[];
    existingCapabilities: CapabilityRequirement[];
    context?: Partial<ExecutionContext>;
  }): Promise<SupplementNodeSpec[]>;
}

/** 补充节点规格（LLM 生成或记忆召回的临时节点定义） */
export interface SupplementNodeSpec {
  /** 节点 ID（带前缀 SUP- 防止与注册节点冲突） */
  id: string;
  /** 节点名称 */
  name: string;
  /** 节点描述 */
  description: string;
  /** 所属阶段 */
  stage: ThinkStage;
  /** 所属链 */
  chain: SkillChain;
  /** 核心问题 */
  coreQuestion: string;
  /** 期望产出 */
  expectedOutputs: string[];
  /** 推荐的技能类别 */
  recommendedSkillCategories?: string[];
  /** 置信度阈值 */
  confidenceThresholds: {
    high: number;
    medium: number;
    low: number;
  };
  /** 来源标记 */
  source: 'llm_supplement' | 'memory_recall';
  /** LLM 生成时的理由 */
  rationale: string;
}

/** 补充结果 */
export interface SupplementResult {
  /** 是否进行了补充 */
  supplemented: boolean;
  /** 补充的节点规格列表 */
  supplementNodes: SupplementNodeSpec[];
  /** 转换为 ThinkingStepDefinition 的节点（可直接插入执行计划） */
  stepDefinitions: ThinkingStepDefinition[];
  /** 来源说明 */
  source: 'none' | 'llm_supplement' | 'memory_recall' | 'mixed';
  /** 补充理由 */
  reasons: string[];
  /** 创建的记忆条目 ID（如果已存入记忆） */
  memoryEntryIds: string[];
}

// ============================================================
// 意图 → 能力需求映射表
// ============================================================

/**
 * 每种意图所需的核心能力清单
 *
 * 用于检测注册表是否覆盖了该意图的关键能力维度
 * 当注册表中缺少某个维度的技能时，触发 LLM 补充
 */
const INTENT_REQUIRED_CAPABILITIES: Record<IntentType, CapabilityRequirement[]> = {
  market_query: [
    {
      capabilityId: 'price-fetcher',
      name: '价格获取',
      description: '获取实时/历史价格数据',
      stage: 'research',
      chain: 'C',
      applicableIntents: ['market_query'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'market-regime-detector',
      name: '市场状态识别',
      description: '识别当前市场状态（趋势/震荡/高波动）',
      stage: 'analysis',
      chain: 'A',
      applicableIntents: ['market_query', 'deep_analysis'],
      priority: 'medium',
      source: 'registry',
    },
  ],
  deep_analysis: [
    {
      capabilityId: 'regime-detector',
      name: '市场状态识别',
      description: '判断市场所处阶段（趋势/震荡/转折）',
      stage: 'research',
      chain: 'A',
      applicableIntents: ['deep_analysis', 'scenario_sim'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'technical-analyzer',
      name: '技术面分析',
      description: '多周期技术指标分析',
      stage: 'analysis',
      chain: 'C',
      applicableIntents: ['deep_analysis', 'strategy_verify'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'sentiment-analyzer',
      name: '情绪面分析',
      description: '市场情绪和资金流向分析',
      stage: 'analysis',
      chain: 'F',
      applicableIntents: ['deep_analysis', 'risk_alert'],
      priority: 'medium',
      source: 'registry',
    },
    {
      capabilityId: 'risk-quantifier',
      name: '风险量化',
      description: '量化当前持仓或潜在交易的风险敞口',
      stage: 'validate',
      chain: 'A',
      applicableIntents: ['deep_analysis', 'risk_alert', 'execute_trade'],
      priority: 'medium',
      source: 'registry',
    },
  ],
  scenario_sim: [
    {
      capabilityId: 'regime-detector',
      name: '市场状态识别',
      description: '判断市场所处阶段',
      stage: 'research',
      chain: 'A',
      applicableIntents: ['scenario_sim', 'deep_analysis'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'scenario-engine',
      name: '情景推演引擎',
      description: '多情景假设推演和概率评估',
      stage: 'design',
      chain: 'A',
      applicableIntents: ['scenario_sim'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'backtest-simulator',
      name: '回测模拟',
      description: '历史数据回测验证',
      stage: 'validate',
      chain: 'C',
      applicableIntents: ['scenario_sim', 'strategy_verify'],
      priority: 'medium',
      source: 'registry',
    },
  ],
  strategy_verify: [
    {
      capabilityId: 'strategy-loader',
      name: '策略加载',
      description: '加载待验证的策略定义',
      stage: 'research',
      chain: 'C',
      applicableIntents: ['strategy_verify'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'backtest-engine',
      name: '回测引擎',
      description: '执行策略历史回测',
      stage: 'validate',
      chain: 'C',
      applicableIntents: ['strategy_verify'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'risk-adjusted-evaluator',
      name: '风险调整评估',
      description: '夏普比率、最大回撤等风险调整指标',
      stage: 'validate',
      chain: 'A',
      applicableIntents: ['strategy_verify'],
      priority: 'medium',
      source: 'registry',
    },
  ],
  execute_trade: [
    {
      capabilityId: 'pretrade-gatekeeper',
      name: '交易前检查',
      description: '交易前风险和合规检查',
      stage: 'validate',
      chain: 'A',
      applicableIntents: ['execute_trade'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'regime-detector',
      name: '市场状态识别',
      description: '交易前确认市场状态',
      stage: 'analysis',
      chain: 'A',
      applicableIntents: ['execute_trade', 'deep_analysis'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'position-sizer',
      name: '仓位计算',
      description: '基于风险承受能力计算仓位',
      stage: 'design',
      chain: 'A',
      applicableIntents: ['execute_trade'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'order-executor',
      name: '订单执行',
      description: '执行交易订单',
      stage: 'execute',
      chain: 'A',
      applicableIntents: ['execute_trade'],
      priority: 'high',
      source: 'registry',
    },
  ],
  risk_alert: [
    {
      capabilityId: 'risk-monitor',
      name: '风险监控',
      description: '实时监控持仓风险',
      stage: 'analysis',
      chain: 'A',
      applicableIntents: ['risk_alert'],
      priority: 'high',
      source: 'registry',
    },
    {
      capabilityId: 'alert-classifier',
      name: '告警分类',
      description: '告警严重程度分级',
      stage: 'validate',
      chain: 'A',
      applicableIntents: ['risk_alert'],
      priority: 'medium',
      source: 'registry',
    },
  ],
  simple_qa: [
    {
      capabilityId: 'knowledge-responder',
      name: '知识问答',
      description: '通用知识问答',
      stage: 'research',
      chain: 'A',
      applicableIntents: ['simple_qa'],
      priority: 'low',
      source: 'registry',
    },
  ],
  system_config: [],
  credits_query: [],
  artifact_query: [
    {
      capabilityId: 'artifact-searcher',
      name: '知识检索',
      description: '检索知识库',
      stage: 'research',
      chain: 'A',
      applicableIntents: ['artifact_query'],
      priority: 'low',
      source: 'registry',
    },
  ],
  command: [],
};

// ============================================================
// 节点缺失检测 + LLM 驱动补充器
// ============================================================

/**
 * 节点缺失检测 + LLM 驱动补充器
 *
 * 工作流程：
 *   1. detectGap() - 检测注册表是否覆盖当前意图的能力需求
 *   2. supplement() - LLM 搜索最佳实践生成补充节点
 *   3. toStepDefinitions() - 转换为可执行的 ThinkingStepDefinition
 *   4. 记忆集成 - 存入 memory store 供后期进化
 */
export class NodeGapSupplementer {
  private registry: SkillsRegistry;
  private memoryStore: SupplementMemoryStore;
  private llmBridge?: NodeSupplementLLMBridge;
  private maxSupplementNodes: number;

  constructor(
    registry: SkillsRegistry,
    memoryStore: SupplementMemoryStore,
    llmBridge?: NodeSupplementLLMBridge,
    maxSupplementNodes: number = 3
  ) {
    this.registry = registry;
    this.memoryStore = memoryStore;
    this.llmBridge = llmBridge;
    this.maxSupplementNodes = maxSupplementNodes;
  }

  // ============================================================
  // 第一步：节点缺失检测
  // ============================================================

  /**
   * 检测注册表是否覆盖当前意图的能力需求
   *
   * 算法：
   *   1. 获取意图所需的核心能力清单
   *   2. 遍历注册表，检查每个能力是否被覆盖
   *   3. 未被覆盖的 → 加入 missingCapabilities
   *   4. 根据 missing 数量和优先级计算 severity
   */
  detectGap(
    intent: IntentType,
    context?: Partial<ExecutionContext>
  ): NodeGapDetectionResult {
    const requiredCapabilities = INTENT_REQUIRED_CAPABILITIES[intent] || [];
    const reasons: string[] = [];
    const missing: CapabilityRequirement[] = [];
    const covered: CapabilityRequirement[] = [];

    if (requiredCapabilities.length === 0) {
      return {
        hasGap: false,
        missingCapabilities: [],
        coveredCapabilities: [],
        severity: 'none',
        reasons: [`意图「${intent}」无需特定能力节点`],
      };
    }

    // 获取注册表中所有技能
    const allSkills = this.registry.getAll();
    const registryCapabilities = new Map<string, string[]>();

    for (const skill of allSkills) {
      const meta = skill.metadata;
      for (const stage of meta.applicableStages) {
        const key = `${meta.chain}-${stage}`;
        if (!registryCapabilities.has(key)) {
          registryCapabilities.set(key, []);
        }
        registryCapabilities.get(key)!.push(meta.id);
      }
    }

    // 检查每个所需能力
    for (const req of requiredCapabilities) {
      const key = `${req.chain}-${req.stage}`;
      const coveringSkillIds = registryCapabilities.get(key) || [];

      // 进一步检查意图匹配
      const intentMatchedSkills = coveringSkillIds.filter(id => {
        const skill = this.registry.get(id);
        if (!skill) return false;
        return skill.metadata.applicableIntents.some(
          i => i === req.applicableIntents[0] || i === 'all' || i === '*'
        );
      });

      // 也检查 capabilityId 是否直接存在
      const directMatch = this.registry.has(req.capabilityId);

      if (directMatch || intentMatchedSkills.length > 0) {
        covered.push({ ...req, source: 'registry' });
      } else {
        missing.push(req);
        reasons.push(
          `缺少能力「${req.name}」(${req.capabilityId})：${req.description}`
        );
      }
    }

    // 评估严重程度
    const highPriorityMissing = missing.filter(m => m.priority === 'high');
    let severity: NodeGapDetectionResult['severity'] = 'none';
    if (highPriorityMissing.length >= 2) {
      severity = 'high';
    } else if (highPriorityMissing.length === 1) {
      severity = 'medium';
    } else if (missing.length > 0) {
      severity = 'low';
    }

    const hasGap = missing.length > 0;

    return {
      hasGap,
      missingCapabilities: missing,
      coveredCapabilities: covered,
      severity,
      reasons: hasGap ? reasons : ['注册表能力覆盖完整'],
    };
  }

  // ============================================================
  // 第二步：LLM 驱动搜索补充 + 记忆召回
  // ============================================================

  /**
   * 补充缺失节点
   *
   * 流程：
   *   1. 先从记忆中召回历史补充节点（validated 状态）
   *   2. 如果记忆不足以覆盖缺口 → LLM 搜索最佳实践
   *   3. 合并去重，生成最终补充节点列表
   *   4. 将新补充节点存入记忆（draft 状态）
   *   5. 转换为 ThinkingStepDefinition 供执行
   */
  async supplement(
    intent: IntentType,
    userRequest: string,
    gapResult: NodeGapDetectionResult,
    context?: Partial<ExecutionContext>
  ): Promise<SupplementResult> {
    const reasons: string[] = [];
    const memoryEntryIds: string[] = [];
    const allSupplementNodes: SupplementNodeSpec[] = [];
    const seenNodeIds = new Set<string>();

    // 1. 记忆召回：从历史补充节点中查找匹配
    const memoryHits = this.memoryStore.queryByIntent(intent);
    for (const entry of memoryHits) {
      if (entry.status === 'deprecated') continue;
      if (seenNodeIds.has(entry.nodeSpec.id)) continue;

      // 检查此记忆节点是否覆盖某个缺失能力
      const coversMissing = gapResult.missingCapabilities.some(
        m => m.stage === entry.nodeSpec.stage && m.chain === entry.nodeSpec.chain
      );
      if (coversMissing) {
        allSupplementNodes.push({
          ...entry.nodeSpec,
          source: 'memory_recall',
        });
        seenNodeIds.add(entry.nodeSpec.id);
        memoryEntryIds.push(entry.id);
        reasons.push(`从记忆召回节点「${entry.nodeSpec.name}」（状态：${entry.status}，验证 ${entry.validationCount} 次）`);
      }
    }

    // 2. 计算仍需 LLM 补充的缺口
    const remainingMissing = gapResult.missingCapabilities.filter(
      m => !allSupplementNodes.some(n => n.stage === m.stage && n.chain === m.chain)
    );

    // 3. 如果仍有缺口且 LLM 可用 → LLM 搜索最佳实践
    let source: SupplementResult['source'] = 'none';
    if (remainingMissing.length > 0 && this.llmBridge) {
      try {
        const llmNodes = await this.llmBridge.searchBestPractices({
          intent,
          userRequest,
          missingCapabilities: remainingMissing,
          existingCapabilities: gapResult.coveredCapabilities,
          context,
        });

        // 限制补充节点数量
        const limitedNodes = llmNodes.slice(0, this.maxSupplementNodes);

        for (const node of limitedNodes) {
          if (seenNodeIds.has(node.id)) continue;

          // 存入记忆（draft 状态）
          const memoryEntry = this.memoryStore.createEntry({
            intent,
            userRequestSummary: this.summarizeRequest(userRequest),
            nodeSpec: node,
            evolutionTags: ['llm-generated', 'pending-validation'],
          });

          allSupplementNodes.push(node);
          seenNodeIds.add(node.id);
          memoryEntryIds.push(memoryEntry.id);
          reasons.push(`LLM 生成补充节点「${node.name}」：${node.rationale}`);
        }

        source = allSupplementNodes.some(n => n.source === 'memory_recall')
          ? 'mixed'
          : 'llm_supplement';
      } catch (err) {
        reasons.push(`LLM 补充失败：${err instanceof Error ? err.message : '未知错误'}，将仅使用记忆召回节点`);
        source = 'memory_recall';
      }
    } else if (allSupplementNodes.length > 0) {
      source = 'memory_recall';
    }

    // 4. 转换为 ThinkingStepDefinition
    const stepDefinitions = allSupplementNodes.map(spec =>
      this.toStepDefinition(spec)
    );

    const supplemented = allSupplementNodes.length > 0;

    if (!supplemented) {
      reasons.push('无法补充缺失节点（无记忆命中且 LLM 不可用），将使用降级执行');
    }

    return {
      supplemented,
      supplementNodes: allSupplementNodes,
      stepDefinitions,
      source,
      reasons,
      memoryEntryIds,
    };
  }

  // ============================================================
  // 第三步：执行后反馈（用于记忆进化）
  // ============================================================

  /**
   * 上报补充节点的执行结果
   *
   * 用于记忆进化：
   *   - 成功 → successCount++，多次成功后状态提升为 validated
   *   - 失败 → failureCount++，多次失败后状态降级为 deprecated
   *   - 多次 validated 后可提升为 registered（注册到 SkillsRegistry）
   *
   * @param memoryEntryIds 记忆条目 ID 列表
   * @param results 执行结果（confidence 和 success）
   */
  reportExecutionOutcome(
    memoryEntryIds: string[],
    results: Array<{ entryId: string; success: boolean; confidenceContribution: number }>
  ): void {
    for (const result of results) {
      if (!memoryEntryIds.includes(result.entryId)) continue;
      this.memoryStore.updateStats(
        result.entryId,
        result.success,
        result.confidenceContribution
      );
    }
  }

  // ============================================================
  // 第四步：进化 - 将成熟补充节点提升为注册技能
  // ============================================================

  /**
   * 检查是否有补充节点可以提升为正式注册节点
   *
   * 提升条件：
   *   - status === 'validated'
   *   - validationCount >= 5
   *   - successRate >= 0.7
   *   - avgConfidenceContribution >= 10
   *
   * 提升后：
   *   - status → 'promoted'
   *   - 可选：注册到 SkillsRegistry（需要 SkillCapability 实现）
   *
   * @returns 可提升的条目列表
   */
  checkPromotionCandidates(): SupplementMemoryEntry[] {
    return this.memoryStore.findPromotionCandidates();
  }

  /**
   * 标记一个补充节点为已提升
   * 后续可以考虑创建 SkillCapability 并注册到 SkillsRegistry
   */
  promoteEntry(entryId: string): void {
    this.memoryStore.markPromoted(entryId);
  }

  // ============================================================
  // 私有方法
  // ============================================================

  /**
   * 将 SupplementNodeSpec 转换为 ThinkingStepDefinition
   */
  private toStepDefinition(spec: SupplementNodeSpec): ThinkingStepDefinition {
    const thresholds: ConfidenceThresholds = {
      high: spec.confidenceThresholds?.high ?? 80,
      medium: spec.confidenceThresholds?.medium ?? 60,
      low: spec.confidenceThresholds?.low ?? 40,
    };

    return {
      id: spec.id,
      stage: spec.stage,
      chain: spec.chain,
      label: `${spec.id}_${spec.name}`,
      icon: this.getIconForStage(spec.stage),
      description: spec.description,
      coreQuestion: spec.coreQuestion,
      expectedOutputs: spec.expectedOutputs,
      confidenceThresholds: thresholds,
      recommendedSkillCategories: spec.recommendedSkillCategories,
      // 标记为补充节点（非注册节点）
      isCrossValidationPoint: false,
      allowIteration: true,
      maxIterations: 1,
    };
  }

  private getIconForStage(stage: ThinkStage): string {
    const iconMap: Record<ThinkStage, string> = {
      research: '🔍',
      analysis: '📊',
      design: '🎨',
      validate: '✓',
      execute: '⚡',
    };
    return iconMap[stage] || '❓';
  }

  private summarizeRequest(userRequest: string): string {
    const trimmed = userRequest.trim();
    if (trimmed.length <= 80) return trimmed;
    return trimmed.slice(0, 77) + '...';
  }
}

// ============================================================
// 便捷函数
// ============================================================

/**
 * 创建一个 LLM 补充节点的 Spec（手动构造时使用）
 */
export function createSupplementNodeSpec(
  partial: Partial<SupplementNodeSpec> & {
    id: string;
    name: string;
    stage: ThinkStage;
    chain: SkillChain;
  }
): SupplementNodeSpec {
  return {
    id: partial.id.startsWith('SUP-') ? partial.id : `SUP-${partial.id}`,
    name: partial.name,
    description: partial.description || `补充节点：${partial.name}`,
    stage: partial.stage,
    chain: partial.chain,
    coreQuestion: partial.coreQuestion || `需要分析 ${partial.name} 相关的信息`,
    expectedOutputs: partial.expectedOutputs || [`${partial.name} 分析结论`],
    recommendedSkillCategories: partial.recommendedSkillCategories,
    confidenceThresholds: partial.confidenceThresholds || {
      high: 75,
      medium: 55,
      low: 35,
    },
    source: partial.source || 'llm_supplement',
    rationale: partial.rationale || '手动创建的补充节点',
  };
}

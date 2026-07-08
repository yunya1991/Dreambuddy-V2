/**
 * Superpower 模式 LLM 桥接适配器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/orchestration/superpower-llm-bridge.ts
 *
 * 职责:
 *   将 callLLM 适配为两个接口：
 *   1. ClarificationLLMBridge - 意图澄清引擎的 LLM 桥接
 *   2. NodeSupplementLLMBridge - 节点补充器的 LLM 桥接
 *
 * 设计依据: Claude Code Superpower 的 "多问后做" 模式
 *   - 澄清问题由 LLM 基于上下文动态生成（非固定模板）
 *   - 节点补充由 LLM 搜索最佳实践生成
 */

import { callLLM } from './llm-bridge';
import type { ClarificationLLMBridge } from '.././planner/intent-clarification-engine';
import type {
  ClarificationQuestion,
  ClarificationAssessment,
} from '.././planner/intent-clarification-engine';
import type { NodeSupplementLLMBridge } from '.././planner/node-gap-supplementer';
import type {
  SupplementNodeSpec,
  CapabilityRequirement,
} from '.././planner/node-gap-supplementer';
import type { ExecutionContext } from '.././planner/skill-types';
import type { IntentType } from '.././planner/planner-types';

// ============================================================
// 意图澄清 LLM 桥接
// ============================================================

/**
 * 创建 ClarificationLLMBridge 实例
 *
 * 使用 LLM 动态生成澄清问题，遵循 Superpower 的 "one question at a time" 原则
 */
export function createClarificationLLMBridge(uid?: string): ClarificationLLMBridge {
  return {
    async generateQuestion(
      userMessage: string,
      assessment: ClarificationAssessment,
      context?: Partial<ExecutionContext>
    ): Promise<ClarificationQuestion> {
      const systemPrompt = `你是一个意图澄清助手，借鉴 Claude Code Superpower 模式。

你的任务是基于用户的模糊请求，生成一个澄清问题。

核心规则：
1. 每次只问一个问题（one question at a time）
2. 优先多选题（multiple_choice），降低用户认知负担
3. 问题必须聚焦于以下维度之一：${assessment.clarificationDimensions.join('、')}
4. 选项数量 2-4 个，每个选项有简短说明
5. 问题要简洁明了，避免技术术语

返回 JSON 格式（不要 markdown 代码块）：
{
  "id": "clarify_<dimension>_<timestamp>",
  "type": "multiple_choice",
  "question": "问题文本",
  "dimension": "${assessment.clarificationDimensions[0]}",
  "priority": 1,
  "options": [
    {"key": "opt1", "label": "选项1", "hint": "说明", "inferredIntent": "deep_analysis"},
    {"key": "opt2", "label": "选项2", "hint": "说明", "inferredIntent": "market_query"}
  ]
}

如果维度不适合多选，可以用 open_ended 类型：
{
  "id": "clarify_<dimension>_<timestamp>",
  "type": "open_ended",
  "question": "问题文本",
  "dimension": "${assessment.clarificationDimensions[0]}",
  "priority": 1
}`;

      const userPrompt = `用户请求: "${userMessage}"

模糊度评估:
- 模糊级别: ${assessment.ambiguity}
- 模糊度评分: ${assessment.ambiguityScore}/100
- 检测到的问题: ${assessment.ambiguityReasons.join('; ')}
- 需要澄清的维度: ${assessment.clarificationDimensions.join(', ')}

上下文信息:
- 交易标的: ${context?.symbol || '未指定'}
- 当前意图: ${context?.intent || '未知'}

请生成一个聚焦于「${assessment.clarificationDimensions[0]}」维度的澄清问题。`;

      try {
        const result = await callLLM({
          prompt: userPrompt,
          systemPrompt,
          temperature: 0.5,
          maxTokens: 800,
          timeoutMs: 15000,
        }, uid);

        // 尝试解析 JSON（容错处理）
        const parsed = parseJSONLoose<ClarificationQuestion>(result.content);
        if (parsed && parsed.question && (parsed.type === 'multiple_choice' || parsed.type === 'open_ended')) {
          return parsed;
        }

        // 解析失败，返回 open_ended 兜底
        return {
          id: `clarify_llm_${Date.now()}`,
          type: 'open_ended',
          question: result.content.slice(0, 200) || '能再具体描述一下你的需求吗？',
          dimension: assessment.clarificationDimensions[0] || 'purpose',
          priority: 1,
        };
      } catch (err) {
        throw new Error(`LLM 澄清问题生成失败: ${err instanceof Error ? err.message : '未知错误'}`);
      }
    },
  };
}

// ============================================================
// 节点补充 LLM 桥接
// ============================================================

/**
 * 创建 NodeSupplementLLMBridge 实例
 *
 * 使用 LLM 搜索最佳实践，生成补充节点规格
 */
export function createNodeSupplementLLMBridge(uid?: string): NodeSupplementLLMBridge {
  return {
    async searchBestPractices(params: {
      intent: IntentType;
      userRequest: string;
      missingCapabilities: CapabilityRequirement[];
      existingCapabilities: CapabilityRequirement[];
      context?: Partial<ExecutionContext>;
    }): Promise<SupplementNodeSpec[]> {
      const systemPrompt = `你是一个交易分析系统的节点架构师。

你的任务是基于缺失的能力需求，搜索并生成补充节点定义。

核心原则：
1. 每个补充节点应填补一个明确的能力缺口
2. 节点定义要具体可执行，包含核心问题和期望产出
3. 节点 ID 以 "SUP-" 开头，简洁唯一
4. 置信度阈值合理（high: 70-85, medium: 50-65, low: 30-45）
5. 最多生成 3 个补充节点

返回 JSON 数组格式（不要 markdown 代码块）：
[
  {
    "id": "SUP-xxx",
    "name": "节点名称",
    "description": "节点描述",
    "stage": "research|analysis|design|validate|execute",
    "chain": "A|C|F",
    "coreQuestion": "此节点需要回答的核心问题",
    "expectedOutputs": ["产出1", "产出2"],
    "recommendedSkillCategories": ["category1"],
    "confidenceThresholds": {"high": 75, "medium": 55, "low": 35},
    "source": "llm_supplement",
    "rationale": "为什么需要此节点的理由"
  }
]`;

      const missingDesc = params.missingCapabilities
        .map(m => `- ${m.name} (${m.capabilityId}): ${m.description} [阶段:${m.stage}, 链:${m.chain}, 优先级:${m.priority}]`)
        .join('\n');

      const existingDesc = params.existingCapabilities
        .map(c => `- ${c.name} (${c.capabilityId})`)
        .join('\n');

      const userPrompt = `意图: ${params.intent}
用户请求: "${params.userRequest}"

缺失的能力:
${missingDesc}

已有的能力:
${existingDesc || '（无）'}

上下文:
- 交易标的: ${params.context?.symbol || '未指定'}

请为每个缺失能力生成一个补充节点定义。`;

      try {
        const result = await callLLM({
          prompt: userPrompt,
          systemPrompt,
          temperature: 0.4,
          maxTokens: 2000,
          timeoutMs: 25000,
        }, uid);

        const parsed = parseJSONLoose<SupplementNodeSpec[]>(result.content);
        if (Array.isArray(parsed)) {
          // 规范化每个节点的 ID
          return parsed.map(node => ({
            ...node,
            id: node.id?.startsWith('SUP-') ? node.id : `SUP-${node.id || 'generated'}`,
            source: 'llm_supplement' as const,
          }));
        }

        // 解析失败，返回空数组（让上层降级处理）
        return [];
      } catch (err) {
        throw new Error(`LLM 节点补充搜索失败: ${err instanceof Error ? err.message : '未知错误'}`);
      }
    },
  };
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 宽松的 JSON 解析
 *
 * 处理 LLM 输出中常见的格式问题：
 *   - markdown 代码块包裹
 *   - 前后多余文本
 *   - 单引号、尾随逗号
 */
function parseJSONLoose<T>(content: string): T | null {
  if (!content) return null;

  let text = content.trim();

  // 去除 markdown 代码块
  const codeBlockMatch = text.match(/```(?:json)?\s*([\s\S]*?)\s*```/);
  if (codeBlockMatch) {
    text = codeBlockMatch[1].trim();
  }

  // 尝试直接解析
  try {
    return JSON.parse(text) as T;
  } catch {
    // 继续尝试
  }

  // 尝试提取第一个 JSON 对象或数组
  const objectMatch = text.match(/\{[\s\S]*\}/);
  if (objectMatch) {
    try {
      return JSON.parse(objectMatch[0]) as T;
    } catch {
      // 继续
    }
  }

  const arrayMatch = text.match(/\[[\s\S]*\]/);
  if (arrayMatch) {
    try {
      return JSON.parse(arrayMatch[0]) as T;
    } catch {
      // 继续
    }
  }

  return null;
}

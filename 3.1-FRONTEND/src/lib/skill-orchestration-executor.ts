/**
 * SkillOrchestrationExecutor — SKILL 编排执行器（集成层）
 * ====================================
 * 将 M2 各组件串联为完整调用链，对接 /api/task/stream 路由。
 *
 * 调用链（SPEC §4.1）:
 *   TaskFile(intent已识别)
 *     → CognitiveContextBuilder.build()         // 四系统并行构建认知上下文
 *     → SkillSelector.select()                   // 规则+向量匹配选择 SKILL
 *     → DSHExecutionEngine.execute_plan()        // 节点优先 + LLM 兜底
 *     → CDriveCoordinator.decideFromResults()    // C 层反射决策
 *     → SummaryAgent.summarize()                 // 汇总 → FinalOutput
 *     → 构造 ResultFile 返回
 *
 * 设计原则:
 *   1. 双轨开关: USE_SKILL_ORCHESTRATION=true 时启用，否则走原路径
 *   2. FAIL-OPEN: 任一 M2 组件失败 → 返回 null，调用方降级到原路径
 *   3. 进度透传: 通过 onProgress 回调上报 SSE 事件
 *   4. 零侵入: 不修改 task-manager 既有逻辑，只新增分支
 *
 * 位置: 3.1-FRONTEND/src/lib/skill-orchestration-executor.ts
 *
 * 复用（避免重复造轮子）:
 *   - CognitiveContextBuilder（M1，单例 getCognitiveContextBuilder）
 *   - SkillSelector（M2.1，单例 getSkillSelector）
 *   - DSHExecutionEngine（M2.3.1，单例 getDSHExecutionEngine）
 *   - CDriveCoordinator（M2.3.2）
 *   - SummaryAgent（M2.3.3）
 *   - PlannerProgressEvent（planner-types，复用既有 SSE 事件格式）
 */

import { getCognitiveContextBuilder, withImitationContext, type IndexReference } from './cognitive-context-builder';
import { getSkillSelector, type IntentResult } from './skill-selector';
import { getDSHExecutionEngine, type SkillResult } from './dsh-execution-engine';
import { CDriveCoordinator } from './c-drive';
import { SummaryAgent } from './summary-agent';
import { getKnowledgeIngester } from './knowledge-ingest';
import { getEvolutionAgent } from './evolution-agent';
import { getImitationCounter } from './imitation-counter';
import type { PlannerProgressEvent } from './planner/planner-types';

// ── Token 消耗估算（可观测性埋点，§3.5） ──
// 估算规则: tokens ≈ chars / 4（标准 char-to-token 比率）
function estimateTokens(text: string): number {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}
interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}
function makeTokenUsage(inputTokens: number, outputTokens: number): TokenUsage {
  return {
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    total_tokens: inputTokens + outputTokens,
  };
}
import type { TaskFile } from './task-manager';

// ============================================================
// 1. 类型定义
// ============================================================

/** SKILL 编排执行结果（中间结构，由 task-manager 转为 ResultFile） */
export interface SkillOrchestrationResult {
  /** 最终汇总内容（markdown 文本） */
  content: string;
  content_type: 'markdown' | 'json' | 'text';
  /** 整体置信度 */
  confidence: number;
  /** 是否需要人工复核 */
  human_review_required: boolean;
  /** 执行摘要 */
  execution_summary: {
    chain_executed: string[];
    total_steps: number;
    skipped_steps: string[];
    intent_recognized: string;
    total_time_ms: number;
    /** SKILL 编排模式标记 */
    orchestration_mode: 'skill_orchestration';
    /** C-Drive 决策动作 */
    cdrive_action?: string;
    /** 各 SKILL 输出来源统计 */
    source_stats?: { node: number; llm: number; mixed: number };
    [key: string]: any;
  };
  /** 执行元数据 */
  metadata: {
    executor: 'skill_orchestration';
    /** 选中的 SKILL ID 列表 */
    skill_ids: string[];
    /** 选择理由 */
    match_reasons: string[];
    /** C-Drive 决策 */
    cdrive_decision?: any;
    /** 数据来源 */
    sources?: any[];
    [key: string]: any;
  };
  /** 产物（暂无，后续可扩展） */
  artifacts_produced: Array<{ file: string; type: string; chain_phase: string }>;
  /** 执行耗时 ms */
  execution_time_ms: number;
}

// ============================================================
// 2. 配置（动态读取环境变量，支持运行时切换）
// ============================================================

const ORCH_CONFIG = {
  /** 双轨开关（SPEC §5.1）: 环境变量 USE_SKILL_ORCHESTRATION=true 启用 */
  get enabled(): boolean {
    return process.env.USE_SKILL_ORCHESTRATION === 'true';
  },
  /** C-Drive 是否启用（可独立关闭，仅执行+汇总） */
  get cdrive_enabled(): boolean {
    return process.env.SKILL_ORCH_CDRIVE !== 'false';
  },
  /** 整体编排超时 */
  total_timeout_ms: 60000,
};

// ============================================================
// 3. 主执行函数
// ============================================================

/**
 * 检查 SKILL 编排是否启用（双轨开关）
 */
export function isSkillOrchestrationEnabled(): boolean {
  return ORCH_CONFIG.enabled;
}

/**
 * 执行 SKILL 编排调用链
 *
 * @param task - 已识别意图的任务文件
 * @param message - 用户原始消息
 * @param lang - 语言（zh/en）
 * @param onProgress - 进度回调（转发到 SSE）
 * @returns 成功返回 SkillOrchestrationResult，失败返回 null（FAIL-OPEN 降级）
 */
export async function executeSkillOrchestration(
  task: TaskFile,
  message: string,
  lang: 'zh' | 'en' = 'zh',
  onProgress?: (event: PlannerProgressEvent) => void,
): Promise<SkillOrchestrationResult | null> {
  const startTime = Date.now();
  const isZh = lang === 'zh';
  const intentType = task.intent.type;
  const entities = task.intent.entities || {};

  try {
    // ── Step 0: 上报开始 ──────────────────────────────
    onProgress?.({
      type: 'plan_created',
      message: isZh ? 'SKILL 编排链路启动' : 'Skill orchestration chain started',
      timestamp: Date.now(),
      data: { intent_type: intentType, orchestration: true },
    });

    // ── Step 1: 构建认知上下文（CognitiveContextBuilder） ──
    onProgress?.({
      type: 'step_start',
      stepId: 'CTX_BUILD',
      message: isZh ? '构建认知上下文（recall+RAG+索引+SKILL注册）' : 'Building cognitive context',
      timestamp: Date.now(),
    });

    const ctxBuilder = getCognitiveContextBuilder();
    const entityValues = Object.values(entities).filter(Boolean) as string[];
    const context = await ctxBuilder.build(intentType, entityValues, message);

    onProgress?.({
      type: 'step_end',
      stepId: 'CTX_BUILD',
      message: isZh
        ? `认知上下文构建完成: 经验${context.experiences.length} / 知识${context.knowledge.length} / 引用${context.references.length} / 候选${context.skill_candidates.length}`
        : `Context built: exp=${context.experiences.length} / knowledge=${context.knowledge.length} / refs=${context.references.length} / candidates=${context.skill_candidates.length}`,
      timestamp: Date.now(),
      data: {
        experiences: context.experiences.length,
        knowledge: context.knowledge.length,
        references: context.references.length,
        skill_candidates: context.skill_candidates.length,
      },
    });

    // ── Step 2: 选择 SKILL（SkillSelector，HC-1: 不用 LLM） ──
    onProgress?.({
      type: 'step_start',
      stepId: 'SKILL_SELECT',
      message: isZh ? '选择 SKILL（规则+向量匹配）' : 'Selecting SKILLs (rule+vector)',
      timestamp: Date.now(),
    });

    const selector = getSkillSelector();
    const intentResult: IntentResult = {
      type: intentType,
      entities,
      confidence: task.intent.confidence ?? 0.5,
      raw_text: message,
    };
    const plan = selector.select(intentResult, context);

    onProgress?.({
      type: 'step_end',
      stepId: 'SKILL_SELECT',
      message: isZh
        ? `选中 ${plan.skill_ids.length} 个 SKILL: ${plan.skill_ids.join(', ')}`
        : `Selected ${plan.skill_ids.length} SKILLs: ${plan.skill_ids.join(', ')}`,
      timestamp: Date.now(),
      data: {
        skill_ids: plan.skill_ids,
        match_reasons: plan.match_reasons,
      },
    });

    // ── SIE-SPEC §3.2.2: 路径 B 模仿分支 ──────────────────
    // 当 SkillSelector 返回 imitation_required=true 时，不走正常 Step 3，
    // 而是走路径 B: 文档检索 → LLM 转计划 → DSH 执行 → ImitationCounter 计数
    if (plan.imitation_required) {
      onProgress?.({
        type: 'step_start',
        stepId: 'IMITATION',
        message: isZh ? '路径 B: 模仿执行（文档检索 + LLM 转计划）' : 'Path B: Imitation (doc retrieval + LLM plan)',
        timestamp: Date.now(),
        data: { imitation_required: true, cosine_score: plan.match_reasons.find(r => r.includes('cosine')) || '' },
      });

      try {
        // SPL P1-3: 先检查 TDR 案例检索结果（CognitiveContextBuilder 第5系统已在 build() 中检索）
        if (context.solution_cases && context.solution_cases.length > 0) {
          const bestCase = context.solution_cases[0];
          const docContext = `## 历史解题模式\n意图: ${bestCase.intent}\n动作: ${bestCase.actions.join(' → ')}\n结果: ${bestCase.outcome_text}\n经验: ${bestCase.learned.join('; ')}`;

          onProgress?.({
            type: 'step_start',
            stepId: 'IMITATION',
            message: isZh ? `路径 B (SPL): 案例注入执行 (source: ${bestCase.id})` : `Path B (SPL): Case-injected (source: ${bestCase.id})`,
            timestamp: Date.now(),
            data: { imitation_required: true, case_source: bestCase.id, case_quality: bestCase.quality },
          });

          const engine = getDSHExecutionEngine();
          const knownComponents = engine.get_known_components();
          const imitationPlan = {
            ...plan,
            skill_ids: plan.skill_ids || ['simple_qa'],
            order: plan.order || ['simple_qa'],
            params: { document_context: docContext, known_components: knownComponents, case_source: bestCase.id },
          };
          const skillResults: SkillResult[] = await engine.execute_plan(imitationPlan);

          // ImitationCounter 计数（保留兜底）
          const counter = getImitationCounter();
          const incrementResult = counter.increment(message, [], JSON.stringify(imitationPlan.params));

          const content = skillResults.map(r => typeof r.content === 'string' ? r.content : JSON.stringify(r.content)).join('\n\n');
          const bTokenUsage = makeTokenUsage(estimateTokens(message) + estimateTokens(docContext), estimateTokens(content));

          onProgress?.({
            type: 'step_end',
            stepId: 'IMITATION',
            message: isZh ? `SPL 案例注入执行完成 (count ${incrementResult.current_count}/3)` : `SPL case-injected done (count ${incrementResult.current_count}/3)`,
            timestamp: Date.now(),
            data: { imitation_required: true, case_source: bestCase.id, count: incrementResult.current_count, token_usage: bTokenUsage },
          });

          // P1-4: 执行反馈回写 TDR（FAIL-OPEN）
          try {
            const { getCaseBankClient } = await import('./case-bank-client');
            const bankClient = getCaseBankClient();
            const outcomeText = skillResults.length > 0 && content ? '完成' : '失败';
            await bankClient.store({
              intent: message,
              actions: bestCase.actions,
              outcome_text: outcomeText,
              learned: bestCase.learned.length > 0 ? bestCase.learned : ['SPL replay'],
              message_id: `spl-replay-${Date.now()}`,
              message_summary_time: new Date().toISOString().replace('T', ' ').slice(0, 19),
              tags: ['spl-replay', `source:${bestCase.id}`],
              source: 'spl-path-b',
            });
          } catch {
            // FAIL-OPEN: 回写失败不影响主链路
          }

          return {
            content: content || (isZh ? '案例注入执行完成' : 'Case-injected execution done'),
            content_type: 'markdown' as const,
            confidence: 0.6,
            human_review_required: false,
            execution_summary: {
              chain_executed: ['IMITATION'],
              total_steps: 1,
              skipped_steps: [],
              intent_recognized: intentResult.type,
              total_time_ms: Date.now() - startTime,
              orchestration_mode: 'skill_orchestration' as const,
              source_stats: { node: 0, llm: skillResults.length, mixed: 0 },
            },
            metadata: {
              executor: 'skill_orchestration' as const,
              skill_ids: ['IMITATION'],
              match_reasons: ['spl: case-injected execution'],
              imitation_path: 'B-SPL' as const,
              case_source: bestCase.id,
              token_usage: bTokenUsage,
            },
            artifacts_produced: [],
            execution_time_ms: Date.now() - startTime,
          };
        }

        // Step 2.3: 调 index_query_service 检索文档（通过 DSH IPC 调 Python 索引服务）
        // 尝试通过 DSH handler 调用文档检索
        const { callDshHandler } = await import('./dsh-execution-engine');
        let docResults: any[] = [];
        try {
          const docResult = await callDshHandler('index_query', { query: message, category: 'doc', top_k: 5 });
          const raw = (docResult as any)?.output || docResult || [];
          docResults = Array.isArray(raw) ? raw : (raw?.results || raw?.data || []);
        } catch {
          // 文档检索服务不可达 → 跳转路径 C
          docResults = [];
        }

        const docContentRaw = docResults.map((d: any) => d.content || d.text || JSON.stringify(d)).join('\n\n');

        onProgress?.({
          type: 'step_end',
          stepId: 'IMITATION',
          message: isZh ? `文档检索: ${docResults.length} 条命中` : `Doc retrieval: ${docResults.length} hits`,
          timestamp: Date.now(),
          data: { doc_count: docResults.length, imitation_required: true, token_usage: makeTokenUsage(estimateTokens(message), estimateTokens(docContentRaw)) },
        });

        if (docResults.length > 0) {
          // Step 2.4-2.5: LLM 转执行计划 + DSH 执行（注入 document_context）
          // 获取白名单约束（M-2 修复）
          const engine = getDSHExecutionEngine();
          const knownComponents = engine.get_known_components();
          const docContext = docContentRaw;

          // SIE-SPEC §5.1 P1: 将文档检索结果注入 imitation_context
          const docRefs: IndexReference[] = docResults.map((d: any) => ({
            ref_id: d.ref_id || d.id || d.path || '',
            title: d.title || d.path || '',
            path: d.path || d.source || '',
            category: (d.category || 'doc') as IndexReference['category'],
            description: d.description || '',
          }));
          const enrichedContext = withImitationContext(context, docRefs);

          // 用 LLM fallback 分支执行（注入文档上下文）
          // 简化实现：直接用 DSH 的 LLM fallback，注入 document_context
          const imitationPlan = {
            ...plan,
            skill_ids: ['simple_qa'], // 用 simple_qa 作为 LLM fallback 载体
            order: ['simple_qa'],
            params: { document_context: docContext, known_components: knownComponents },
          };

          const skillResults: SkillResult[] = await engine.execute_plan(imitationPlan);

          // Step 2.6: ImitationCounter 计数
          const counter = getImitationCounter();
          const incrementResult = counter.increment(
            message,
            docResults.map((d: any) => d.path || d.source || ''),
            JSON.stringify(imitationPlan.params),
          );

          // 构造返回结果（模仿执行成功）
          const content = skillResults.map(r => typeof r.content === 'string' ? r.content : JSON.stringify(r.content)).join('\n\n');
          const bTokenUsage = makeTokenUsage(estimateTokens(message) + estimateTokens(docContext), estimateTokens(content));

          onProgress?.({
            type: 'step_end',
            stepId: 'IMITATION',
            message: isZh
              ? `模仿执行完成，计数 ${incrementResult.current_count}/${counter.constructor.name === 'IMITATION_THRESHOLD' ? 3 : 3}`
              : `Imitation done, count ${incrementResult.current_count}/3`,
            timestamp: Date.now(),
            data: { imitation_required: true, count: incrementResult.current_count, triggered: incrementResult.triggered, token_usage: bTokenUsage },
          });
          return {
            content: content || (isZh ? '模仿执行完成（基于文档）' : 'Imitation executed (based on docs)'),
            content_type: 'markdown' as const,
            confidence: 0.5,
            human_review_required: false,
            execution_summary: {
              chain_executed: ['IMITATION'],
              total_steps: 1,
              skipped_steps: [],
              intent_recognized: intentResult.type,
              total_time_ms: Date.now() - startTime,
              orchestration_mode: 'skill_orchestration' as const,
              source_stats: { node: 0, llm: skillResults.length, mixed: 0 },
            },
            metadata: {
              executor: 'skill_orchestration' as const,
              skill_ids: ['IMITATION'],
              match_reasons: ['imitation: document-based execution'],
              imitation_path: 'B',
              imitation_context: enrichedContext.imitation_context,
              token_usage: bTokenUsage,
            },
            artifacts_produced: [],
            execution_time_ms: Date.now() - startTime,
          };
        }

        // ── SIE-SPEC §3.3: 路径 C 联网兜底 ──────────────────
        // 文档为空 → 自动触发 dream-research-workflow 联网调研
        onProgress?.({
          type: 'step_start',
          stepId: 'RESEARCH',
          message: isZh ? '路径 C: 联网兜底（dream-research-workflow）' : 'Path C: Research fallback',
          timestamp: Date.now(),
          data: { research_triggered: true, reason: 'no_documents' },
        });

        try {
          // Step 3.2: 调 dream-research-workflow 联网调研
          let researchReport = '';
          try {
            const researchResult = await callDshHandler('research', {
              query: message,
              sources: ['finance', 'github', 'modular', 'code'],
            });
            const rOut: any = (researchResult as any)?.output || researchResult || {};
            researchReport = (rOut?.report || rOut?.content || (typeof rOut === 'string' ? rOut : '') || '');
          } catch {
            // research handler 不可达
            researchReport = '';
          }

          if (researchReport) {
            // Step 3.4-3.5: LLM 转执行计划 + DSH 执行（注入 research report 作为 document_context）
            const engine = getDSHExecutionEngine();
            const knownComponents = engine.get_known_components();
            // SIE-SPEC §5.1 P1: 将调研报告注入 imitation_context
            const enrichedContext = withImitationContext(context, [], researchReport);
            const researchPlan = {
              ...plan,
              skill_ids: ['simple_qa'],
              order: ['simple_qa'],
              params: { document_context: researchReport, known_components: knownComponents, source: 'research' },
            };
            const skillResults: SkillResult[] = await engine.execute_plan(researchPlan);

            // Step 3.6: knowledge-ingest 沉淀研究报告（只新增，HC-8）
            try {
              const ingester = getKnowledgeIngester();
              await ingester.ingest(researchReport, {
                title: `路径C调研-${Date.now()}`,
                source: 'path-c-research',
                category: 'external_research',
                domain: 'research',
                tags: ['auto-ingest', 'path-c'],
              });
            } catch {
              // knowledge-ingest 失败不阻塞
            }

            // 构造返回结果（路径 C 成功）
            const content = skillResults.map(r => typeof r.content === 'string' ? r.content : JSON.stringify(r.content)).join('\n\n');
            const cTokenUsage = makeTokenUsage(estimateTokens(message) + estimateTokens(researchReport), estimateTokens(content));

            onProgress?.({
              type: 'step_end',
              stepId: 'RESEARCH',
              message: isZh ? `联网调研完成，报告 ${researchReport.length} 字` : `Research done, report ${researchReport.length} chars`,
              timestamp: Date.now(),
              data: { research_triggered: true, report_size: researchReport.length, sedimentation: 'proposed', token_usage: cTokenUsage },
            });

            return {
              content: content || (isZh ? '基于联网调研结果执行' : 'Executed based on research'),
              content_type: 'markdown' as const,
              confidence: 0.4,
              human_review_required: false,
              execution_summary: {
                chain_executed: ['RESEARCH'],
                total_steps: 1,
                skipped_steps: [],
                intent_recognized: intentResult.type,
                total_time_ms: Date.now() - startTime,
                orchestration_mode: 'skill_orchestration' as const,
                source_stats: { node: 0, llm: skillResults.length, mixed: 0 },
              },
              metadata: {
                executor: 'skill_orchestration' as const,
                skill_ids: ['RESEARCH'],
                match_reasons: ['research: online fallback execution'],
                imitation_path: 'C',
                sedimentation_status: 'proposed',
                imitation_context: enrichedContext.imitation_context,
                token_usage: cTokenUsage,
              },
              artifacts_produced: [],
              execution_time_ms: Date.now() - startTime,
            };
          }

          // research 也为空 → 路径 C 失败
          const cFailTokenUsage = makeTokenUsage(estimateTokens(message), 0);
          onProgress?.({
            type: 'step_end',
            stepId: 'RESEARCH',
            message: isZh ? '联网调研无结果，标记人工审核' : 'Research yielded no results, human review required',
            timestamp: Date.now(),
            data: { research_triggered: true, success: false, token_usage: cFailTokenUsage },
          });

          // Step 3.7: 返回 human_review_required=true
          return {
            content: isZh ? '无法解决，请人工介入' : 'Unable to resolve, human review required',
            content_type: 'markdown' as const,
            confidence: 0.1,
            human_review_required: true,
            execution_summary: {
              chain_executed: ['IMITATION', 'RESEARCH'],
              total_steps: 2,
              skipped_steps: [],
              intent_recognized: intentResult.type,
              total_time_ms: Date.now() - startTime,
              orchestration_mode: 'skill_orchestration' as const,
              source_stats: { node: 0, llm: 0, mixed: 0 },
            },
            metadata: {
              executor: 'skill_orchestration' as const,
              skill_ids: [],
              match_reasons: ['path C failed: research yielded no results'],
              imitation_path: 'C',
              human_review_required: true,
              token_usage: cFailTokenUsage,
            },
            artifacts_produced: [],
            execution_time_ms: Date.now() - startTime,
          };
        } catch (researchError) {
          // 路径 C 失败 → human_review_required=true
          const cErrTokenUsage = makeTokenUsage(estimateTokens(message), 0);
          onProgress?.({
            type: 'step_end',
            stepId: 'RESEARCH',
            message: isZh ? `联网调研失败: ${(researchError as Error).message}` : `Research failed: ${(researchError as Error).message}`,
            timestamp: Date.now(),
            data: { research_triggered: true, error: (researchError as Error).message, token_usage: cErrTokenUsage },
          });

          return {
            content: isZh ? '无法解决，请人工介入' : 'Unable to resolve, human review required',
            content_type: 'markdown' as const,
            confidence: 0.1,
            human_review_required: true,
            execution_summary: {
              chain_executed: ['IMITATION', 'RESEARCH'],
              total_steps: 2,
              skipped_steps: [],
              intent_recognized: intentResult.type,
              total_time_ms: Date.now() - startTime,
              orchestration_mode: 'skill_orchestration' as const,
              source_stats: { node: 0, llm: 0, mixed: 0 },
            },
            metadata: {
              executor: 'skill_orchestration' as const,
              skill_ids: [],
              match_reasons: [`path C error: ${(researchError as Error).message}`],
              imitation_path: 'C',
              human_review_required: true,
              token_usage: cErrTokenUsage,
            },
            artifacts_produced: [],
            execution_time_ms: Date.now() - startTime,
          };
        }
      } catch (imitationError) {
        // 路径 B 失败 → FAIL-OPEN，降级到正常 Step 3
        onProgress?.({
          type: 'step_end',
          stepId: 'IMITATION',
          message: isZh ? `模仿执行失败，降级: ${(imitationError as Error).message}` : `Imitation failed, fallback: ${(imitationError as Error).message}`,
          timestamp: Date.now(),
          data: { imitation_required: true, error: (imitationError as Error).message },
        });
      }
    }

    // ── Step 3: 执行 SKILL 计划（DSHExecutionEngine，HC-2: 节点优先+LLM兜底） ──
    onProgress?.({
      type: 'step_start',
      stepId: 'DSH_EXEC',
      message: isZh ? '执行 SKILL 计划（节点优先 + LLM 兜底）' : 'Executing SKILL plan (node-first + LLM fallback)',
      timestamp: Date.now(),
    });

    const engine = getDSHExecutionEngine();
    const skillResults: SkillResult[] = await engine.execute_plan(plan);

    // 统计输出来源
    const sourceStats = { node: 0, llm: 0, mixed: 0 };
    for (const r of skillResults) {
      sourceStats[r.source] = (sourceStats[r.source] || 0) + 1;
    }

    onProgress?.({
      type: 'step_end',
      stepId: 'DSH_EXEC',
      message: isZh
        ? `SKILL 执行完成: ${skillResults.length} 个结果（node=${sourceStats.node}/llm=${sourceStats.llm}/mixed=${sourceStats.mixed}）`
        : `SKILL execution done: ${skillResults.length} results (node=${sourceStats.node}/llm=${sourceStats.llm}/mixed=${sourceStats.mixed})`,
      timestamp: Date.now(),
      data: {
        result_count: skillResults.length,
        source_stats: sourceStats,
        latencies: skillResults.map((r) => r.latency_ms),
      },
    });

    // ── Step 4: C-Drive 反射决策 ──
    let cdriveDecision: any = null;
    if (ORCH_CONFIG.cdrive_enabled && skillResults.length > 0) {
      onProgress?.({
        type: 'step_start',
        stepId: 'CDRIVE',
        message: isZh ? 'C-Drive 反射决策' : 'C-Drive reflection',
        timestamp: Date.now(),
      });

      const coordinator = new CDriveCoordinator();
      cdriveDecision = await coordinator.decideFromResults(skillResults, intentType);

      onProgress?.({
        type: 'step_end',
        stepId: 'CDRIVE',
        message: isZh
          ? `C-Drive 决策: ${cdriveDecision.action} (confidence=${cdriveDecision.confidence?.toFixed(2)})`
          : `C-Drive decision: ${cdriveDecision.action} (confidence=${cdriveDecision.confidence?.toFixed(2)})`,
        timestamp: Date.now(),
        data: {
          action: cdriveDecision.action,
          confidence: cdriveDecision.confidence,
          jump_to: cdriveDecision.jump_to,
          supplement_module: cdriveDecision.supplement_module,
        },
      });

      // C-Drive 建议 SUPPLEMENT → 补充执行 SubAgent
      if (coordinator.shouldSupplement(cdriveDecision)) {
        const suppModule = cdriveDecision.supplement_module;
        onProgress?.({
          type: 'cross_validation',
          stepId: 'SUPPLEMENT',
          message: isZh ? `补充执行 SubAgent: ${suppModule}` : `Supplementing SubAgent: ${suppModule}`,
          timestamp: Date.now(),
        });
        const suppResult = await engine.execute_skill(
 suppModule,
          { ...plan.params, supplement: true },
          context,
        );
        skillResults.push(suppResult);
      }
    }

    // ── Step 5: 汇总（SummaryAgent） ──
    onProgress?.({
      type: 'step_start',
      stepId: 'SUMMARY',
      message: isZh ? '汇总 Agent 综合输出' : 'Summary agent synthesizing',
      timestamp: Date.now(),
    });

    const summarizer = new SummaryAgent();
    const finalOutput = await summarizer.summarize(
      intentType,
      skillResults,
      cdriveDecision,
      context,
    );

    onProgress?.({
      type: 'step_end',
      stepId: 'SUMMARY',
      message: isZh
        ? `汇总完成: confidence=${finalOutput.confidence.toFixed(2)}${finalOutput.human_review_required ? ' [需人工复核]' : ''}`
        : `Summary done: confidence=${finalOutput.confidence.toFixed(2)}${finalOutput.human_review_required ? ' [review required]' : ''}`,
      timestamp: Date.now(),
      data: {
        confidence: finalOutput.confidence,
        human_review_required: finalOutput.human_review_required,
        sources_count: finalOutput.sources.length,
      },
    });

    // ── Step 5.5: 知识沉淀（调研类任务） ──────────────
    // 调研类意图执行完成后，自动触发知识入库（SPEC §3.6, §4.1 SSE knowledge_ingested）
    const RESEARCH_INTENTS = ['deep_analysis', 'scenario_sim', 'strategy_verify'];
    const contentText = _formatFinalOutput(finalOutput, isZh);
    let ingestedPath: string | undefined;
    if (RESEARCH_INTENTS.includes(intentType) && contentText) {
      try {
        onProgress?.({
          type: 'step_start',
          stepId: 'KNOWLEDGE_INGEST',
          message: isZh ? '知识沉淀入库中' : 'Ingesting knowledge',
          timestamp: Date.now(),
        });

        const ingester = getKnowledgeIngester();
        const ingestResult = await ingester.ingest(contentText, {
          title: `编排产出-${intentType}-${Date.now()}`,
          domain: intentType,
          tags: ['auto-ingest', intentType],
          source: 'SkillOrchestrationExecutor',
          category: 'external_research',
        });

        if (ingestResult.success && ingestResult.stored_path) {
          ingestedPath = ingestResult.stored_path;
          onProgress?.({
            type: 'knowledge_ingested',
            message: isZh ? `知识已入库: ${ingestedPath}` : 'Knowledge ingested',
            timestamp: Date.now(),
            data: {
              knowledge_path: ingestResult.stored_path,
              memory_id: ingestResult.memory_id,
            },
          });
        }
      } catch {
        // FAIL-OPEN: 知识沉淀失败不阻塞主流程
      }
    }

    // ── Step 6: 构造返回结果 ──────────────────────────
    const elapsed = Date.now() - startTime;

    onProgress?.({
      type: 'completed',
      message: isZh ? `SKILL 编排完成 (${elapsed}ms)` : `Skill orchestration completed (${elapsed}ms)`,
      timestamp: Date.now(),
      data: {
        execution_time_ms: elapsed,
        confidence: finalOutput.confidence,
      },
    });

    // ── Step 7: 自进化触发（异步，不阻塞返回） ──────────
    // SPEC §3.8: 每次任务完成后异步触发三大系统进化
    getEvolutionAgent().triggerAsync({
      intent_type: intentType,
      skill_ids: plan.skill_ids,
      final_output: contentText,
      is_research_type: RESEARCH_INTENTS.includes(intentType),
      success: finalOutput.confidence > 0.4,
    });

    return {
      content: contentText,
      content_type: 'markdown',
      confidence: finalOutput.confidence,
      human_review_required: finalOutput.human_review_required,
      execution_summary: {
        chain_executed: ['CTX_BUILD', 'SKILL_SELECT', 'DSH_EXEC', 'CDRIVE', 'SUMMARY'],
        total_steps: 5,
        skipped_steps: ORCH_CONFIG.cdrive_enabled ? [] : ['CDRIVE'],
        intent_recognized: intentType,
        total_time_ms: elapsed,
        orchestration_mode: 'skill_orchestration',
        cdrive_action: cdriveDecision?.action || null,
        source_stats: sourceStats,
        knowledge_ingested: !!ingestedPath,
      },
      metadata: {
        executor: 'skill_orchestration',
        skill_ids: plan.skill_ids,
        match_reasons: plan.match_reasons,
        cdrive_decision: cdriveDecision,
        sources: finalOutput.sources,
        human_review_required: finalOutput.human_review_required,
        knowledge_path: ingestedPath,
      },
      artifacts_produced: [],
      execution_time_ms: elapsed,
    };
  } catch (err) {
    // FAIL-OPEN: 编排链路任一步失败 → 返回 null，调用方降级到原路径
    const elapsed = Date.now() - startTime;
    console.error(`[SkillOrchestration] 编排失败 (${elapsed}ms), 降级到原路径:`, err);
    onProgress?.({
      type: 'error',
      message: isZh
        ? `SKILL 编排失败，降级到原路径: ${err instanceof Error ? err.message : String(err)}`
        : `Skill orchestration failed, falling back: ${err instanceof Error ? err.message : String(err)}`,
      timestamp: Date.now(),
      data: { error: err instanceof Error ? err.message : String(err), elapsed_ms: elapsed },
    });
    return null;
  }
}

// ============================================================
// 4. 内部辅助
// ============================================================

/**
 * 将 FinalOutput 格式化为 markdown 文本
 * 如果 FinalOutput.content 已是字符串，直接使用；否则做轻量格式化
 */
function _formatFinalOutput(output: any, isZh: boolean): string {
  // 如果 content 已经是 markdown 字符串，直接返回
  if (typeof output.content === 'string' && output.content.length > 0) {
    return output.content;
  }

  // 否则从 cards 结构构造 markdown
  const cards = Array.isArray(output.content?.cards) ? output.content.cards : [];
  if (cards.length === 0) {
    const reviewTag = output.human_review_required
      ? (isZh ? '\n\n> ⚠️ 置信度较低，建议人工复核' : '\n\n> ⚠️ Low confidence, human review recommended')
      : '';
    return (isZh ? '## SKILL 编排结果\n\n' : '## Skill Orchestration Result\n\n') +
      `confidence: ${(output.confidence ?? 0.5).toFixed(2)}` + reviewTag;
  }

  const parts: string[] = [];
  for (const card of cards) {
    const title = card.title || (isZh ? '洞察' : 'Insight');
    const body = typeof card.content === 'string' ? card.content : JSON.stringify(card.content, null, 2);
    parts.push(`### ${title}\n\n${body}`);
    if (typeof card.confidence === 'number') {
      parts.push(`\n_confidence: ${card.confidence.toFixed(2)}_`);
    }
  }

  if (output.human_review_required) {
    parts.push(isZh ? '\n---\n⚠️ 置信度较低，建议人工复核' : '\n---\n⚠️ Low confidence, human review recommended');
  }

  return parts.join('\n\n');
}

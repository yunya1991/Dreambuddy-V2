/**
 * CognitiveContextBuilder — 认知上下文构建层
 * ==========================================
 * 意图识别后，并行调用四大系统构建统一认知上下文：
 *   1. 认知系统 recall（历史经验）
 *   2. 知识库 RAG（相关知识）
 *   3. 索引系统 IndexQueryService（文档/代码定位）
 *   4. SKILL 注册中心（候选 SKILL）
 *
 * 设计原则（HC-7/9）：
 *   - 四系统并行调用，总延迟 ≤ 2s（P95）
 *   - 任一系统超时/失败则跳过，不阻塞整体（FAIL-OPEN）
 *   - 只读，不修改任何源系统数据
 *   - 各 top_k=5，避免上下文膨胀
 *
 * 位置: 3.1-FRONTEND/src/lib/cognitive-context-builder.ts
 */

import { callCognitive } from './cognitive-client';
import { retrieveRelevantChunks } from './knowledge-rag';
import { getSkillSelector, type IntentResult } from './skill-selector';
import * as Path from 'path';

// ============================================================
// 1. 类型定义（对齐 SPEC §3.0）
// ============================================================

export interface CognitiveContext {
  experiences: CognitiveExperience[];
  knowledge: KnowledgeChunk[];
  references: IndexReference[];
  skill_candidates: SkillCapability[];
  built_at: number;
  intent_type: string;
  /** SIE-SPEC §5.1 P1: 模仿上下文（路径 B/C 文档检索/调研报告注入） */
  imitation_context?: ImitationContext;
}

/**
 * SIE-SPEC §5.1 P1: 模仿上下文
 * 路径 B（文档检索结果）和路径 C（联网调研报告）的注入载体
 * 供下游消费者（SummaryAgent 等）访问文档/调研结果
 */
export interface ImitationContext {
  /** 路径 B 文档检索结果（IndexReference 格式） */
  document_results: IndexReference[];
  /** 路径 C 联网调研报告（markdown 文本，未触发时为 null） */
  research_report: string | null;
}

export interface CognitiveExperience {
  memory_id: string;
  content: string;
  quality_level: 'S' | 'A' | 'B' | 'C' | 'D';
  confidence: number;
  relevance_score: number;
}

export interface KnowledgeChunk {
  chunk_id: string;
  content: string;
  source_type: 'strategy_doc' | 'cbr_case' | 'hard_constraint' | 'external_research';
  domain: string;
  score: number;
}

export interface IndexReference {
  ref_id: string;
  title: string;
  path: string;
  category: 'doc' | 'skill' | 'module' | 'code';
  description: string;
}

export interface SkillCapability {
  skill_id: string;
  name: string;
  description: string;
  category: string;
  match_score: number;
  match_reasons: string[];
}

// ============================================================
// 2. 配置
// ============================================================

const CONTEXT_CONFIG = {
  total_timeout_ms: 2000,   // 总超时（HC-9）
  per_system_top_k: 5,      // 每个系统返回 top_k（避免膨胀）
  min_quality: 'C',         // 认知系统最低质量等级
};

// ============================================================
// 3. 单系统调用（带超时 + FAIL-OPEN）
// ============================================================

async function withTimeout<T>(
  fn: () => Promise<T>,
  timeoutMs: number,
  fallback: T,
  label: string,
): Promise<T> {
  return new Promise<T>((resolve) => {
    const timer = setTimeout(() => {
      resolve(fallback);
    }, timeoutMs);
    fn()
      .then((result) => {
        clearTimeout(timer);
        resolve(result);
      })
      .catch(() => {
        clearTimeout(timer);
        resolve(fallback);
      });
  });
}

/** 认知系统 recall */
async function fetchExperiences(intent: string, entities: string[]): Promise<CognitiveExperience[]> {
  const context = [intent, ...entities].filter(Boolean).join(' ');
  const result = await callCognitive<{ memories?: any[] }>('recall', {
    context,
    top_k: CONTEXT_CONFIG.per_system_top_k,
    min_quality: CONTEXT_CONFIG.min_quality,
  });
  if (!result.ok || !result.data?.memories) return [];
  return result.data.memories.map((m: any) => ({
    memory_id: m.id || '',
    content: m.content || '',
    quality_level: (m.quality_level || 'C') as CognitiveExperience['quality_level'],
    confidence: typeof m.confidence === 'number' ? m.confidence : 0.3,
    relevance_score: typeof m.score === 'number' ? m.score : 0,
  }));
}

/** 知识库 RAG 检索 */
async function fetchKnowledge(intent: string, intentType: string): Promise<KnowledgeChunk[]> {
  const chunks = await retrieveRelevantChunks(intent, intentType, CONTEXT_CONFIG.per_system_top_k);
  return chunks.map((c: any) => ({
    chunk_id: c.chunkId || c.id || '',
    content: c.content || '',
    source_type: (c.sourceType || 'strategy_doc') as KnowledgeChunk['source_type'],
    domain: c.domain || intentType || 'general',
    score: typeof c.score === 'number' ? c.score : 0,
  }));
}

/**
 * 索引系统查询（IndexQueryService）
 * 通过子进程调用 Python 适配器，FAIL-OPEN 模式
 */
async function fetchReferences(intent: string): Promise<IndexReference[]> {
  const { spawn } = await import('child_process');
  const adapterPath = Path.join(process.cwd(), 'scripts', 'index_query_adapter.py');
  const pythonBin = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';

  return new Promise<IndexReference[]>((resolve) => {
    const child = spawn(pythonBin, [adapterPath, 'query', intent, '--top-k', '5'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const timer = setTimeout(() => {
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve([]);
    }, CONTEXT_CONFIG.total_timeout_ms);

    let stdout = '';
    child.stdout.on('data', (chunk: Buffer) => { stdout += chunk.toString(); });
    child.on('error', () => { clearTimeout(timer); resolve([]); });
    child.on('close', () => {
      clearTimeout(timer);
      try {
        const data = JSON.parse(stdout);
        if (data.degraded || !data.results) {
          resolve([]);
          return;
        }
        resolve(data.results.map((r: any) => ({
          ref_id: r.title || r.path || '',
          title: r.title || '',
          path: r.path || '',
          category: (r.category || 'doc') as IndexReference['category'],
          description: r.description || '',
        })));
      } catch {
        resolve([]);
      }
    });
  });
}

/**
 * SKILL 注册中心查询
 * 通过 SkillSelector（规则匹配 + TF-IDF 向量兜底）选择候选 SKILL
 * HC-1: 不使用 LLM
 */
async function fetchSkillCandidates(
  intentType: string,
  intentText: string = '',
  entities: Record<string, string> = {},
  confidence: number = 0.8,
): Promise<SkillCapability[]> {
  try {
    const selector = getSkillSelector();
    const intent: IntentResult = {
      type: intentType,
      entities,
      confidence,
      raw_text: intentText || intentType,
    };
    const plan = selector.select(intent, {
      experiences: [],
      knowledge: [],
      references: [],
      skill_candidates: [],
      built_at: Date.now(),
      intent_type: intentType,
    });

    return plan.selections.map(sel => {
      const skill = selector.getSkill(sel.skill_id);
      return {
        skill_id: sel.skill_id,
        name: skill?.name || sel.skill_id,
        description: skill?.description || '',
        category: skill?.category || '',
        match_score: sel.match_score,
        match_reasons: sel.match_reasons,
      };
    });
  } catch {
    return []; // FAIL-OPEN
  }
}

// ============================================================
// 4. CognitiveContextBuilder 主类
// ============================================================

export class CognitiveContextBuilder {
  /**
   * 构建认知上下文
   * @param intent_type 意图类型
   * @param entities 实体列表
   * @param intent_text 原始意图文本
   * @returns CognitiveContext（四系统并行调用结果聚合）
   */
  async build(
    intent_type: string,
    entities: string[],
    intent_text: string,
  ): Promise<CognitiveContext> {
    const query = intent_text || intent_type;

    // 四系统并行调用，总超时 2s
    const [experiences, knowledge, references, skill_candidates] = await Promise.all([
      withTimeout(
        () => fetchExperiences(query, entities),
        CONTEXT_CONFIG.total_timeout_ms,
        [] as CognitiveExperience[],
        'cognitive-recall',
      ),
      withTimeout(
        () => fetchKnowledge(query, intent_type),
        CONTEXT_CONFIG.total_timeout_ms,
        [] as KnowledgeChunk[],
        'knowledge-rag',
      ),
      withTimeout(
        () => fetchReferences(query),
        CONTEXT_CONFIG.total_timeout_ms,
        [] as IndexReference[],
        'index-query',
      ),
      withTimeout(
        () => fetchSkillCandidates(
          intent_type,
          query,
          Object.fromEntries(entities.filter(Boolean).map((v, i) => [`entity_${i}`, v])),
        ),
        CONTEXT_CONFIG.total_timeout_ms,
        [] as SkillCapability[],
        'skill-registry',
      ),
    ]);

    return {
      experiences,
      knowledge,
      references,
      skill_candidates,
      built_at: Date.now(),
      intent_type,
    };
  }

  /** 判断认知上下文是否被实际使用（用于 F8 验收统计） */
  isContextUsed(ctx: CognitiveContext): boolean {
    return (
      ctx.experiences.length > 0 ||
      ctx.knowledge.length > 0 ||
      ctx.references.length > 0 ||
      ctx.skill_candidates.length > 0
    );
  }
}

// ============================================================
// 5. SIE-SPEC §5.1 P1: 模仿上下文注入
// ============================================================

/**
 * 将文档检索结果/调研报告注入到既有 CognitiveContext
 *
 * 路径 B: document_results 来自 index_query_service
 * 路径 C: research_report 来自 dream-research-workflow
 *
 * 不修改原上下文对象（HC-7 只读原则），返回新对象
 *
 * @param ctx 基础认知上下文（来自 build()）
 * @param documentResults 路径 B 文档检索结果（可选，默认空数组）
 * @param researchReport 路径 C 调研报告（可选，默认 null）
 * @returns 带有 imitation_context 字段的新上下文对象
 */
export function withImitationContext(
  ctx: CognitiveContext,
  documentResults: IndexReference[] = [],
  researchReport: string | null = null,
): CognitiveContext {
  return {
    ...ctx,
    imitation_context: {
      document_results: documentResults,
      research_report: researchReport,
    },
  };
}

// 单例导出
let _instance: CognitiveContextBuilder | null = null;
export function getCognitiveContextBuilder(): CognitiveContextBuilder {
  if (!_instance) _instance = new CognitiveContextBuilder();
  return _instance;
}

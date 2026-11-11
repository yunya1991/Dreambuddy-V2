/**
 * POST /api/agent/plan
 * 52-LobeHub 协议集成 Phase 4 — side-A PlanCard 生成入口（脑暴编排器 A 侧提案方）。
 *
 * Body: { intent: string, context_refs?: string[], variant?: { focus, seed } }
 *
 * 流程：resolveAgentModel（env 驱动）→ null 则 200 degraded 信封；
 * 否则独立取证（MCP unified_search → recall，FAIL-OPEN）→ 模型生成 PlanCard
 * → validatePlanCard 手写校验（不合规 200 degraded + 错误明细，绝不抛 500）
 * → { ok:true, data:{ plancard, model, evidence_path } }。
 *
 * variant（Phase 4.5）：脑暴编排器按 --n-per-side 多次调用本路由，
 * focus ∈ risk-first/cost-first/speed-first 注入提示词；缺省不改变原行为。
 * 返回前统一重签 card_id，保证并发/多次调用 id 唯一。
 *
 * 边界（硬约束）：只做规划层产物生成；plan_steps[].tool 只允许引用 47 registry
 * 已注册的 l0.* 工具；无任何执行/交易/记忆写能力（写工具由服务端拒绝）。
 * 只读：GET/PUT/DELETE 返回 405。
 */
import fs from 'fs';
import path from 'path';
import { NextRequest, NextResponse } from 'next/server';
import { generateText } from 'ai';
import { resolveAgentModel } from '@/lib/agent/providers';
import { getCognitionMcpClient } from '@/lib/agent/mcp-client';
import {
  validatePlanCard,
  newPlanCardId,
  PLAN_CARD_ID_PREFIX,
} from '@/lib/agent/plancard';
import {
  buildVariantPromptSection,
  normalizeVariant,
  type PlanVariant,
} from '@/lib/agent/plan-variant';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DEFAULT_EVALUATOR_REF = '45.heuristic@1.0.0';
const EVIDENCE_TOP_K = 5;

function degraded(reason: string, extra: Record<string, unknown> = {}) {
  return NextResponse.json({ ok: false, data: null, degraded: true, error: reason, ...extra });
}

/**
 * 从 47 registry 读取已注册 l0 工具集合（{shell}.{tool}）。
 * 极简行解析（不引 yaml 依赖）：shell_id 后跟 tools 列表。文件缺失 → 退回最小只读集合。
 */
export function loadRegisteredTools(): string[] {
  const registryPath =
    process.env.L0_REGISTRY_PATH ??
    path.join(process.cwd(), '..', '47-MCP管理系统', 'registry', 'mcp_capabilities.yaml');
  const fallback = [
    'l0.cognition.mcp.recall',
    'l0.cognition.mcp.unified_search',
    'l0.eval.mcp.eval_analyze',
  ];
  let text: string;
  try {
    text = fs.readFileSync(registryPath, 'utf-8');
  } catch {
    return fallback;
  }
  const tools: string[] = [];
  let shell = '';
  for (const rawLine of text.split('\n')) {
    const line = rawLine.replace(/#.*$/, '');
    const shellMatch = line.match(/^\s*-\s*shell_id:\s*["']?([a-z0-9._-]+)/i);
    if (shellMatch) {
      shell = shellMatch[1];
      continue;
    }
    const nameMatch = line.match(/^\s*-\s*name:\s*["']?([a-z0-9_]+)/i);
    if (nameMatch && shell) {
      tools.push(`${shell}.${nameMatch[1]}`);
    }
  }
  const registered = tools.filter((t) => t.startsWith('l0.'));
  return registered.length > 0 ? registered : fallback;
}

interface EvidenceBundle {
  refs: string[];
  recallHits: Array<{ id: string; quality_level: string; content: string }>;
  errors: string[];
}

function parseMcpText(result: { content: Array<{ type: string; text?: string }> }): unknown {
  const text = result.content
    .filter((c) => c.type === 'text')
    .map((c) => c.text ?? '')
    .join('');
  return JSON.parse(text);
}

/** 独立取证：unified_search 先检索，再 recall 同一 intent；单步失败 FAIL-OPEN。 */
async function collectEvidence(intent: string): Promise<EvidenceBundle> {
  const refs: string[] = [];
  const recallHits: EvidenceBundle['recallHits'] = [];
  const errors: string[] = [];
  const client = getCognitionMcpClient();

  try {
    const payload = parseMcpText(
      await client.callTool('unified_search', { query: intent, top_k: EVIDENCE_TOP_K }),
    ) as { ok?: boolean; data?: { hits?: Array<Record<string, unknown>> } };
    const hits = payload?.data?.hits ?? [];
    hits.slice(0, EVIDENCE_TOP_K).forEach((hit, index) => {
      const id = String(hit.id ?? hit.doc_id ?? hit.title ?? `hit-${index + 1}`);
      refs.push(`unified_search:${id}`);
    });
  } catch (e) {
    errors.push(`unified_search:${e instanceof Error ? e.message : 'failed'}`);
  }

  try {
    const payload = parseMcpText(
      await client.callTool('recall', {
        context: intent,
        top_k: EVIDENCE_TOP_K,
        min_quality: 'C',
      }),
    ) as {
      memories?: Array<{ id?: string; quality_level?: string; content?: string }>;
      data?: { memories?: Array<{ id?: string; quality_level?: string; content?: string }> };
    };
    const memories = payload?.memories ?? payload?.data?.memories ?? [];
    memories.slice(0, EVIDENCE_TOP_K).forEach((m, index) => {
      const id = String(m.id ?? `memory-${index + 1}`);
      refs.push(`recall:${id}`);
      recallHits.push({
        id,
        quality_level: String(m.quality_level ?? 'C'),
        content: String(m.content ?? ''),
      });
    });
  } catch (e) {
    errors.push(`recall:${e instanceof Error ? e.message : 'failed'}`);
  }

  return { refs, recallHits, errors };
}

/** 从模型输出中提取 JSON 对象（容忍 ```json 围栏与前后废话）。 */
function extractJsonObject(text: string): unknown {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = (fenced ? fenced[1] : text).trim();
  const start = candidate.indexOf('{');
  const end = candidate.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('model_output_no_json');
  return JSON.parse(candidate.slice(start, end + 1));
}

function buildPrompt(
  intent: string,
  contextRefs: string[],
  evidence: EvidenceBundle,
  allowedTools: string[],
  variant: PlanVariant | null,
): string {
  return [
    '你是 DreamBuddy 的规划提案方（side A），只输出一个 JSON 对象，不要任何解释文字。',
    '任务：为一个「方案择优类」意图生成可评估的 PlanCard。',
    '',
    `意图：${intent}`,
    contextRefs.length > 0 ? `上下文引用：${JSON.stringify(contextRefs)}` : '',
    ...buildVariantPromptSection(variant),
    '独立取证结果（只能引用这些 evidence_refs）：',
    evidence.refs.length > 0 ? JSON.stringify(evidence.refs) : '（无，evidence_refs 留空数组）',
    '',
    `plan_steps[].tool 只能从以下已注册工具中选择：${JSON.stringify(allowedTools)}`,
    `validation.evaluator_refs 固定填 ["${DEFAULT_EVALUATOR_REF}"]。`,
    '',
    '输出字段（严格对齐）：',
    '{',
    `  "id": "${PLAN_CARD_ID_PREFIX}<12位小写字母数字>",`,
    '  "intent": "意图摘要（<=500字）",',
    '  "context_refs": ["..."],',
    '  "plan_steps": [{"step": 1, "action": "动作描述", "tool": "l0.x.mcp.y", "args_hint": {}}],',
    '  "evidence_refs": ["..."],',
    '  "risk_flags": ["..."],',
    '  "cost_estimate": {"tokens": 0, "tool_calls": 0},',
    '  "expected_outcome": "可验证的结果描述",',
    '  "validation": {"evaluator_refs": ["45.heuristic@1.0.0"], "acceptance_checks": ["..."]}',
    '}',
  ]
    .filter(Boolean)
    .join('\n');
}

export async function POST(request: NextRequest) {
  let body: {
    intent?: string;
    context_refs?: string[];
    provider?: string;
    model?: string;
    variant?: { focus?: string; seed?: number };
  };
  try {
    body = await request.json();
  } catch {
    return degraded('invalid_json_body');
  }

  const intent = typeof body?.intent === 'string' ? body.intent.trim() : '';
  if (!intent) {
    return degraded('intent_required');
  }
  const contextRefs = Array.isArray(body?.context_refs)
    ? body.context_refs.filter((r): r is string => typeof r === 'string')
    : [];
  const variant = normalizeVariant(body?.variant);

  try {
    const model = resolveAgentModel({ provider: body.provider, model: body.model });
    if (!model) {
      return degraded('model_not_configured');
    }
    const modelName =
      body.model?.trim() ||
      process.env.AGENT_MODEL?.trim() ||
      ((body.provider ?? process.env.AGENT_PROVIDER ?? 'openai-compatible') === 'openai'
        ? 'gpt-4o-mini'
        : 'qwen-plus');

    const allowedTools = loadRegisteredTools();
    const evidence = await collectEvidence(intent);

    const { text } = await generateText({
      model,
      prompt: buildPrompt(intent, contextRefs, evidence, allowedTools, variant),
      temperature: 0.2,
    });

    let parsed: unknown;
    try {
      parsed = extractJsonObject(text);
    } catch (e) {
      return degraded('model_output_unparsable', {
        errors: [e instanceof Error ? e.message : 'model_output_unparsable'],
      });
    }

    // 非合规输出 → 200 degraded + 明细；不抛 500
    const check = validatePlanCard(parsed);
    const card = parsed as Record<string, unknown>;
    const stepTools = Array.isArray(card.plan_steps)
      ? card.plan_steps
          .map((s) => (s && typeof s === 'object' ? (s as { tool?: unknown }).tool : undefined))
          .filter((t): t is string => typeof t === 'string')
      : [];
    const unregistered = stepTools.filter((t) => !allowedTools.includes(t));
    const errors = [...check.errors, ...unregistered.map((t) => `tool_not_registered:${t}`)];

    if (errors.length > 0) {
      return degraded('plancard_invalid', { errors });
    }

    return NextResponse.json({
      ok: true,
      data: {
        // 统一重签 id：同一 intent 多次调用（N-per-side 发散）也保证 card_id 唯一
        plancard: { ...card, id: newPlanCardId() },
        model: modelName,
        evidence_path: 'unified_search+recall',
        variant,
      },
    });
  } catch (e) {
    // FAIL-OPEN：模型调用/网络异常不阻塞编排器
    console.warn('[AgentPlan] degraded:', e instanceof Error ? e.message : e);
    return degraded(e instanceof Error ? e.message : 'agent_plan_failed');
  }
}

export async function GET() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/plan accepts POST only' },
    { status: 405 },
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/plan accepts POST only' },
    { status: 405 },
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/plan accepts POST only' },
    { status: 405 },
  );
}

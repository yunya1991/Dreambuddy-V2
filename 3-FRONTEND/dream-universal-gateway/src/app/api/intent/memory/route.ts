/**
 * Intent Memory API
 * POST /api/intent/memory     — 记录一次识别结果
 * GET  /api/intent/memory     — 查询记忆记录
 * POST /api/intent/memory/feedback — 提交用户反馈
 * POST /api/intent/memory/evolve   — 手动触发自主进化
 * GET  /api/intent/memory/stats    — 获取学习统计
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  recordRecognition,
  recordFeedback,
  getMemoryRecords,
  getMemoryStats,
  getCandidatePatterns,
  getConfidenceAdjustments,
  applyAdjustments,
  adoptCandidate,
} from '@/lib/intent/intent-memory';

// ============================================================
// POST /api/intent/memory — 记录识别 / 反馈 / 进化
// ============================================================

export async function POST(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const action = url.searchParams.get('action');

    if (action === 'feedback') {
      return await handleFeedback(request);
    }
    if (action === 'evolve') {
      return await handleEvolve(request);
    }
    if (action === 'adopt') {
      return await handleAdoptCandidate(request);
    }

    // 默认: 记录识别
    return await handleRecord(request);
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

// ============================================================
// GET /api/intent/memory — 查询记录 / 统计
// ============================================================

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const action = url.searchParams.get('action');

    if (action === 'stats') {
      return NextResponse.json(getMemoryStats());
    }
    if (action === 'candidates') {
      return NextResponse.json({ candidates: getCandidatePatterns() });
    }
    if (action === 'adjustments') {
      return NextResponse.json({ adjustments: getConfidenceAdjustments() });
    }

    // 默认: 查询记录
    const intent = url.searchParams.get('intent') as any;
    const method = url.searchParams.get('method') || undefined;
    const feedback = url.searchParams.get('feedback') as any;
    const session_id = url.searchParams.get('session_id') || undefined;
    const limit = parseInt(url.searchParams.get('limit') || '50', 10);

    const records = getMemoryRecords({
      intent: intent || undefined,
      method,
      feedback,
      session_id,
      limit: Math.min(limit, 200),
    });

    return NextResponse.json({ records, total: records.length });
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

// ============================================================
// 内部 handler
// ============================================================

async function handleRecord(request: NextRequest): Promise<NextResponse> {
  const body = await request.json();
  const {
    input,
    recognized_intent,
    recognized_confidence,
    recognized_method,
    recognized_complexity,
    matched_pattern_id,
    llm_intent,
    llm_confidence,
    routing_chain,
    session_id,
    user_role,
  } = body;

  if (!input || !recognized_intent) {
    return NextResponse.json({ error: 'Missing required fields: input, recognized_intent' }, { status: 400 });
  }

  const recordId = recordRecognition({
    input,
    recognized_intent,
    recognized_confidence: recognized_confidence || 0.5,
    recognized_method: recognized_method || 'rule',
    recognized_complexity: recognized_complexity || 'simple',
    matched_pattern_id,
    llm_intent,
    llm_confidence,
    routing_chain: routing_chain || [],
    session_id: session_id || 'anonymous',
    user_role: user_role || 'FREE',
  });

  return NextResponse.json({ success: true, record_id: recordId });
}

async function handleFeedback(request: NextRequest): Promise<NextResponse> {
  const body = await request.json();
  const { record_id, feedback, corrected_intent } = body;

  if (!record_id || !feedback) {
    return NextResponse.json({ error: 'Missing required fields: record_id, feedback' }, { status: 400 });
  }

  const valid = ['correct', 'incorrect'];
  if (!valid.includes(feedback)) {
    return NextResponse.json({ error: `Invalid feedback. Must be one of: ${valid.join(', ')}` }, { status: 400 });
  }

  const success = recordFeedback(record_id, feedback, corrected_intent);
  return NextResponse.json({ success, record_id });
}

async function handleEvolve(request: NextRequest): Promise<NextResponse> {
  const adjustments = getConfidenceAdjustments();
  const applied = applyAdjustments(adjustments);
  const candidates = getCandidatePatterns();

  return NextResponse.json({
    success: true,
    adjustments_applied: applied ? adjustments.length : 0,
    adjustments,
    candidate_patterns: candidates,
  });
}

async function handleAdoptCandidate(request: NextRequest): Promise<NextResponse> {
  const body = await request.json();
  const { keywords, intent, occurrences, suggested_confidence, suggested_pattern, source } = body;

  if (!keywords || !intent) {
    return NextResponse.json({ error: 'Missing required fields: keywords, intent' }, { status: 400 });
  }

  const success = adoptCandidate({
    keywords,
    intent,
    occurrences: occurrences || 1,
    suggested_confidence: suggested_confidence || 0.60,
    suggested_pattern: suggested_pattern || keywords.join('|'),
    source: source || 'user_adopted',
  });

  return NextResponse.json({ success });
}

/**
 * Intent Analysis API
 * GET /api/intent/analyze/confusion  — 混淆矩阵
 * GET /api/intent/analyze/candidates — 候选新模式
 * GET /api/intent/analyze/trends    — 识别方法趋势
 */

import { NextRequest, NextResponse } from 'next/server';
import { getMemoryStats, getCandidatePatterns } from '@/lib/intent/intent-memory';

export async function GET(request: NextRequest) {
  try {
    const url = new URL(request.url);
    const endpoint = url.pathname.split('/').pop();

    switch (endpoint) {
      case 'confusion': {
        const stats = getMemoryStats();
        return NextResponse.json({
          confusion_matrix: stats.confusion_matrix,
          high_confusion_pairs: findHighConfusionPairs(stats.confusion_matrix),
        });
      }

      case 'candidates': {
        const candidates = getCandidatePatterns();
        return NextResponse.json({ candidates, total: candidates.length });
      }

      case 'trends': {
        const stats = getMemoryStats();
        return NextResponse.json({
          trend: stats.trend,
          method_distribution: stats.method_distribution,
          intent_distribution: stats.intent_distribution,
        });
      }

      default:
        return NextResponse.json({ error: 'Unknown endpoint. Use /confusion, /candidates, or /trends' }, { status: 404 });
    }
  } catch (e) {
    return NextResponse.json({ error: (e as Error).message }, { status: 500 });
  }
}

function findHighConfusionPairs(matrix: Record<string, Record<string, number>>): Array<{
  intent_a: string;
  intent_b: string;
  confusion_count: number;
  percentage: string;
}> {
  const pairs: Array<{ intent_a: string; intent_b: string; confusion_count: number; percentage: string }> = [];

  for (const [llmIntent, ruleIntents] of Object.entries(matrix)) {
    const total = Object.values(ruleIntents).reduce((s, v) => s + v, 0);
    for (const [ruleIntent, count] of Object.entries(ruleIntents)) {
      if (llmIntent !== ruleIntent && count >= 2) {
        const pct = total > 0 ? Math.round((count / total) * 100) : 0;
        pairs.push({
          intent_a: llmIntent,
          intent_b: ruleIntent,
          confusion_count: count,
          percentage: `${pct}%`,
        });
      }
    }
  }

  return pairs.sort((a, b) => b.confusion_count - a.confusion_count);
}

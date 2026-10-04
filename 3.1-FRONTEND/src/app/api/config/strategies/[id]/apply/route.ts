/**
 * POST /api/config/strategies/[id]/apply
 * 应用策略 - 将策略状态改为APPLIED并创建定时任务
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveStrategyApplyRouteUid } from '@/lib/development-route-uids';
import {
  applyStrategyWithTaskOrder,
  resolveStrategyFrequency,
} from '@/lib/strategy-lifecycle-service';
import { createStrategyTaskOrderArtifactWriter } from '@/lib/strategy-artifacts';
import { ARTIFACTS_DIR } from '@/lib/task-manager';
import { syncStrategyToClassic } from '@/lib/classic-system-bridge';

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const uid = await resolveStrategyApplyRouteUid(request);

  try {
    const strategy = await prisma.strategy.findFirst({ where: { id, uid } });
    if (!strategy) {
      return NextResponse.json({ success: false, error: '策略不存在' }, { status: 404 });
    }

    let requestedFrequency: string | null = null;
    try {
      const body = await request.json();
      requestedFrequency = typeof body?.frequency === 'string' ? body.frequency : null;
    } catch {
      requestedFrequency = null;
    }
    const profile = await prisma.userProfile.findUnique({ where: { uid } });
    const frequency = resolveStrategyFrequency({
      requestedFrequency,
      preferredFrequency: profile?.preferredFrequency,
    });

    const result = await applyStrategyWithTaskOrder({
      prisma,
      strategy: {
        ...strategy,
        description: strategy.description ?? null,
        confidence: strategy.confidence ?? null,
        source: strategy.source ?? null,
        rawInput: strategy.rawInput ?? null,
      },
      uid,
      frequency,
      triggerType: 'manual',
      nowIso: new Date().toISOString(),
      artifactWriter: createStrategyTaskOrderArtifactWriter(ARTIFACTS_DIR),
    });

    // ===== 同步策略治理流程到经典系统 =====
    const warnings: string[] = [];
    const classicSync = await syncStrategyToClassic({
      id: strategy.id,
      name: strategy.name,
      description: strategy.description,
      direction: strategy.direction,
      symbol: strategy.symbol,
      tradeType: strategy.tradeType ?? undefined,
      leverage: profile?.leverageMax ?? undefined,
      positionSize: profile?.capitalPercentage ?? undefined,
      frequency,
    });

    if (!classicSync.ok) {
      warnings.push(`经典系统策略同步失败: ${classicSync.error}`);
    }
    if (classicSync.warnings) {
      warnings.push(...classicSync.warnings);
    }

    return NextResponse.json({
      success: true,
      data: result.taskOrder,
      meta: {
        strategy: result.strategy,
        strategyTask: result.strategyTask,
        executionRun: result.executionRun,
        nextExecutionAt: result.nextExecutionAt,
        classic_sync: classicSync.ok ? {
          ok: true,
          trace_id: classicSync.trace_id,
          stages: classicSync.data?.stages,
        } : {
          ok: false,
          trace_id: classicSync.trace_id,
          error: classicSync.error,
        },
      },
      ...(warnings.length > 0 ? { warnings } : {}),
    });
  } catch (error) {
    console.error('应用策略失败:', error);
    return NextResponse.json({ success: false, error: '应用策略失败' }, { status: 500 });
  }
}

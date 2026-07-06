/**
 * 策略设置 API 路由
 * GET    - 获取策略列表(推荐+自定义)
 * POST   - 创建策略
 * PATCH  - 更新策略
 * DELETE - 删除策略
 *
 * 注意: /parse 端点已拆分到 parse/route.ts
 */
import { NextRequest, NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';
import { resolveStrategiesRouteUid } from '@/lib/development-route-uids';
import { createStrategyWithLifecycle } from '@/lib/strategy-lifecycle-service';
import { createStrategyTaskOrderArtifactWriter } from '@/lib/strategy-artifacts';
import { ARTIFACTS_DIR } from '@/lib/task-manager';

// GET /api/config/strategies
export async function GET(request: NextRequest) {
  const uid = await resolveStrategiesRouteUid(request);

  try {
    const strategies = await prisma.strategy.findMany({
      where: { uid },
      include: {
        tasks: true,
        taskOrders: {
          include: {
            strategyTasks: true,
            executionRuns: {
              orderBy: { createdAt: 'desc' },
            },
          },
          orderBy: { appliedAt: 'desc' },
        },
      },
      orderBy: { createdAt: 'desc' },
    });

    // 分类
    const recommended = strategies.filter(s => s.type === 'RECOMMENDED');
    const custom = strategies.filter(s => s.type === 'CUSTOM');
    const applied = strategies.filter(s => s.status === 'APPLIED');

    return NextResponse.json({
      success: true,
      data: { strategies, recommended, custom, applied },
    });
  } catch (error) {
    console.error('获取策略列表失败:', error);
    return NextResponse.json(
      { success: false, error: '获取策略列表失败' },
      { status: 500 }
    );
  }
}

// POST /api/config/strategies - 创建策略(推荐或自定义)
export async function POST(request: NextRequest) {
  const uid = await resolveStrategiesRouteUid(request);

  try {
    const body = await request.json();
    const {
      type,
      name,
      description,
      direction,
      symbol,
      tradeType,
      leverage,
      positionSize,
      stopLoss,
      takeProfit,
      confidence,
      edgeScore,
      regime,
      source,
      rawInput,
      apply,
      autoApply,
      frequency,
    } = body;

    if (!name || !direction) {
      return NextResponse.json(
        { success: false, error: '缺少必填字段: name, direction' },
        { status: 400 }
      );
    }

    const shouldApply = apply === true || autoApply === true;
    const profile = shouldApply
      ? await prisma.userProfile.findUnique({ where: { uid } })
      : null;
    const result = await createStrategyWithLifecycle({
      prisma,
      uid,
      apply: shouldApply,
      requestedFrequency: frequency,
      preferredFrequency: profile?.preferredFrequency,
      nowIso: new Date().toISOString(),
      artifactWriter: shouldApply
        ? createStrategyTaskOrderArtifactWriter(ARTIFACTS_DIR)
        : undefined,
      strategy: {
        type,
        name,
        description,
        direction,
        symbol,
        tradeType,
        leverage,
        positionSize,
        stopLoss,
        takeProfit,
        confidence,
        edgeScore,
        regime,
        source,
        rawInput,
      },
    });

    return NextResponse.json({
      success: true,
      data: shouldApply ? result.taskOrder : result.strategy,
      meta: shouldApply
        ? {
            strategy: result.strategy,
            strategyTask: result.strategyTask,
            executionRun: result.executionRun,
            nextExecutionAt: result.nextExecutionAt,
          }
        : undefined,
    });
  } catch (error) {
    console.error('创建策略失败:', error);
    return NextResponse.json(
      { success: false, error: '创建策略失败' },
      { status: 500 }
    );
  }
}

// PATCH /api/config/strategies - 更新策略
export async function PATCH(request: NextRequest) {
  const uid = await resolveStrategiesRouteUid(request);

  try {
    const body = await request.json();
    const { id, ...updates } = body;

    if (!id) {
      return NextResponse.json(
        { success: false, error: '缺少策略ID' },
        { status: 400 }
      );
    }

    // 验证策略属于当前用户
    const existing = await prisma.strategy.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json(
        { success: false, error: '策略不存在或无权限' },
        { status: 404 }
      );
    }

    const allowedFields = ['name', 'description', 'direction', 'symbol', 'tradeType', 'leverage', 'positionSize', 'stopLoss', 'takeProfit', 'confidence', 'edgeScore', 'status', 'isRead'];
    const updateData: Record<string, unknown> = {};
    for (const field of allowedFields) {
      if (updates[field] !== undefined) updateData[field] = updates[field];
    }

    await prisma.strategy.update({ where: { id }, data: updateData });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('更新策略失败:', error);
    return NextResponse.json(
      { success: false, error: '更新策略失败' },
      { status: 500 }
    );
  }
}

// DELETE /api/config/strategies
export async function DELETE(request: NextRequest) {
  const uid = await resolveStrategiesRouteUid(request);

  try {
    const { searchParams } = new URL(request.url);
    const id = searchParams.get('id');

    if (!id) {
      return NextResponse.json(
        { success: false, error: '缺少策略ID' },
        { status: 400 }
      );
    }

    const existing = await prisma.strategy.findFirst({ where: { id, uid } });
    if (!existing) {
      return NextResponse.json(
        { success: false, error: '策略不存在或无权限' },
        { status: 404 }
      );
    }

    await prisma.strategy.delete({ where: { id } });

    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('删除策略失败:', error);
    return NextResponse.json(
      { success: false, error: '删除策略失败' },
      { status: 500 }
    );
  }
}

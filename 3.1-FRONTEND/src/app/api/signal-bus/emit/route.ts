/**
 * POST /api/signal-bus/emit
 * 通信系统层（36-通信系统层）信号收口入口
 * 依据 SPEC.md v1.0 第 6.1 节（P1：集成健康监控）
 */
import { NextRequest, NextResponse } from 'next/server';
import { emit } from '../../../../../../36-通信系统层/src/bus';
import { startHealthMonitor, getHealthState } from '../../../../../../36-通信系统层/src/health';

// 模块加载时启动健康监控（幂等）
startHealthMonitor();

export async function POST(request: NextRequest) {
  // 内部 Token 鉴权（SPEC 第 9 章）：配置了 SIGNAL_BUS_TOKEN 时强制校验
  const busToken = process.env.SIGNAL_BUS_TOKEN;
  if (busToken) {
    const auth = request.headers.get('authorization');
    if (auth !== `Bearer ${busToken}`) {
      return NextResponse.json(
        { success: false, error: '未授权的信号来源' },
        { status: 401 }
      );
    }
  }

  try {
    const body = await request.json();
    const result = await emit(body);
    return NextResponse.json({ success: true, data: result });
  } catch (error) {
    const message = error instanceof Error ? error.message : '信号处理失败';
    console.error('[signal-bus] emit 失败:', message);
    return NextResponse.json(
      { success: false, error: message },
      { status: 400 }
    );
  }
}

export async function GET() {
  const health = getHealthState();
  return NextResponse.json({
    success: true,
    data: {
      service: 'signal-bus',
      version: '1.1.0',
      spec: '36-通信系统层/SPEC.md',
      hermes: {
        healthy: health.healthy,
        consecutiveFails: health.consecutiveFails,
        lastProbeAt: health.lastProbeAt,
        degradedAt: health.degradedAt,
        recoveredAt: health.recoveredAt,
      },
    },
  });
}

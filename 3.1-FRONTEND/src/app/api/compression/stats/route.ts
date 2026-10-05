/**
 * Compression Stats API — G 层图架构上下文压缩统计
 * GET /api/compression/stats
 *
 * 暴露 compressor-adapter 的真实统计数据与 BAC 会话列表，
 * 供前端 BACTimeline 组件消费（替代硬编码 mock checkpoints）。
 *
 * FAIL-OPEN: 压缩器模块不可用时返回空数据，不抛异常。
 */
import { NextResponse } from 'next/server';
import { getCompressorAdapter } from '@/lib/compressor-adapter';

export const dynamic = 'force-dynamic';

export async function GET() {
  const adapter = getCompressorAdapter();

  // 确保初始化（失败也降级，不阻塞）
  try {
    await adapter.initialize();
  } catch {
    // adapter 内部已降级到 fallback 模式
  }

  const stats = adapter.getStats();
  const health = adapter.health();

  let sessions: unknown[] = [];
  try {
    sessions = await adapter.listSessionMetas();
  } catch {
    sessions = [];
  }

  return NextResponse.json({
    success: true,
    data: {
      stats,
      health,
      sessions,
    },
    timestamp: new Date().toISOString(),
  });
}

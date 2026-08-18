import { NextResponse } from 'next/server';
import { invalidateCache, getArtifactsData } from '@/lib/content.server';

export const dynamic = 'force-dynamic';

/**
 * POST /api/refresh — 手动刷新产物缓存
 * 投递新产物后调用此接口，前端无需重启即可加载新数据
 */
export async function POST() {
  try {
    invalidateCache();
    // 触发一次重新扫描以验证
    const data = getArtifactsData();
    return NextResponse.json({
      ok: true,
      message: 'Cache invalidated and rescanned',
      total: data.total,
      generated_at: data.generated_at,
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, message: 'Refresh failed', error: String(err) },
      { status: 500 }
    );
  }
}

/**
 * GET /api/refresh — 查询缓存状态
 */
export async function GET() {
  try {
    const data = getArtifactsData();
    return NextResponse.json({
      ok: true,
      total: data.total,
      generated_at: data.generated_at,
      statistics: data.statistics,
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: String(err) },
      { status: 500 }
    );
  }
}

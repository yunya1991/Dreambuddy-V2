/**
 * Training Model API — GET 模型状态端点
 * ==========================================
 * SPEC v0.5 §5.3 P2.2
 *
 * GET /api/training/[layer]/model → 返回模型状态 JSON
 *   - weights / step / drift_flag / timestamp / version
 *   - 各层结构不同（S: weights+typeKeywords, G: graph_coverage 等）
 *
 * FAIL-OPEN: 训练循环不可用时返回降级空状态，不抛异常。
 */
import { NextResponse } from 'next/server';
import { getModelSnapshot, type LayerName } from '@/lib/training-loop-registry';

export const dynamic = 'force-dynamic';

const VALID_LAYERS = new Set(['S', 'DSH', 'C', 'G', 'LLM']);

export async function GET(
  request: Request,
  { params }: { params: Promise<{ layer: string }> },
) {
  const { layer: layerRaw } = await params;
  const layer = layerRaw.toUpperCase() as LayerName;

  if (!VALID_LAYERS.has(layer)) {
    return NextResponse.json(
      { success: false, error: `invalid_layer: ${layerRaw}` },
      { status: 400 },
    );
  }

  try {
    const snapshot = getModelSnapshot(layer);
    if (!snapshot) {
      return NextResponse.json({
        success: true,
        data: { layer, step: 0, weights: {}, drift_flag: false, degraded: true },
      });
    }
    return NextResponse.json({ success: true, data: snapshot });
  } catch (e) {
    // FAIL-OPEN
    return NextResponse.json({
      success: true,
      data: { layer, step: 0, weights: {}, drift_flag: false, degraded: true },
    });
  }
}

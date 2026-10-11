/**
 * Training API — 5 层训练循环 HTTP 接口
 * ==========================================
 * 供 34-前端应用训练系统 的 Python 编排层调用。
 *
 * GET  /api/training/[layer]           → 获取桶状态
 * POST /api/training/[layer]            → 添加训练数据或触发训练
 *   body: { action: "add", data: {...} }
 *   body: { action: "train" }
 *
 * layer ∈ S | DSH | C | G | LLM
 *
 * FAIL-OPEN: 训练循环不可用时返回降级数据，不抛异常。
 */
import { NextResponse } from 'next/server';
import {
  getTrainingLoopStatus,
  addTrainingData,
  trainLayer,
  trainIncrementalLayer,
  checkpointLayer,
  restoreLayer,
  type LayerName,
} from '@/lib/training-loop-registry';

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
    const status = getTrainingLoopStatus(layer);
    if (!status) {
      return NextResponse.json({
        success: true,
        data: { layer, bucketCount: 0, bucketThreshold: 0, shouldTrain: false },
      });
    }
    return NextResponse.json({ success: true, data: status });
  } catch (e) {
    // FAIL-OPEN
    return NextResponse.json({
      success: true,
      data: { layer, bucketCount: 0, bucketThreshold: 0, shouldTrain: false, degraded: true },
    });
  }
}

export async function POST(
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

  let body: { action?: string; data?: Record<string, unknown> };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { success: false, error: 'invalid_json_body' },
      { status: 400 },
    );
  }

  const action = body.action || '';

  try {
    if (action === 'add') {
      if (!body.data) {
        return NextResponse.json(
          { success: false, error: 'missing_data' },
          { status: 400 },
        );
      }
      const added = addTrainingData(layer, body.data);
      return NextResponse.json({ success: true, data: { added } });
    }

    if (action === 'train') {
      const result = trainLayer(layer);
      if (result === null) {
        return NextResponse.json({
          success: true,
          data: { trained: false, degraded: true },
        });
      }
      return NextResponse.json({ success: true, data: result });
    }

    // v0.5 P2.1: 增量训练
    if (action === 'incremental') {
      const result = trainIncrementalLayer(layer);
      if (result === null) {
        return NextResponse.json({
          success: true,
          data: { trained: false, degraded: true },
        });
      }
      return NextResponse.json({ success: true, data: result });
    }

    // v0.5 P2.1: 保存模型状态检查点
    if (action === 'checkpoint') {
      const result = checkpointLayer(layer);
      if (result === null) {
        return NextResponse.json({
          success: true,
          data: { checkpointed: false, degraded: true },
        });
      }
      return NextResponse.json({ success: true, data: result });
    }

    // v0.5 P2.1: 恢复模型状态
    if (action === 'restore') {
      const restoreState = body.data;
      if (!restoreState || Object.keys(restoreState).length === 0) {
        return NextResponse.json(
          { success: false, error: 'missing_state_for_restore' },
          { status: 400 },
        );
      }
      const result = restoreLayer(layer, restoreState as Record<string, unknown>);
      if (result === null) {
        return NextResponse.json({
          success: true,
          data: { restored: false, degraded: true },
        });
      }
      return NextResponse.json({ success: true, data: result });
    }

    return NextResponse.json(
      { success: false, error: `unknown_action: ${action}` },
      { status: 400 },
    );
  } catch (e) {
    // FAIL-OPEN
    return NextResponse.json({
      success: true,
      data: { trained: false, degraded: true, error: String(e) },
    });
  }
}

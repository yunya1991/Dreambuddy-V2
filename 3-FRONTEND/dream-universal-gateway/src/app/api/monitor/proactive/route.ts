/**
 * POST /api/monitor/proactive — 主动推送测试端点（Phase 4）
 *
 * 用于测试前端 ProactiveCard 渲染：
 * 调用此端点模拟后台交易/任务/产物事件，事件经 monitorBus 推送至 SSE，
 * 前端 EventSource 接收后转为 chat 系统消息卡片。
 *
 * Body: { event_type: 'trade_alert' | 'task_completed' | 'artifact_synced' | 'intel_ready' | 'risk_alert' }
 */
import { NextRequest, NextResponse } from 'next/server';
import monitorBus from '@/lib/monitor-bus';

export const dynamic = 'force-dynamic';

const PHASE_MAP: Record<string, { phase: string; layer: string; status: string; title: string; desc: string }> = {
  trade_alert: { phase: 'trade_pending', layer: 'workbuddy', status: 'received', title: '交易待确认', desc: 'AI 生成 BTC 做多建议，杠杆 5x，等待用户确认' },
  task_completed: { phase: 'wb_completed', layer: 'workbuddy', status: 'completed', title: '后台任务完成', desc: 'S2 分析报告已生成' },
  artifact_synced: { phase: 'artifact_synced', layer: 'artifact_hub', status: 'completed', title: '产物已同步', desc: '策略产物 S2_ANALYSIS_BTC.json 已同步至产物库' },
  intel_ready: { phase: 'feed_ready', layer: 'workbuddy', status: 'completed', title: '情报就绪', desc: '市场情报 Feed 已准备完成，可查看' },
};

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const eventType = body.event_type || 'trade_alert';
    const mapping = PHASE_MAP[eventType];

    if (!mapping) {
      return NextResponse.json(
        { success: false, error: `Unknown event_type: ${eventType}. Supported: ${Object.keys(PHASE_MAP).join(', ')}` },
        { status: 400 }
      );
    }

    // 模拟 UID（测试用）
    const uid = body.uid || 'test_user';

    // 通过 monitorBus 发射事件
    const event = monitorBus.emitMonitorEvent({
      trace_id: `proactive_${Date.now()}`,
      uid,
      layer: mapping.layer as any,
      phase: mapping.phase as any,
      status: mapping.status as any,
      intent: body.intent || 'deep_analysis',
      message_preview: body.message_preview || mapping.title,
      artifact_file: body.artifact_file || (eventType === 'artifact_synced' ? 'S2_ANALYSIS_BTC.json' : undefined),
      extra: {
        confidence: body.confidence || 0.75,
        ...body.extra,
      },
    });

    return NextResponse.json({
      success: true,
      event_id: event.id,
      event,
      message: `Proactive event "${mapping.title}" emitted. Frontend should receive via SSE and render ProactiveCard in chat.`,
    });
  } catch (err) {
    return NextResponse.json(
      { success: false, error: err instanceof Error ? err.message : 'Unknown error' },
      { status: 500 }
    );
  }
}

/** GET 返回支持的 event_type 列表 */
export async function GET() {
  return NextResponse.json({
    success: true,
    supported_event_types: Object.keys(PHASE_MAP).map(key => ({
      event_type: key,
      ...PHASE_MAP[key],
    })),
    usage: 'POST /api/monitor/proactive with body { event_type, uid?, message_preview?, artifact_file?, confidence? }',
  });
}

/**
 * SSE Stream API — 实时监控事件推送
 * GET /api/monitor/stream?uid=xxx
 *
 * 返回 Content-Type: text/event-stream
 * 心跳: 15s
 * 事件: MonitorEvent JSON
 */
import { NextRequest } from 'next/server';
import monitorBus from '@/lib/monitor-bus';

const HEARTBEAT_INTERVAL_MS = 15_000;

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const uid = searchParams.get('uid') || '';

  const stream = new ReadableStream({
    start(controller) {
      // 注册 SSE 连接
      const connId = monitorBus.registerSSE(uid, controller);

      if (!connId) {
        // 连接数超限，返回降级提示
        controller.enqueue(
          `data: ${JSON.stringify({
            type: 'system',
            message: 'SSE connections limit reached. Please use polling mode (GET /api/monitor/events).',
            poll_interval_ms: 5000,
          })}\n\n`
        );
        controller.close();
        return;
      }

      // 发送连接成功事件
      controller.enqueue(
        `data: ${JSON.stringify({
          type: 'connected',
          conn_id: connId,
          timestamp: new Date().toISOString(),
        })}\n\n`
      );

      // 发送历史事件（最近10条）
      const recentEvents = monitorBus.getRecentEvents({ uid: uid || undefined, limit: 10 });
      for (const event of recentEvents.reverse()) { // 最旧在前
        controller.enqueue(`data: ${JSON.stringify(event)}\n\n`);
      }

      // 心跳
      const heartbeat = setInterval(() => {
        try {
          controller.enqueue(`:heartbeat ${Date.now()}\n\n`);
        } catch {
          clearInterval(heartbeat);
          monitorBus.unregisterSSE(connId);
        }
      }, HEARTBEAT_INTERVAL_MS);

      // 清理
      const cleanup = () => {
        clearInterval(heartbeat);
        monitorBus.unregisterSSE(connId);
      };

      // 请求关闭时清理
      // Note: Next.js API Route 不支持 req.on('close')，
      // 依赖心跳检测和超时清理
    },

    cancel() {
      // 流被消费者取消
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no', // nginx 不缓冲
      'Access-Control-Allow-Origin': '*',
    },
  });
}

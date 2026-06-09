import { encodeSseComment, encodeSseEvent } from '@/lib/realtime-sse';
import { DEBATE_SCRIPT, type Statement } from '@/lib/meeting-types';

export async function GET() {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      try {
        // Send debate statements with progressive delays
        for (let i = 0; i < DEBATE_SCRIPT.length; i++) {
          const stmt: Statement = {
            ...DEBATE_SCRIPT[i],
            timestamp: Date.now(),
          };

          const event = {
            id: `meeting-${i}`,
            channel: 'meeting' as const,
            timestamp: Date.now(),
            type: stmt.type,
            summary: stmt.content,
            data: stmt as unknown as Record<string, unknown>,
          };
          controller.enqueue(encoder.encode(encodeSseEvent(event)));

          // Progressive delay: opening 600ms, rebuttal 400ms, final 300ms
          const delay = stmt.type === 'opening' ? 600 : stmt.type === 'rebuttal' ? 400 : 300;
          await sleep(delay);
        }

        // Send conclusion summary
        const conclusion = {
          type: 'conclusion',
          bias: 0.55,
          confidence: 0.72,
          summary: '综合三阵营辩论：偏向谨慎看多，建议持有现有仓位、降低杠杆至2x、设置移动止损。主要分歧在宏观风险认知。',
          actionable: [
            '仓位: 维持现有仓位，不加仓',
            '杠杆: 从3x降至2x',
            '保护: 设置BTC 82000移动止损',
            '监控: A6重点关注FOMC决议影响',
          ],
          timestamp: Date.now(),
        };
        controller.enqueue(
          encoder.encode(
            encodeSseEvent({
              id: `meeting-${DEBATE_SCRIPT.length}`,
              channel: 'meeting',
              timestamp: Date.now(),
              type: conclusion.type,
              summary: conclusion.summary,
              data: conclusion as unknown as Record<string, unknown>,
            }),
          ),
        );

        // Send done signal
        controller.enqueue(encoder.encode(encodeSseComment('done')));
        controller.close();
      } catch (err) {
        controller.error(err);
      }
    },
  });

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  });
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

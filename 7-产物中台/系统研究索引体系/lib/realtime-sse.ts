import { getRealtimeHub } from "./realtime-hub.ts";
import type { RealtimeChannel, RealtimeEvent } from "./types.ts";

export function encodeSseEvent(
  event: RealtimeEvent,
  options?: { eventName?: string | null },
) {
  const eventName =
    options && "eventName" in options ? options.eventName : "realtime";
  const eventLine = eventName ? `event: ${eventName}\n` : "";
  return `id: ${event.id}\n${eventLine}data: ${JSON.stringify(event)}\n\n`;
}

export function encodeSseComment(comment: string) {
  return `: ${comment}\n\n`;
}

export function createRealtimeStream(channel: RealtimeChannel) {
  const hub = getRealtimeHub();
  const encoder = new TextEncoder();

  let unsubscribe: (() => void) | null = null;
  let timer: ReturnType<typeof setInterval> | null = null;

  return new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode(encodeSseComment("connected")));

      for (const event of hub.getRecentEvents(channel)) {
        controller.enqueue(
          encoder.encode(encodeSseEvent(event, { eventName: null })),
        );
        controller.enqueue(encoder.encode(encodeSseEvent(event)));
      }

      unsubscribe = hub.subscribe(channel, (event) => {
        controller.enqueue(
          encoder.encode(encodeSseEvent(event, { eventName: null })),
        );
        controller.enqueue(encoder.encode(encodeSseEvent(event)));
      });

      timer = setInterval(() => {
        controller.enqueue(encoder.encode(encodeSseComment("keepalive")));
      }, 15000);
    },
    cancel() {
      if (timer) {
        clearInterval(timer);
      }
      if (unsubscribe) {
        unsubscribe();
      }
    },
  });
}

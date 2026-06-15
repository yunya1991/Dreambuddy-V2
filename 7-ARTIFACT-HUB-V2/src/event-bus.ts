import type { ServerResponse } from "node:http";

export interface SseEvent {
  type: string;
  payload: unknown;
  ts: number;
}

export class EventBus {
  private readonly subs = new Map<string, Set<ServerResponse>>();

  subscribe(traceId: string, res: ServerResponse): void {
    const set = this.subs.get(traceId) ?? new Set<ServerResponse>();
    set.add(res);
    this.subs.set(traceId, set);

    res.on("close", () => {
      const s = this.subs.get(traceId);
      if (!s) return;
      s.delete(res);
      if (s.size === 0) this.subs.delete(traceId);
    });
  }

  publish(traceId: string, event: SseEvent): void {
    const set = this.subs.get(traceId);
    if (!set) return;
    const data = `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
    for (const res of set) res.write(data);
  }
}


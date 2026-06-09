import { randomUUID } from "node:crypto";
import { EventEmitter } from "node:events";
import type {
  RealtimeChannel,
  RealtimeEvent,
  RealtimeEventPayload,
} from "./types.ts";

type Listener = (event: RealtimeEvent) => void;

export function createRealtimeHub(options?: { historyLimit?: number }) {
  const historyLimit = options?.historyLimit ?? 20;
  const emitter = new EventEmitter();
  const history = new Map<RealtimeChannel, RealtimeEvent[]>();

  function publish(
    channel: RealtimeChannel,
    payload: RealtimeEventPayload,
  ): RealtimeEvent {
    const event: RealtimeEvent = {
      id: randomUUID(),
      channel,
      timestamp: Date.now(),
      ...payload,
    };
    const next = [...(history.get(channel) ?? []), event].slice(-historyLimit);
    history.set(channel, next);
    emitter.emit(channel, event);
    return event;
  }

  function subscribe(channel: RealtimeChannel, listener: Listener) {
    emitter.on(channel, listener);
    return () => emitter.off(channel, listener);
  }

  function getRecentEvents(channel: RealtimeChannel) {
    return [...(history.get(channel) ?? [])];
  }

  return { publish, subscribe, getRecentEvents };
}

let singletonHub: ReturnType<typeof createRealtimeHub> | null = null;

export function getRealtimeHub() {
  if (!singletonHub) {
    singletonHub = createRealtimeHub();
  }
  return singletonHub;
}

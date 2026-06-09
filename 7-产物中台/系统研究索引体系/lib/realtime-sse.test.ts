import test from "node:test";
import assert from "node:assert/strict";
import { getRealtimeHub } from "./realtime-hub.ts";
import {
  createRealtimeStream,
  encodeSseComment,
  encodeSseEvent,
} from "./realtime-sse.ts";

test("encodeSseEvent serializes a JSON payload using SSE data lines", () => {
  const chunk = encodeSseEvent({
    id: "evt-1",
    channel: "dream-agent",
    type: "request.started",
    summary: "start",
    timestamp: 1,
  });

  assert.equal(
    chunk,
    'id: evt-1\nevent: realtime\ndata: {"id":"evt-1","channel":"dream-agent","type":"request.started","summary":"start","timestamp":1}\n\n',
  );
});

test("encodeSseComment emits keepalive comment frames", () => {
  assert.equal(encodeSseComment("ping"), ": ping\n\n");
});

test("encodeSseEvent can serialize a default message frame without an event name", () => {
  const chunk = encodeSseEvent(
    {
      id: "evt-2",
      channel: "dream-agent",
      type: "request.completed",
      summary: "done",
      timestamp: 2,
    },
    { eventName: null },
  );

  assert.equal(
    chunk,
    'id: evt-2\ndata: {"id":"evt-2","channel":"dream-agent","type":"request.completed","summary":"done","timestamp":2}\n\n',
  );
});

test("createRealtimeStream emits an initial visible frame immediately after connection", async () => {
  const stream = createRealtimeStream("system");
  const reader = stream.getReader();
  const decoder = new TextDecoder();

  const firstChunk = await reader.read();

  assert.equal(firstChunk.done, false);
  assert.equal(decoder.decode(firstChunk.value), ": connected\n\n");

  await reader.cancel();
});

test("createRealtimeStream emits both message and realtime frames for the same event", async () => {
  const stream = createRealtimeStream("system");
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  const hub = getRealtimeHub();

  await reader.read();

  const published = hub.publish("system", {
    type: "request.started",
    summary: "compat-check",
  });

  const nextChunk = await reader.read();
  const nextNextChunk = await reader.read();

  assert.equal(
    decoder.decode(nextChunk.value),
    `id: ${published.id}\ndata: ${JSON.stringify(published)}\n\n`,
  );
  assert.equal(
    decoder.decode(nextNextChunk.value),
    `id: ${published.id}\nevent: realtime\ndata: ${JSON.stringify(published)}\n\n`,
  );

  await reader.cancel();
});

import test from "node:test";
import assert from "node:assert/strict";
import { invokeDreamAgent } from "./dream-agent-gateway.ts";
import { getRealtimeHub } from "./realtime-hub.ts";

test("invokeDreamAgent proxies backend success and emits realtime lifecycle events", async () => {
  const originalFetch = global.fetch;
  const events: string[] = [];
  const unsubscribe = getRealtimeHub().subscribe("dream-agent", (event) => {
    events.push(event.type);
  });

  global.fetch = async () =>
    new Response(
      JSON.stringify({ success: true, response: "hello" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ) as Response;

  const result = await invokeDreamAgent({
    user_input: "hi",
    llm_config: { provider: "openai", model: "gpt-4", apiKey: "x", apiBase: "" },
  });

  assert.equal(result.success, true);
  assert.equal(result.response, "hello");
  assert.deepEqual(events, ["request.queued", "request.started", "request.completed"]);

  unsubscribe();
  global.fetch = originalFetch;
});

test("invokeDreamAgent emits failed event when backend request fails", async () => {
  const originalFetch = global.fetch;
  const events: string[] = [];
  const unsubscribe = getRealtimeHub().subscribe("dream-agent", (event) => {
    events.push(event.type);
  });

  global.fetch = async () =>
    new Response("boom", { status: 502, statusText: "Bad Gateway" }) as Response;

  await assert.rejects(
    () =>
      invokeDreamAgent({
        user_input: "hi",
        llm_config: { provider: "openai", model: "gpt-4", apiKey: "x", apiBase: "" },
      }),
    /Bad Gateway/,
  );

  assert.deepEqual(events, ["request.queued", "request.started", "request.failed"]);

  unsubscribe();
  global.fetch = originalFetch;
});

test("invokeDreamAgent emits failed event when backend fetch throws a network error", async () => {
  const originalFetch = global.fetch;
  const events: string[] = [];
  const unsubscribe = getRealtimeHub().subscribe("dream-agent", (event) => {
    events.push(event.type);
  });

  global.fetch = async () => {
    throw new Error("connect ECONNREFUSED");
  };

  await assert.rejects(
    () =>
      invokeDreamAgent({
        user_input: "hi",
        llm_config: { provider: "openai", model: "gpt-4", apiKey: "x", apiBase: "" },
      }),
    /ECONNREFUSED/,
  );

  assert.deepEqual(events, ["request.queued", "request.started", "request.failed"]);

  unsubscribe();
  global.fetch = originalFetch;
});

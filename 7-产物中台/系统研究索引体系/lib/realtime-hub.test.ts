import test from "node:test";
import assert from "node:assert/strict";
import { createRealtimeHub } from "./realtime-hub.ts";

test("RealtimeHub publishes events only to the matching channel and keeps recent history", () => {
  const hub = createRealtimeHub({ historyLimit: 3 });
  const received: string[] = [];

  const unsubscribe = hub.subscribe("dream-agent", (event) => {
    received.push(event.type);
  });

  hub.publish("dream-agent", { type: "request.started", summary: "start" });
  hub.publish("meeting", { type: "meeting.started", summary: "ignore" });
  hub.publish("dream-agent", { type: "request.completed", summary: "done" });

  assert.deepEqual(received, ["request.started", "request.completed"]);
  assert.deepEqual(
    hub.getRecentEvents("dream-agent").map((event) => event.type),
    ["request.started", "request.completed"],
  );

  unsubscribe();
});

test("RealtimeHub trims old history entries once the channel reaches its limit", () => {
  const hub = createRealtimeHub({ historyLimit: 2 });

  hub.publish("dream-agent", { type: "first", summary: "1" });
  hub.publish("dream-agent", { type: "second", summary: "2" });
  hub.publish("dream-agent", { type: "third", summary: "3" });

  assert.deepEqual(
    hub.getRecentEvents("dream-agent").map((event) => event.type),
    ["second", "third"],
  );
});

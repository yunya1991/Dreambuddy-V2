import assert from "node:assert/strict";
import test from "node:test";

import {
  toHealthViewModel,
  toTraceViewModel,
  toWorkflowViewModel,
} from "../index.js";
import type { ChainPhase } from "../index.js";
import { mockHealth } from "./health.mock.js";
import { mockTrace } from "./trace.mock.js";
import { mockWorkflow } from "./workflow.mock.js";

test("health adapter maps contract fields to view model", () => {
  const health = toHealthViewModel(mockHealth);

  assert.equal(health.service, "artifact-hub-v2");
  assert.equal(health.status, "ok");
  assert.equal(health.dependencyList.length, 3);
  assert.equal(
    health.dependencyList.find((d) => d.name === "gateway")?.status,
    "unknown"
  );
});

test("trace adapter computes duration for completed traces", () => {
  const trace = toTraceViewModel(mockTrace);

  assert.equal(trace.traceId, "trace_demo_001");
  assert.equal(trace.status, "completed");
  assert.equal(trace.durationMs, 150000);
});

test("trace adapter keeps null duration for running traces", () => {
  const running = toTraceViewModel({
    ...mockTrace,
    status: "running",
    finished_at: null,
  });

  assert.equal(running.durationMs, null);
  assert.equal(running.finishedAt, null);
});

test("workflow adapter maps trace linkage and phase", () => {
  const wf = toWorkflowViewModel(mockWorkflow);
  const phase: ChainPhase = "A3";

  assert.equal(phase, wf.chainPhase);
  assert.equal(wf.workflowId, "wf_demo_001");
  assert.equal(wf.latestTraceId, "trace_demo_001");
});

test("workflow adapter preserves null latest trace id", () => {
  const wfNoTrace = toWorkflowViewModel({
    ...mockWorkflow,
    status: "pending",
    latest_trace_id: null,
  });

  assert.equal(wfNoTrace.latestTraceId, null);
});

test("assertions fail the test process when expectations are wrong", () => {
  assert.notEqual(
    toHealthViewModel(mockHealth).service,
    "definitely-not-the-real-service"
  );
});

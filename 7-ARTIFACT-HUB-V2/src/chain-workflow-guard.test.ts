import assert from "node:assert/strict";
import { test } from "node:test";
import {
  isLegacyChain,
  isTradingV2,
  normalizeWorkflowType,
  groupByWorkflowType,
} from "./chain-workflow-guard.js";
import type { Artifact } from "./types.js";

test("isLegacyChain returns true for legacy_chain", () => {
  assert.equal(isLegacyChain("legacy_chain"), true);
});

test("isLegacyChain returns true for undefined (backward compat)", () => {
  assert.equal(isLegacyChain(undefined), true);
});

test("isLegacyChain returns true for empty string (backward compat)", () => {
  assert.equal(isLegacyChain(""), true);
});

test("isLegacyChain returns false for trading_v2", () => {
  assert.equal(isLegacyChain("trading_v2"), false);
});

test("isTradingV2 returns true for trading_v2", () => {
  assert.equal(isTradingV2("trading_v2"), true);
});

test("isTradingV2 returns false for legacy_chain", () => {
  assert.equal(isTradingV2("legacy_chain"), false);
});

test("isTradingV2 returns false for undefined", () => {
  assert.equal(isTradingV2(undefined), false);
});

test("normalizeWorkflowType returns legacy_chain for unknown values", () => {
  assert.equal(normalizeWorkflowType(undefined), "legacy_chain");
  assert.equal(normalizeWorkflowType(""), "legacy_chain");
  assert.equal(normalizeWorkflowType("unknown_type"), "legacy_chain");
});

test("normalizeWorkflowType returns trading_v2 for trading_v2", () => {
  assert.equal(normalizeWorkflowType("trading_v2"), "trading_v2");
});

test("groupByWorkflowType splits artifacts into two buckets", () => {
  const artifacts: Artifact[] = [
    {
      artifact_id: "a1",
      title: "t1",
      department: "trading",
      category: "cat",
      type: "trading",
      chain_phase: "A3",
      workflow_id: "w1",
      workflow_type: "legacy_chain",
      trace_id: "tr1",
      status: "completed",
      relative_path: "/a/b",
      created_at: "2026-01-01T00:00:00Z",
    },
    {
      artifact_id: "a2",
      title: "t2",
      department: "trading",
      category: "cat",
      type: "trading",
      chain_phase: "",
      workflow_id: "w2",
      workflow_type: "trading_v2",
      trace_id: "tr2",
      status: "completed",
      relative_path: "/a/c",
      created_at: "2026-01-01T00:00:00Z",
    },
  ];

  const groups = groupByWorkflowType(artifacts);
  assert.equal(groups.legacy_chain.length, 1);
  assert.equal(groups.trading_v2.length, 1);
  assert.equal(groups.legacy_chain[0].artifact_id, "a1");
  assert.equal(groups.trading_v2[0].artifact_id, "a2");
});

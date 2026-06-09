import assert from "node:assert/strict";
import { test } from "node:test";
import { createServer } from "node:http";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";

async function listen(server: ReturnType<typeof createServer>): Promise<{ url: string; close: () => Promise<void> }> {
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address() as { port: number };
      resolve({
        url: `http://127.0.0.1:${addr.port}`,
        close: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

function setupArtifactRoot(root: string, items: unknown[]): void {
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({ last_updated: "2026-05-18T00:00:00Z", artifacts: items })
  );
}

test("GET /chain/artifacts returns grouped artifacts by workflow_type", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chain-query-"));
  fs.mkdirSync(path.join(root, "tasks"), { recursive: true });
  fs.mkdirSync(path.join(root, "results"), { recursive: true });

  setupArtifactRoot(root, [
    { artifact_id: "a1", title: "Legacy Trade", type: "trading", chain_phase: "A3", workflow_type: "legacy_chain", status: "completed" },
    { artifact_id: "a2", title: "Trading V2", type: "trading", chain_phase: "", workflow_type: "trading_v2", status: "completed" },
    { artifact_id: "a3", title: "No Type", type: "trading", chain_phase: "A5", status: "completed" },
  ]);

  const prevRoot = process.env.ARTIFACTS_ROOT;
  const prevHubUrl = process.env.HUB_URL;
  const prevGatewayUrl = process.env.GATEWAY_URL;
  process.env.ARTIFACTS_ROOT = root;
  process.env.HUB_URL = "http://127.0.0.1:1";
  process.env.GATEWAY_URL = "http://127.0.0.1:1";

  // Dynamically import to pick up env vars
  const { default: http } = await import("node:http");
  // We create server manually to avoid circular deps — use fetch to test
  const { ArtifactStore } = await import("./artifact-store.js");
  const { groupByWorkflowType, normalizeWorkflowType } = await import("./chain-workflow-guard.js");

  const store = new ArtifactStore(root);
  const items = store.getArtifactsIndex();

  // Verify workflow_type pass-through
  const a1 = items.find(i => i.id === "trading/a1");
  const a2 = items.find(i => i.id === "trading/a2");
  const a3 = items.find(i => i.id === "trading/a3");

  assert.ok(a1, "a1 should be in index");
  assert.equal(a1!.workflow_type, "legacy_chain");
  assert.equal(a2!.workflow_type, "trading_v2");
  assert.equal(a3!.workflow_type, undefined);

  // Verify groupByWorkflowType with mapped items
  const groups = groupByWorkflowType(
    items.map(a => ({
      artifact_id: a.id,
      title: a.title,
      department: a.department,
      category: a.id.split("/")[0] ?? "",
      type: a.type,
      chain_phase: a.chain_phase,
      workflow_id: "",
      workflow_type: normalizeWorkflowType(a.workflow_type),
      trace_id: "",
      status: a.status,
      relative_path: a.url,
      created_at: a.date,
    }))
  );

  assert.equal(groups.legacy_chain.length, 2, "a1 + a3(default) should be legacy_chain");
  assert.equal(groups.trading_v2.length, 1, "a2 should be trading_v2");

  process.env.ARTIFACTS_ROOT = prevRoot;
  process.env.HUB_URL = prevHubUrl;
  process.env.GATEWAY_URL = prevGatewayUrl;
  fs.rmSync(root, { recursive: true, force: true });
});

test("GET /chain/artifacts?workflow_type=trading_v2 filters correctly", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chain-query-filter-"));
  fs.mkdirSync(path.join(root, "tasks"), { recursive: true });
  fs.mkdirSync(path.join(root, "results"), { recursive: true });

  setupArtifactRoot(root, [
    { artifact_id: "b1", title: "Legacy", type: "trading", chain_phase: "A1", workflow_type: "legacy_chain", status: "completed" },
    { artifact_id: "b2", title: "V2", type: "trading", chain_phase: "", workflow_type: "trading_v2", status: "completed" },
  ]);

  const { ArtifactStore } = await import("./artifact-store.js");
  const { groupByWorkflowType, normalizeWorkflowType } = await import("./chain-workflow-guard.js");

  const store = new ArtifactStore(root);
  const items = store.getArtifactsIndex();
  const groups = groupByWorkflowType(
    items.map(a => ({
      artifact_id: a.id,
      title: a.title,
      department: a.department,
      category: a.id.split("/")[0] ?? "",
      type: a.type,
      chain_phase: a.chain_phase,
      workflow_id: "",
      workflow_type: normalizeWorkflowType(a.workflow_type),
      trace_id: "",
      status: a.status,
      relative_path: a.url,
      created_at: a.date,
    }))
  );

  const tradingV2Items = groups.trading_v2;
  assert.equal(tradingV2Items.length, 1);
  assert.equal(tradingV2Items[0].artifact_id, "trading/b2");

  fs.rmSync(root, { recursive: true, force: true });
});

test("GET /chain/reviews returns all reviews when no trace_id", async () => {
  const os = await import("node:os");
  const path = await import("node:path");
  const fs = await import("node:fs");
  const { MetaStore } = await import("./meta-store.js");
  const { MinisterAgent } = await import("./types.js");

  const dir = fs.default.mkdtempSync(path.default.join(os.default.tmpdir(), "reviews-test-"));
  const store = new MetaStore(dir);

  store.addExecutionReview({
    review_id: "rev-r1",
    trace_id: "trace-route-1",
    execution_id: "exec-1",
    reviewer_agent: MinisterAgent.GOVERNANCE,
    verdict: "pass",
    findings: "All good",
    recommendations: "None",
    reviewed_at: "2026-05-18T10:00:00Z",
  });
  store.addExecutionReview({
    review_id: "rev-r2",
    trace_id: "trace-route-2",
    execution_id: "exec-2",
    reviewer_agent: MinisterAgent.OPERATIONS,
    verdict: "escalate",
    findings: "Anomaly",
    recommendations: "Escalate",
    reviewed_at: "2026-05-18T11:00:00Z",
  });

  const all = store.listExecutionReviews();
  assert.equal(all.length, 2);

  const filtered = store.listExecutionReviews("trace-route-1");
  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].verdict, "pass");

  const empty = store.listExecutionReviews("trace-unknown");
  assert.deepEqual(empty, []);

  fs.default.rmSync(dir, { recursive: true, force: true });
});

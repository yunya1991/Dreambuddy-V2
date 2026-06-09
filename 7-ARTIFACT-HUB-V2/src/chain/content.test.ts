import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ChainContentStore } from "./content.js";

test("ChainContentStore groups artifacts by workflow type and surfaces anomalies", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "chain-content-"));
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });
  fs.mkdirSync(path.join(root, "tasks"), { recursive: true });
  fs.mkdirSync(path.join(root, "results"), { recursive: true });

  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "A1",
          workflow_type: "legacy_chain",
          chain_phase: "A3",
          status: "completed"
        },
        {
          artifact_id: "trading/a2",
          title: "A2",
          workflow_type: "trading_v2",
          chain_phase: "A5",
          status: "processing"
        }
      ]
    })
  );
  fs.writeFileSync(
    path.join(root, "tasks", "task_a2.json"),
    JSON.stringify({
      task_id: "task_a2",
      trace_id: "trace_a2",
      routing_plan: { mode: "RUN_CHAIN" }
    })
  );

  const store = new ChainContentStore(root);
  const overview = store.getOverview();
  assert.equal(overview.workflowGroups.legacy_chain.length, 1);
  assert.equal(overview.workflowGroups.trading_v2.length, 1);
  assert.ok(
    overview.anomalies.some((item: { kind: string }) => item.kind === "missing_result")
  );

  fs.rmSync(root, { recursive: true, force: true });
});

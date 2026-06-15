import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { FeedContentStore } from "./content.js";

test("FeedContentStore lists artifacts, computes stats, and reads markdown detail", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-content-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "Alpha Report",
          filename: "a1.md",
          type: "report",
          status: "completed",
          tags: ["macro", "risk"],
          chain_phase: "A3"
        }
      ]
    })
  );

  fs.writeFileSync(
    path.join(tradingDir, "a1.md"),
    `---
title: Alpha Report
department: trading
type: report
status: completed
tags:
  - macro
  - risk
date: 2026-05-20T10:00:00Z
---

# Alpha Report

This is the markdown body.
`
  );

  const store = new FeedContentStore(root);
  const list = store.listArtifacts();
  assert.equal(list.length, 1);
  assert.equal(list[0].url, "/feed/trading/a1");
  assert.equal(list[0].category, "trading");
  assert.equal(list[0].artifactId, "a1");

  const stats = store.getStats();
  assert.equal(stats.total, 1);
  assert.equal(stats.byDepartment.trading, 1);
  assert.equal(stats.byChainPhase.A3, 1);

  const detail = store.getArtifactDetail("trading", "a1");
  assert.ok(detail);
  assert.equal(detail?.title, "Alpha Report");
  assert.match(detail?.content ?? "", /This is the markdown body/);

  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore reads detail from index metadata when real artifacts only provide index.json", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-content-real-shape-"));
  const researchDir = path.join(root, "research");
  fs.mkdirSync(researchDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-19T10:00:00Z",
      artifacts: [
        {
          artifact_id: "intel-report-001",
          title: "BTC市场情报分析报告",
          type: "report",
          date: "2026-05-19T09:00:00Z",
          status: "completed",
          chain_phase: "A1",
          workflow_type: "trading_v2",
          tags: "bitcoin market-analysis"
        }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const detail = store.getArtifactDetail("research", "intel-report-001");

  assert.ok(detail);
  assert.equal(detail?.title, "BTC市场情报分析报告");
  assert.equal(detail?.rawPath, path.join(researchDir, "index.json"));
  assert.match(detail?.content ?? "", /BTC市场情报分析报告/);
  assert.match(detail?.content ?? "", /Tags: bitcoin, market-analysis/);

  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore filters artifacts by department, status, and chain phase", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-filters-"));
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "trading/a1", title: "A1", status: "completed", type: "report", chain_phase: "A3", tags: ["a3"] },
        { artifact_id: "trading/a2", title: "A2", status: "failed", type: "report", chain_phase: "A5", tags: ["a5"] }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const items = store.listArtifacts({ department: "trading", status: "completed", chainPhase: "A3" });
  assert.equal(items.length, 1);
  assert.equal(items[0].artifactId, "a1");
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore paginates list results", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-page-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "research/r1", title: "R1" },
        { artifact_id: "research/r2", title: "R2" },
        { artifact_id: "research/r3", title: "R3" }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const page = store.listArtifacts({ limit: 2, offset: 1 });
  assert.deepEqual(page.map((item) => item.artifactId), ["r2", "r3"]);
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore exposes governance context on detail records", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-governance-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/a1",
          title: "A1",
          workflow_id: "wf-1",
          workflow_type: "trading_v2",
          trace_id: "trace-1",
          chain_phase: "A4"
        }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const detail = store.getArtifactDetail("trading", "a1");
  assert.ok(detail);
  assert.deepEqual(detail?.governanceContext, {
    workflowId: "wf-1",
    workflowType: "trading_v2",
    traceId: "trace-1",
    chainPhase: "A4"
  });
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore maps current sources to Chinese P0 departments", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-p0-departments-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.mkdirSync(path.join(root, "governance"), { recursive: true });
  fs.mkdirSync(path.join(root, "trading"), { recursive: true });

  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [
        { artifact_id: "research/intel-a1", title: "Intel", chain_phase: "A1", type: "report", status: "completed", tags: ["market-analysis"] },
        { artifact_id: "research/dream-note-001", title: "Dream Note", chain_phase: "A3", type: "note", status: "completed", tags: ["dream", "oneirology"] }
      ]
    })
  );
  fs.writeFileSync(
    path.join(root, "governance", "index.json"),
    JSON.stringify({ last_updated: "2026-05-20T00:00:00Z", artifacts: [{ artifact_id: "governance/audit-001", title: "Audit", status: "completed" }] })
  );
  fs.writeFileSync(
    path.join(root, "trading", "index.json"),
    JSON.stringify({ last_updated: "2026-05-20T00:00:00Z", artifacts: [{ artifact_id: "trading/order-001", title: "Order", chain_phase: "A9", status: "completed" }] })
  );

  const store = new FeedContentStore(root);
  const all = store.listArtifacts();
  assert.equal(all.find((item) => item.id === "research/dream-note-001")?.departmentLabel, "做梦部");
  assert.equal(all.find((item) => item.id === "research/intel-a1")?.departmentLabel, "知识库");
  assert.equal(all.find((item) => item.id === "governance/audit-001")?.departmentLabel, "治理部");
  assert.equal(all.find((item) => item.id === "trading/order-001")?.departmentLabel, "交易部");
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore exposes fixed A0-A9 summary with zero-count stages", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-p0-stages-"));
  fs.mkdirSync(path.join(root, "research"), { recursive: true });
  fs.writeFileSync(
    path.join(root, "research", "index.json"),
    JSON.stringify({
      last_updated: "2026-05-20T00:00:00Z",
      artifacts: [{ artifact_id: "research/intel-a1", title: "Intel", chain_phase: "A1", status: "completed" }]
    })
  );

  const store = new FeedContentStore(root);
  const summary = store.getHomepageSummary();
  assert.deepEqual(summary.stageEntries.map((item) => item.label), ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"]);
  assert.equal(summary.stageEntries.find((item) => item.label === "A1")?.count, 1);
  assert.equal(summary.stageEntries.find((item) => item.label === "A0")?.count, 0);
  fs.rmSync(root, { recursive: true, force: true });
});

test("FeedContentStore keeps 做梦部 non-empty for current real research data via temporary A3 strategy mapping", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "feed-real-dream-fallback-"));
  const researchDir = path.join(root, "research");
  fs.mkdirSync(researchDir, { recursive: true });

  fs.writeFileSync(
    path.join(researchDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-05-19T10:00:00Z",
      artifacts: [
        {
          artifact_id: "intel-report-001",
          title: "BTC市场情报分析报告",
          type: "report",
          date: "2026-05-19T09:00:00Z",
          status: "completed",
          chain_phase: "A1",
          workflow_type: "trading_v2",
          tags: "bitcoin market-analysis"
        },
        {
          artifact_id: "strategy-a3-002",
          title: "ETH趋势跟踪策略",
          type: "strategy",
          date: "2026-05-18T15:00:00Z",
          status: "completed",
          chain_phase: "A3",
          workflow_type: "trading_v2",
          tags: "ethereum trend strategy"
        }
      ]
    })
  );

  const store = new FeedContentStore(root);
  const all = store.listArtifacts();
  const dreamItems = store.listArtifacts({ department: "做梦部" });
  const summary = store.getHomepageSummary();

  assert.equal(all.find((item) => item.id === "research/intel-report-001")?.departmentLabel, "知识库");
  assert.equal(all.find((item) => item.id === "research/strategy-a3-002")?.departmentLabel, "做梦部");
  assert.deepEqual(dreamItems.map((item) => item.artifactId), ["strategy-a3-002"]);
  assert.equal(summary.departmentEntries.find((item) => item.label === "做梦部")?.count, 1);

  fs.rmSync(root, { recursive: true, force: true });
});

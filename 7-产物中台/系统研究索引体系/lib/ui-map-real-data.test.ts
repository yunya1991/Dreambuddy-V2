import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { getUIMapScenario } from "../app/ui-map/ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "../app/ui-map/ui-map-shell-view-model.ts";
import {
  buildResearchChainUIMapOverride,
  buildSystemResearchUIMapOverride,
  buildOperationsUIMapOverride,
} from "./ui-map-real-data.ts";
import { createRealtimeHub, getRealtimeHub } from "./realtime-hub.ts";
import type { RealtimeChannel } from "./types.ts";

test("buildSystemResearchUIMapOverride summarizes real artifact data for ui-map", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-"));
  const tradingDir = path.join(root, "trading");
  const knowledgeDir = path.join(root, "knowledge");

  fs.mkdirSync(tradingDir, { recursive: true });
  fs.mkdirSync(knowledgeDir, { recursive: true });

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-06-09T08:00:00Z",
      artifacts: [
        {
          artifact_id: "trading/t-001",
          title: "Trading Artifact",
          department: "trading",
          type: "strategy",
          status: "completed",
          date: "2026-06-09T08:00:00Z",
          chain_phase: "A4",
          tags: ["signal"],
          filename: "trading-artifact.md",
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(tradingDir, "trading-artifact.md"), "# Trading");

  fs.writeFileSync(
    path.join(knowledgeDir, "index.json"),
    JSON.stringify({
      last_updated: "2026-06-08T20:00:00Z",
      artifacts: [
        {
          artifact_id: "knowledge/k-001",
          title: "Knowledge Artifact",
          department: "knowledge",
          type: "research",
          status: "completed",
          date: "2026-06-08T20:00:00Z",
          chain_phase: "A6",
          tags: ["summary"],
          filename: "knowledge-artifact.md",
        },
      ],
    }),
  );
  fs.writeFileSync(path.join(knowledgeDir, "knowledge-artifact.md"), "# Knowledge");

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildSystemResearchUIMapOverride();

  assert.deepEqual(override, {
    description: "已接入真实系统研究数据：2 个产物，覆盖 2 个部门、2 个阶段。",
    bullets: [
      "系统研究结果沉淀：2 个真实产物",
      "关系链路覆盖：2 条关系，2 个阶段",
      "平台能力覆盖：2 个部门",
    ],
  });

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("ui-map shell view model keeps fixture content when no real-data override is provided", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    systemResearch: null,
  });

  assert.equal(viewModel.indexFoundation.systemResearch.description, "平台基础能力底座，持续为系统策略和 AI 推理供能。");
  assert.deepEqual(viewModel.indexFoundation.systemResearch.bullets, [
    "系统研究结果沉淀",
    "系统策略支撑",
    "平台公共能力",
    "AI 推理优先参考路径",
  ]);
});

test("ui-map shell view model prefers the real-data system research summary when available", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    systemResearch: {
      description: "已接入真实系统研究数据：9 个产物，覆盖 4 个部门、3 个阶段。",
      bullets: [
        "系统研究结果沉淀：9 个真实产物",
        "关系链路覆盖：7 条关系，3 个阶段",
        "平台能力覆盖：4 个部门",
      ],
    },
  });

  assert.equal(viewModel.indexFoundation.systemResearch.description, "已接入真实系统研究数据：9 个产物，覆盖 4 个部门、3 个阶段。");
  assert.deepEqual(viewModel.indexFoundation.systemResearch.bullets, [
    "系统研究结果沉淀：9 个真实产物",
    "关系链路覆盖：7 条关系，3 个阶段",
    "平台能力覆盖：4 个部门",
  ]);
});

test("buildResearchChainUIMapOverride summarizes real chain-phase data for ui-map", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-chain-"));
  const phasesDir = path.join(root, "trading");
  fs.mkdirSync(phasesDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/t-001", title: "T1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "t1.md" },
    { artifact_id: "trading/t-002", title: "T2", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "t2.md" },
    { artifact_id: "trading/t-003", title: "T3", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "t3.md" },
  ];

  fs.writeFileSync(
    path.join(phasesDir, "index.json"), JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts })
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildResearchChainUIMapOverride();

  assert.ok(override !== null);
  assert.match(override!.description, /已接入真实研究链路数据：3 条关系，覆盖 2 个阶段/);
  assert.ok(override!.bullets[0].includes("A4 → A6"));
  assert.ok(override!.bullets.some((b) => b.startsWith("A4：2 个产物")));
  assert.ok(override!.bullets.some((b) => b.startsWith("A6：1 个产物")));

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildResearchChainUIMapOverride returns null when no relation data exists", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-empty-"));
  const emptyDir = path.join(root, "trading");
  fs.mkdirSync(emptyDir, { recursive: true });
  fs.writeFileSync(
    path.join(emptyDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts: [] })
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;
  assert.equal(buildResearchChainUIMapOverride(), null);
  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildOperationsUIMapOverride returns null when no realtime events exist", () => {
  // Fresh hub starts empty (no events in any channel)
  const hub = createRealtimeHub();
  const channels: RealtimeChannel[] = ["dream-agent", "meeting", "system"];
  const totalEvents = channels.reduce((sum, ch) => sum + hub.getRecentEvents(ch).length, 0);
  assert.equal(totalEvents, 0);
});

test("buildOperationsUIMapOverride summaries include realtime event counts and timestamps", () => {
  // Publish a few events into the shared singleton to simulate real operational events.
  const hub = getRealtimeHub();
  hub.publish("dream-agent", { level: "info", message: "agent-query-1" });
  hub.publish("meeting", { level: "info", message: "meeting-start" });
  hub.publish("system", { level: "info", message: "status-ping" });
  hub.publish("meeting", { level: "info", message: "meeting-update" });

  const override = buildOperationsUIMapOverride();

  assert.ok(override !== null, "buildOperationsUIMapOverride should produce an override when events exist");
  assert.match(override!.description, /已接入真实运营事件：共 4 条最近事件，覆盖 3 个通道/);
  assert.ok(override!.bullets.some((b) => b.startsWith("dream-agent：1 条最近")));
  assert.ok(override!.bullets.some((b) => b.startsWith("meeting：2 条最近")));
  assert.ok(override!.bullets.some((b) => b.startsWith("system：1 条最近")));
});

test("ui-map shell view model keeps operations card as fallback when no override provided", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    operations: null,
  });

  assert.equal(viewModel.perspectiveLayer[1]?.title, "系统运营链路");
  assert.match(viewModel.perspectiveLayer[1]?.description ?? "", /前端进入、策略收口、上下文调用、执行和索引更新/);
  assert.equal(viewModel.perspectiveLayer[1]?.bullets?.length, 0);
});

test("ui-map shell view model prefers real-data operations summary when available", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    operations: {
      description: "已接入真实运营事件：共 4 条最近事件，覆盖 3 个通道。",
      bullets: ["dream-agent：1 条最近（2026-06-10 08:00）", "meeting：2 条最近（2026-06-10 08:01）", "system：1 条最近（2026-06-10 08:02）"],
    },
  });

  assert.equal(
    viewModel.perspectiveLayer[1]?.description,
    "已接入真实运营事件：共 4 条最近事件，覆盖 3 个通道。",
  );
  assert.deepEqual(viewModel.perspectiveLayer[1]?.bullets, [
    "dream-agent：1 条最近（2026-06-10 08:00）",
    "meeting：2 条最近（2026-06-10 08:01）",
    "system：1 条最近（2026-06-10 08:02）",
  ]);
});

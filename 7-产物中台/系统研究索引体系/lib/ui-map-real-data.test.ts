import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { getUIMapScenario } from "../app/ui-map/ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "../app/ui-map/ui-map-shell-view-model.ts";
import {
  buildResearchChainUIMapOverride,
  buildStrategyUIMapOverride,
  buildSystemResearchUIMapOverride,
  buildOperationsUIMapOverride,
  buildUserContextUIMapOverride,
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

test("ui-map page assembly produces Phase B shell when real artifact data and realtime events are present", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-assembly-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/t-001", title: "T1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "t1.md" },
    { artifact_id: "trading/t-002", title: "T2", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "t2.md" },
    { artifact_id: "trading/t-003", title: "T3", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "t3.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts })
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const hub = getRealtimeHub();
  hub.publish("dream-agent", { level: "info", message: "agent-query" });
  hub.publish("meeting", { level: "info", message: "meeting-start" });
  hub.publish("system", { level: "info", message: "status-ping" });

  const overrides = {
    systemResearch: buildSystemResearchUIMapOverride(),
    researchChain: buildResearchChainUIMapOverride(),
    operations: buildOperationsUIMapOverride(),
  };
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), overrides);

  assert.match(viewModel.hero.dataModeLabel, /Phase B/);
  assert.match(viewModel.hero.subtitle, /Phase B/);
  assert.match(viewModel.indexFoundation.systemResearch.description, /已接入真实系统研究数据/);
  assert.ok(viewModel.indexFoundation.systemResearch.bullets.some((b) => b.includes("真实产物")));
  assert.match(viewModel.perspectiveLayer[0]?.description ?? "", /已接入真实研究链路数据/);
  assert.match(viewModel.perspectiveLayer[1]?.description ?? "", /已接入真实运营事件/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
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

test("buildStrategyUIMapOverride produces summary-only label from strategy typed artifacts", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-strategy-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s1.md" },
    { artifact_id: "trading/s-002", title: "S2", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s2.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "r1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();

  assert.ok(override !== null, "buildStrategyUIMapOverride should produce an override when strategy artifacts exist");
  assert.match(override!.convergenceLabel, /summary-only/);
  assert.match(override!.convergenceLabel, /2 份策略产物沉淀/);
  assert.ok(override!.chain.includes("2 策略设置"));
  assert.ok(override!.chain.includes("策略执行"));
  assert.match(override!.summaryNote ?? "", /summary-only 接入/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildStrategyUIMapOverride returns null when no strategy artifacts exist", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-empty-strategy-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "r1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;
  assert.equal(buildStrategyUIMapOverride(), null);
  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("ui-map shell view model exposes strategy summaryNote through mainlineLayer", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    strategy: {
      convergenceLabel: "summary-only：2 份策略产物沉淀",
      chain: "2 策略设置 → 3 产物链条 → 1 活跃 → 结果产物 → 索引",
      summaryNote: "当前为摘要级接入：基于 artifacts 索引的 type=strategy 统计。",
    },
  });

  assert.equal(viewModel.mainlineLayer.summaryNote, "当前为摘要级接入：基于 artifacts 索引的 type=strategy 统计。");
  assert.match(viewModel.mainlineLayer.convergenceLabel, /summary-only/);
});

test("ui-map page assembly includes strategy override when all four adapters are wired", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-assembly-strategy-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s1.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "r1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const hub = getRealtimeHub();
  hub.publish("dream-agent", { level: "info", message: "agent-query" });

  const overrides = {
    systemResearch: buildSystemResearchUIMapOverride(),
    researchChain: buildResearchChainUIMapOverride(),
    operations: buildOperationsUIMapOverride(),
    strategy: buildStrategyUIMapOverride(),
  };
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), overrides);

  assert.match(viewModel.hero.dataModeLabel, /Phase B/);
  assert.match(viewModel.hero.dataModeLabel, /策略主线/);
  assert.match(viewModel.mainlineLayer.convergenceLabel, /summary-only/);
  assert.match(viewModel.mainlineLayer.summaryNote ?? "", /summary-only 接入/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildUserContextUIMapOverride returns null when no artifacts exist", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-empty-uc-"));
  const emptyDir = path.join(root, "knowledge");
  fs.mkdirSync(emptyDir, { recursive: true });
  fs.writeFileSync(
    path.join(emptyDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts: [] }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;
  assert.equal(buildUserContextUIMapOverride(), null);
  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildUserContextUIMapOverride produces summary-only label from artifact statistics", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-real-data-uc-"));
  const dir = path.join(root, "trading");
  fs.mkdirSync(dir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: [], filename: "s1.md" },
    { artifact_id: "trading/k-001", title: "K1", department: "knowledge", type: "knowledge", status: "active", date: "2026-06-10T08:00:00Z", chain_phase: "A6", tags: [], filename: "k1.md" },
  ];

  fs.writeFileSync(
    path.join(dir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildUserContextUIMapOverride();

  assert.ok(override !== null, "buildUserContextUIMapOverride should produce an override when artifacts exist");
  assert.ok(override!.buildLabel.length > 0, "buildLabel should be non-empty");
  assert.ok(override!.runtimeLabel.length > 0, "runtimeLabel should be non-empty");
  assert.match(override!.description, /summary-only/);
  assert.match(override!.summaryNote, /未透出/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("ui-map shell view model prefers real-data user-context override when available", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    userContext: {
      description: "已接入 summary-only 用户上下文摘要",
      buildLabel: "支撑自定义策略生成（5 个已沉淀产物可被索引回溯）",
      runtimeLabel: "支撑每次策略执行（2 个活跃产物可供上下文注入）",
      summaryNote: "summary-only：未透出任何用户配置或敏感信息",
    },
  });

  assert.match(viewModel.indexFoundation.userContext.description, /已接入 summary-only/);
  assert.match(viewModel.indexFoundation.userContext.buildLabel, /已沉淀产物可被索引回溯/);
  assert.match(viewModel.indexFoundation.userContext.runtimeLabel, /活跃产物可供上下文注入/);
  assert.ok(
    viewModel.indexFoundation.userContext.executionFrequencies.some((f) => f.includes("未透出")),
  );
});

test("ui-map page assembly marks hero dataModeLabel with user-context override", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), {
    userContext: {
      description: "已接入 summary-only 用户上下文摘要",
      buildLabel: "支撑自定义策略生成",
      runtimeLabel: "支撑每次策略执行",
      summaryNote: "summary-only：未透出任何用户配置或敏感信息",
    },
  });

  assert.match(viewModel.hero.dataModeLabel, /Phase B/);
  assert.match(viewModel.hero.dataModeLabel, /用户上下文索引/);
});

test("buildStrategyUIMapOverride includes A-phase distribution in its summary-only label", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-strategy-aphase-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A3", tags: ["signal"], filename: "s1.md" },
    { artifact_id: "trading/s-002", title: "S2", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s2.md" },
    { artifact_id: "trading/s-003", title: "S3", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: ["signal"], filename: "s3.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: ["summary"], filename: "r1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();
  assert.ok(override !== null);
  assert.match(override!.convergenceLabel, /A3×1/);
  assert.match(override!.convergenceLabel, /A4×2/);
  assert.match(override!.chain, /3 策略设置/);
  assert.match(override!.chain, /1 活跃 \/ 2 已沉淀/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildStrategyUIMapOverride shows fallback label when no A-phase annotation exists", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-strategy-no-aphase-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "", tags: [], filename: "s1.md" },
    { artifact_id: "trading/g-001", title: "G1", department: "trading", type: "governance", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "", tags: [], filename: "g1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();
  assert.ok(override !== null);
  assert.match(override!.convergenceLabel, /无 A-phase 标注/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildStrategyUIMapOverride counts phase from strategy artifacts only, not other types", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-strategy-phase-scope-"));
  const dir = path.join(root, "trading");
  fs.mkdirSync(dir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A4", tags: [], filename: "s1.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "completed", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: [], filename: "r1.md" },
    { artifact_id: "trading/r-002", title: "R2", department: "trading", type: "research", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: [], filename: "r2.md" },
    { artifact_id: "trading/r-003", title: "R3", department: "trading", type: "knowledge", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A5", tags: [], filename: "r3.md" },
  ];

  fs.writeFileSync(
    path.join(dir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();
  assert.ok(override !== null);
  assert.match(override!.convergenceLabel, /A4×1/);
  assert.ok(!override!.convergenceLabel.includes("A6"), "phase label should only reflect strategy-typed artifacts");
  assert.ok(!override!.convergenceLabel.includes("A5"), "phase label should only reflect strategy-typed artifacts");
  assert.match(override!.chain, /1 策略设置（0 活跃 \/ 1 已沉淀）/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildStrategyUIMapOverride normalizes lowercase phase labels like a9 to A9", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-strategy-phase-lowercase-"));
  const dir = path.join(root, "trading");
  fs.mkdirSync(dir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "a9", tags: [], filename: "s1.md" },
    { artifact_id: "trading/s-002", title: "S2", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "a9", tags: [], filename: "s2.md" },
  ];

  fs.writeFileSync(
    path.join(dir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();
  assert.ok(override !== null);
  assert.match(override!.convergenceLabel, /A9×2/);
  assert.ok(!override!.convergenceLabel.includes("a9"), "lowercase phase labels should be normalized to uppercase");

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("buildStrategyUIMapOverride counts active/completed only among strategy artifacts", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-strategy-status-scope-"));
  const dir = path.join(root, "trading");
  fs.mkdirSync(dir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "", tags: [], filename: "s1.md" },
    { artifact_id: "trading/s-002", title: "S2", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "", tags: [], filename: "s2.md" },
    { artifact_id: "trading/s-003", title: "S3", department: "trading", type: "strategy", status: "active", date: "2026-06-09T08:00:00Z", chain_phase: "", tags: [], filename: "s3.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: [], filename: "r1.md" },
    { artifact_id: "trading/r-002", title: "R2", department: "trading", type: "research", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A6", tags: [], filename: "r2.md" },
  ];

  fs.writeFileSync(
    path.join(dir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const override = buildStrategyUIMapOverride();
  assert.ok(override !== null);
  assert.match(override!.chain, /3 策略设置/);
  assert.match(override!.chain, /2 活跃 \/ 1 已沉淀/);
  // chain description is now strategy-centric; does not reference total artifact count
  assert.ok(override!.chain.includes("策略执行"));

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

test("ui-map page assembly produces Phase B shell when all five real-data adapters are wired", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "ui-map-assembly-all-five-"));
  const tradingDir = path.join(root, "trading");
  fs.mkdirSync(tradingDir, { recursive: true });

  const artifacts = [
    { artifact_id: "trading/s-001", title: "S1", department: "trading", type: "strategy", status: "completed", date: "2026-06-09T08:00:00Z", chain_phase: "A3", tags: ["signal"], filename: "s1.md" },
    { artifact_id: "trading/r-001", title: "R1", department: "trading", type: "research", status: "active", date: "2026-06-08T08:00:00Z", chain_phase: "A5", tags: ["summary"], filename: "r1.md" },
  ];

  fs.writeFileSync(
    path.join(tradingDir, "index.json"),
    JSON.stringify({ last_updated: "2026-06-09T08:00:00Z", artifacts }),
  );

  process.env.WORKBUDDY_ARTIFACTS_ROOT = root;

  const hub = getRealtimeHub();
  hub.publish("dream-agent", { level: "info", message: "agent-query" });
  hub.publish("meeting", { level: "info", message: "meeting-start" });
  hub.publish("system", { level: "info", message: "status-ping" });

  const overrides = {
    systemResearch: buildSystemResearchUIMapOverride(),
    researchChain: buildResearchChainUIMapOverride(),
    operations: buildOperationsUIMapOverride(),
    strategy: buildStrategyUIMapOverride(),
    userContext: buildUserContextUIMapOverride(),
  };
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"), overrides);

  assert.match(viewModel.hero.dataModeLabel, /Phase B/);
  assert.match(viewModel.hero.dataModeLabel, /系统研究索引/);
  assert.match(viewModel.hero.dataModeLabel, /研究链路/);
  assert.match(viewModel.hero.dataModeLabel, /运营链路/);
  assert.match(viewModel.hero.dataModeLabel, /策略主线/);
  assert.match(viewModel.hero.dataModeLabel, /用户上下文索引/);

  assert.match(viewModel.indexFoundation.systemResearch.description, /已接入真实系统研究数据/);
  assert.match(viewModel.indexFoundation.userContext.description, /已接入 summary-only/);
  assert.match(viewModel.mainlineLayer.convergenceLabel, /summary-only/);
  assert.match(viewModel.mainlineLayer.chain, /策略设置/);
  assert.match(viewModel.perspectiveLayer[0]?.description ?? "", /已接入真实研究链路数据/);
  assert.match(viewModel.perspectiveLayer[1]?.description ?? "", /已接入真实运营事件/);

  delete process.env.WORKBUDDY_ARTIFACTS_ROOT;
  fs.rmSync(root, { recursive: true, force: true });
});

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { getUIMapScenario } from "../app/ui-map/ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "../app/ui-map/ui-map-shell-view-model.ts";
import { buildSystemResearchUIMapOverride } from "./ui-map-real-data.ts";

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

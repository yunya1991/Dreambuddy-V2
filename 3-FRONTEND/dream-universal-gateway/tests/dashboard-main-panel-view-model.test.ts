import test from "node:test";
import assert from "node:assert/strict";

import { buildDashboardMainPanelViewModel } from "../src/app/dashboard/dashboard-main-panel-view-model";

test("buildDashboardMainPanelViewModel groups dashboard state into three tracks", () => {
  const viewModel = buildDashboardMainPanelViewModel({
    strategy: {
      drafts: [{ strategyId: "draft_001", name: "突破草稿" }],
      applied: [{ taskOrderId: "order_001", title: "BTC 趋势跟随", status: "applied" }],
      active: [{ taskOrderId: "order_001", runStatus: "running", executionCount: 3 }],
    },
    memory: {
      totalRecords: 18,
      candidateCount: 2,
      adjustmentCount: 1,
    },
    llm: {
      status: "online",
      model: "qwen3-30b-a3b",
      intentMethod: "llm",
    },
  });

  assert.equal(viewModel.hero.entryLabel, "Dashboard 主入口");
  assert.equal(viewModel.strategyTrack.items[0]?.label, "策略设置");
  assert.equal(viewModel.strategyTrack.items[1]?.value, "1 个任务单");
  assert.equal(viewModel.intentTrack.items[0]?.value, "LLM 意图识别");
  assert.equal(viewModel.intentTrack.items[3]?.value, "18 条经验");
  assert.equal(viewModel.systemTrack.items[0]?.href, "http://127.0.0.1:3456/feed");
});

test("buildDashboardMainPanelViewModel falls back to placeholder values when dashboard state is empty", () => {
  const viewModel = buildDashboardMainPanelViewModel(null);

  assert.equal(viewModel.strategyTrack.items[0]?.value, "待配置");
  assert.equal(viewModel.intentTrack.items[1]?.value, "待接入");
  assert.equal(viewModel.systemTrack.items[1]?.value, "等待承接");
});

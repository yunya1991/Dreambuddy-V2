import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { getUIMapScenario } from "./ui-map-scenarios.ts";
import { buildUIMapShellViewModel } from "./ui-map-shell-view-model.ts";

test("shell view model keeps source layer first and mainline second", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"));

  assert.equal(viewModel.sourceLayer[0]?.title, "自定义策略");
  assert.equal(viewModel.sourceLayer[1]?.title, "系统策略");
  assert.equal(viewModel.mainlineLayer.title, "策略主线");
  assert.equal(viewModel.mainlineLayer.convergenceLabel, "通过交易设置实现策略收口");
});

test("shell view model keeps user context index as build-time and runtime foundation", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("execution-heavy"));

  assert.equal(viewModel.indexFoundation.userContext.title, "用户上下文索引系统");
  assert.equal(viewModel.indexFoundation.userContext.buildLabel, "支撑自定义策略生成");
  assert.equal(viewModel.indexFoundation.userContext.runtimeLabel, "支撑每次策略执行");
  assert.deepEqual(viewModel.indexFoundation.userContext.executionFrequencies, ["1h", "4h", "1d"]);
});

test("unknown scenario falls back to balanced shell data", () => {
  assert.equal(getUIMapScenario("missing").id, "balanced");
});

test("source layer keeps custom strategy as a composite source instead of a flat mechanism list", () => {
  const viewModel = buildUIMapShellViewModel(getUIMapScenario("balanced"));
  const custom = viewModel.sourceLayer[0];
  const system = viewModel.sourceLayer[1];

  assert.equal(custom.title, "自定义策略");
  assert.match(custom.description, /业务来源层/);
  assert.match(custom.description, /共同形成/);
  assert.ok(custom.bullets.includes("意图闭环"));
  assert.ok(custom.bullets.includes("AI 推理与推荐"));

  assert.equal(system?.title, "系统策略");
  assert.match(system.description, /业务来源层/);
});

test("ui-map shell marks the source layer as its own semantic section", () => {
  const source = readFileSync(new URL("./UIMapShell.tsx", import.meta.url), "utf8");

  assert.match(source, /aria-label="source-layer"/);
});

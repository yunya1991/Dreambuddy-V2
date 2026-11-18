/**
 * 任务看板渲染验收：用真实快照渲染，断言图上的每个数字都来自事件，不做 mock 补位。
 */

import { render, screen } from "@testing-library/react";
import { TaskBoard } from "../TaskBoard";
import type { TaskBoardSnapshot } from "@/types/task-board";

const SNAPSHOT: TaskBoardSnapshot = {
  task_id: "tr_20261118_btc_01",
  trace_id: "tr_20261118_btc_01",
  status: "running",
  stage: "execute",
  intent: {
    raw_input: "分析一下比特币接下来的趋势",
    gates: [
      { key: "brainstorm", label: "脑暴", hit: false },
      { key: "reverse_parse", label: "逆向解析", hit: true, reason: "需要拆解历史结构" },
      { key: "external_collect", label: "外部采集", hit: true, reason: "补充链上数据" },
    ],
    decision: "先逆向解析，再补充链上数据，最后生成 SPEC",
  },
  spec: {
    spec_id: "spec_btc_01",
    version: 2,
    status: "confirmed",
    fields: [
      { key: "goal", label: "目标", value: "判断 BTC 4h 趋势方向" },
      { key: "scope", label: "范围", value: "BTC/USDT 4h" },
      { key: "assumptions", label: "假设", value: "无重大黑天鹅" },
      { key: "deliverables", label: "交付", value: "趋势结论 + 关键位" },
      { key: "acceptance", label: "验收", value: "含链上证据" },
      { key: "dependencies", label: "依赖", value: "链上情绪快照" },
    ],
  },
  objective: {
    title: "BTC 4h 趋势研判",
    owner: "c_drive.supervisor",
    mode: "judge",
    deadline: "2026-11-18T18:00:00+08:00",
    confidence_threshold: 0.7,
    progress: 0.5,
  },
  krs: [
    {
      node_id: "KR1",
      objective: "证据齐备",
      criteria: "宏观与链上证据齐备",
      verify: "evidence_backed",
      owner: "onchain",
      evidence_id: "ev_1",
      evidence_count: 2,
      verdict: "pass",
    },
    {
      node_id: "KR2",
      objective: "方案可执行",
      criteria: "关键位与委托方案可执行",
      verify: "c_action",
      owner: "tactical",
      evidence_count: 0,
      verdict: "pending",
      reason: "方案未回传",
    },
  ],
  agents: [
    {
      role: "onchain",
      label: "链上研究员",
      state: "done",
      capability_ids: ["data.onchain_sentiment"],
      summary: "交易所净流出，长期持有者增持",
      evidence_count: 2,
      duration_ms: 1200,
    },
    {
      role: "technical",
      label: "结构分析师",
      state: "running",
      capability_ids: ["market.series"],
      evidence_count: 0,
    },
  ],
  acceptance: [
    {
      role: "onchain",
      node_id: "KR1",
      verdict: "pass",
      reason: "证据与结论一致",
      evidence_refs: ["ev_1", "ev_2"],
      ts: 1763445600000,
    },
  ],
  gates: [],
  cursors: { "acceptance.recorded:onchain:KR1": 5 },
  seq: 5,
  updated_at: 1763445600000,
};

describe("TaskBoard", () => {
  it("渲染目标、SPEC、KR 与执行卡片上的真实数据", () => {
    render(<TaskBoard snapshot={SNAPSHOT} />);

    expect(screen.getAllByText("BTC 4h 趋势研判").length).toBe(2); // 任务头 + 目标卡
    expect(screen.getByText("判断 BTC 4h 趋势方向")).toBeTruthy();
    expect(screen.getByText("分析一下比特币接下来的趋势")).toBeTruthy();
    expect(screen.getByText("逆向解析 · 命中")).toBeTruthy();
    expect(screen.getByText("外部采集 · 命中")).toBeTruthy();

    expect(screen.getByTestId("okr-row-KR1")).toBeTruthy();
    expect(screen.getByText("关键位与委托方案可执行")).toBeTruthy();
    expect(screen.getAllByText("通过").length).toBeGreaterThan(0);
    expect(screen.getByText("待复核")).toBeTruthy();

    expect(screen.getByTestId("agent-card-onchain")).toBeTruthy();
    expect(screen.getByText("data.onchain_sentiment")).toBeTruthy();
    expect(screen.getByText("交易所净流出，长期持有者增持")).toBeTruthy();

    expect(screen.getByTestId("stage-execute").dataset.state).toBe("active");
    expect(screen.getByText("1/2")).toBeTruthy();
  });

  it("证据缺失显示「—」而不是 0", () => {
    render(<TaskBoard snapshot={SNAPSHOT} />);
    // KR2 证据数为 0 → 展示为「—」
    expect(screen.getAllByText("证据 —").length).toBeGreaterThan(0);
  });

  it("无汇总时不提前点亮结论", () => {
    render(<TaskBoard snapshot={SNAPSHOT} />);
    expect(screen.getByText(/全部 OKR 验收通过后/)).toBeTruthy();
  });
});

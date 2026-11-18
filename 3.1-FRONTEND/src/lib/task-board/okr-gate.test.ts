/**
 * T5 单测：OKR 完整性校验与 dispatch 门（自动通过 vs 5 类高不确定性）。
 */

import type { OkrNode, TaskObjective } from "@/types/task-board";
import {
  buildDispatchGate,
  dispatchGateEvidenceRef,
  resolveDispatchGate,
  validateOkr,
} from "./okr-gate";

function objective(over: Partial<TaskObjective> = {}): TaskObjective {
  return {
    title: "验证策略",
    owner: "a_layer:okr_owner",
    mode: "judge",
    confidence_threshold: 0.7,
    progress: 0,
    ...over,
  };
}

function kr(over: Partial<OkrNode> = {}): OkrNode {
  return {
    node_id: "kr-1",
    objective: "收集证据",
    criteria: "结论引用证据",
    verify: "evidence_backed",
    evidence_id: "kr-evidence:t:kr-1",
    evidence_count: 0,
    verdict: "pending",
    owner_domain: "domain:analysis",
    capability_ids: ["analysis.data_insight"],
    ...over,
  };
}

describe("validateOkr", () => {
  it("完整 OKR 通过校验", () => {
    const result = validateOkr(objective(), [kr()]);
    expect(result.ok).toBe(true);
    expect(result.issues).toHaveLength(0);
  });

  it("无 KR 直接判 OKR_INCOMPLETE", () => {
    const result = validateOkr(objective(), []);
    expect(result.ok).toBe(false);
    expect(result.code).toBe("OKR_INCOMPLETE");
    expect(result.issues[0].code).toBe("krs_empty");
  });

  it("缺 owner_domain / 能力不匹配都记为能力缺口", () => {
    const missingDomain = validateOkr(objective(), [
      kr({ owner_domain: undefined }),
    ]);
    expect(missingDomain.issues.map((i) => i.code)).toContain(
      "kr_owner_domain_missing",
    );

    const unmatched = validateOkr(objective(), [
      kr({ owner_domain: "domain:market_data" }),
    ]);
    expect(unmatched.issues.map((i) => i.code)).toContain(
      "kr_capability_unmatched",
    );
  });
});

describe("resolveDispatchGate", () => {
  it("standard 无高不确定性 → 自动通过", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 2,
    });
    expect(decision.status).toBe("approved");
    expect(decision.required).toBe(false);
    expect(decision.reasons).toHaveLength(0);
  });

  it("complexity score=3 边界 → 转人工", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 3,
    });
    expect(decision.status).toBe("waiting");
    expect(decision.reasons).toContain("complexity_boundary");
  });

  it("能力缺口 → 转人工且 fail-closed", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr({ owner_domain: undefined })],
      level: "standard",
      score: 2,
    });
    expect(decision.status).toBe("waiting");
    expect(decision.reasons).toContain("capability_gap");
    expect(decision.reasons).toContain("okr_incomplete");
    expect(decision.validation.ok).toBe(false);
  });

  it("evidence_backed 缺证据锚点 → 转人工", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr({ evidence_id: undefined })],
      level: "standard",
      score: 2,
    });
    expect(decision.reasons).toContain("missing_evidence_anchor");
  });

  it("验收预检 pending 或置信度低于阈值 → 转人工", () => {
    const pending = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 2,
      precheck: { verdict: "pending" },
    });
    expect(pending.reasons).toContain("acceptance_precheck_pending");

    const lowConfidence = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 2,
      precheck: { verdict: "pass", confidence: 0.5 },
    });
    expect(lowConfidence.reasons).toContain("acceptance_precheck_pending");

    const highConfidence = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 2,
      precheck: { verdict: "pass", confidence: 0.9 },
    });
    expect(highConfidence.status).toBe("approved");
  });

  it("Debate INCONCLUSIVE / 降级 → 转人工", () => {
    const inconclusive = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "deep",
      score: 6,
      debateVerdict: "INCONCLUSIVE",
    });
    expect(inconclusive.reasons).toContain("debate_inconclusive");

    const degraded = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "deep",
      score: 6,
      debateDegraded: true,
    });
    expect(degraded.reasons).toContain("debate_degraded");

    const win = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "deep",
      score: 6,
      debateVerdict: "WIN",
    });
    expect(win.status).toBe("approved");
  });
});

describe("buildDispatchGate", () => {
  it("自动通过的门带 system:auto 审计痕迹与可重算的证据引用", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr()],
      level: "standard",
      score: 2,
    });
    const gate = buildDispatchGate(decision, dispatchGateEvidenceRef(7), 1000);
    expect(gate.gate_id).toBe("dispatch");
    expect(gate.kind).toBe("dispatch");
    expect(gate.status).toBe("approved");
    expect(gate.decided_by).toBe("system:auto");
    expect(gate.evidence_ref).toBe("okr:7");
    expect(gate.decided_at).toBe(1000);
  });

  it("转人工的门写入触发原因", () => {
    const decision = resolveDispatchGate({
      objective: objective(),
      krs: [kr({ evidence_id: undefined })],
      level: "standard",
      score: 2,
    });
    const gate = buildDispatchGate(decision, "okr:3", 2000);
    expect(gate.status).toBe("waiting");
    expect(gate.decided_by).toBeUndefined();
    expect(gate.comment).toContain("证据锚点");
  });
});

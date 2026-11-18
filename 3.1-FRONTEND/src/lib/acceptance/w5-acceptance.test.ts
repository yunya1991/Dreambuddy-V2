/**
 * W5 T5.2 验收门（机器判定）：
 * 1) U 级证据是否足够；
 * 2) 残差准入是否漏放；
 * 3) 提案预注册/回滚/证据是否齐备。
 */
import { assessVerdict, type VerdictEvidence } from "../verdict/uncertainty-verdict";
import { admitResidual } from "../cognition/residual-admission";
import { buildProposalTicket } from "../../../../3-EVOLUTION/proposal-ticket-bridge";
import { freezePrereg } from "../../../../3-EVOLUTION/experiment-prereg";
import type { EvolutionProposal } from "../../../../3-EVOLUTION/types";

function assess(level: "U0" | "U1" | "U2" | "U3", evidence: VerdictEvidence[]) {
  return assessVerdict({
    task_id: "acceptance-task",
    trace_id: "trace-acceptance",
    claim: "验收命题",
    level,
    evidence,
    poe_score: 0.9,
    confidence: 0.9,
  });
}

describe("W5 验收：U 级证据", () => {
  it("U2 可复放回测 → supported", () => {
    const out = assess("U2", [
      { ref: "backtest:run-1", kind: "backtest", replayable: true, sample_size: 200, effect_size: 0.2 },
    ]);
    expect(out.verdict.verdict).toBe("supported");
  });

  it("U2 缺沙箱/回测 → inconclusive", () => {
    const out = assess("U2", [
      { ref: "stats:1", kind: "statistics", sample_size: 200 },
    ]);
    expect(out.verdict.verdict).toBe("inconclusive");
  });

  it("U2 不可复放 → inconclusive", () => {
    const out = assess("U2", [
      { ref: "sandbox:1", kind: "sandbox", replayable: false },
    ]);
    expect(out.verdict.verdict).toBe("inconclusive");
  });

  it("U3 两个独立来源 → supported", () => {
    const out = assess("U3", [
      { ref: "url:a", kind: "source", origin: "src-a" },
      { ref: "url:b", kind: "rea", origin: "src-b" },
    ]);
    expect(out.verdict.verdict).toBe("supported");
  });

  it("U3 同源转载只计 1 → inconclusive", () => {
    const out = assess("U3", [
      { ref: "url:a1", kind: "source", origin: "same" },
      { ref: "url:a2", kind: "source", origin: "same" },
    ]);
    expect(out.verdict.verdict).toBe("inconclusive");
  });

  it("证据过期 → inconclusive", () => {
    const out = assess("U1", [
      { ref: "stats:1", kind: "statistics", sample_size: 100, fresh: false },
    ]);
    expect(out.verdict.verdict).toBe("inconclusive");
  });
});

describe("W5 验收：残差准入", () => {
  it("敏感信息拒入", () => {
    expect(admitResidual({ content: "key", sensitive: true }).form).toBe("reject");
  });

  it("可重算 → M3", () => {
    expect(admitResidual({ content: "x", tests: { recompute: true } }).form).toBe("M3");
  });

  it("R1 有锚点 → M1", () => {
    const out = admitResidual({ content: "x", residual_kind: "R1", anchor: "case:1" });
    expect(out.form).toBe("M1");
  });

  it("R3 有关系 → M2", () => {
    const out = admitResidual({ content: "x", residual_kind: "R3", relations: ["a->b"] });
    expect(out.form).toBe("M2");
  });

  it("R3 无关系 → reject", () => {
    expect(admitResidual({ content: "x", residual_kind: "R3" }).form).toBe("reject");
  });

  it("trace 透传", () => {
    const out = admitResidual({ content: "x", residual_kind: "R1", anchor: "a", trace_id: "t-1" });
    expect(out.trace_id).toBe("t-1");
  });
});

function prereg() {
  return freezePrereg({
    prereg_id: "PR-A",
    proposal_id: "PROP-A",
    hypothesis: "失败率下降",
    metric: "failure_rate",
    direction: "lower_is_better",
    baseline_value: 0.2,
    success_threshold: 0.15,
    failure_threshold: 0.25,
    sample: {
      unit: "trade",
      min_size: 100,
      period_start: "2024-01-01",
      period_end: "2025-12-31",
      out_of_sample_ratio: 0.3,
    },
    stopping_rule: "样本耗尽即停",
    registered_at: "2026-01-01T00:00:00Z",
    locked: false,
  });
}

function proposal(over: Partial<EvolutionProposal> = {}): EvolutionProposal {
  return {
    id: "PROP-A",
    finding_id: "F-A",
    title: "降低失败率",
    description: "修复",
    change_type: "code_change",
    requires_code: true,
    rollback_plan_id: "rb-A",
    evidence_refs: ["F-A"],
    prereg_id: "PR-A",
    status: "pending_review",
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

describe("W5 验收：提案预注册", () => {
  it("齐备 + 预注册冻结 → 生成 Ticket", () => {
    const out = buildProposalTicket(proposal(), prereg());
    expect(out.ok).toBe(true);
  });

  it("无预注册 → 拒绝", () => {
    const out = buildProposalTicket(proposal({ prereg_id: undefined }), prereg());
    expect(out.ok).toBe(false);
  });

  it("预注册未冻结 → 拒绝", () => {
    const out = buildProposalTicket(proposal(), { ...prereg(), locked: false });
    expect(out.ok).toBe(false);
  });

  it("无回滚 → 拒绝", () => {
    const out = buildProposalTicket(proposal({ rollback_plan_id: "" }), prereg());
    expect(out.ok).toBe(false);
  });

  it("无证据 → 拒绝", () => {
    const out = buildProposalTicket(proposal({ evidence_refs: [] }), prereg());
    expect(out.ok).toBe(false);
  });

  it("直改生产 → 拒绝", () => {
    const p = { ...proposal(), direct_production: true } as EvolutionProposal;
    expect(buildProposalTicket(p, prereg()).ok).toBe(false);
  });
});

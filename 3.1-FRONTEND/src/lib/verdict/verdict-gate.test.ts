import { assessVerdict, type UncertaintyVerdict } from "./uncertainty-verdict";
import { checkVerdictForGate } from "./verdict-gate";

function supported(level: "U1" | "U2" = "U2"): UncertaintyVerdict {
  return assessVerdict({
    task_id: "t1",
    trace_id: "tr1",
    claim: "样本外有效",
    level,
    evidence: [
      level === "U2"
        ? { ref: "backtest:1", kind: "backtest", replayable: true }
        : { ref: "stats:1", kind: "statistics", sample_size: 100 },
    ],
    confidence: 0.9,
    now: 1,
  }).verdict;
}

describe("验收门消费 verdict", () => {
  it("Ticket 未声明级别 → 不强制", () => {
    expect(checkVerdictForGate({ required: undefined, verdict: null })).toEqual({
      ok: true,
    });
  });

  it("声明了级别但没有裁决 → verdict_required", () => {
    const result = checkVerdictForGate({ required: "U2", verdict: null });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("verdict_required");
  });

  it("裁决级别不足 → verdict_level_insufficient", () => {
    const result = checkVerdictForGate({ required: "U2", verdict: supported("U1") });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("verdict_level_insufficient");
  });

  it("有反证 → verdict_contradicted", () => {
    const verdict = { ...supported(), verdict: "contradicted" as const };
    const result = checkVerdictForGate({ required: "U1", verdict });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("verdict_contradicted");
  });

  it("inconclusive / needs_human → verdict_inconclusive", () => {
    const verdict = { ...supported(), verdict: "inconclusive" as const };
    const result = checkVerdictForGate({ required: "U1", verdict });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("verdict_inconclusive");
  });

  it("supported 但无证据 → verdict_evidence_empty", () => {
    const verdict = { ...supported(), evidence_refs: [] };
    const result = checkVerdictForGate({ required: "U1", verdict });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toBe("verdict_evidence_empty");
  });

  it("supported 且级别达标 → 通过", () => {
    expect(checkVerdictForGate({ required: "U2", verdict: supported("U2") })).toEqual({
      ok: true,
    });
  });
});

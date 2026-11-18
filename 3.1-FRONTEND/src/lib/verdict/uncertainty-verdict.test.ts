import { assessVerdict, validateVerdict, type VerdictInput } from "./uncertainty-verdict";

function input(overrides: Partial<VerdictInput> = {}): VerdictInput {
  return {
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "该因子在样本外有效",
    level: "U1",
    evidence: [
      {
        ref: "stats:factor-a:v1",
        kind: "statistics",
        sample_size: 240,
        effect_size: 0.21,
        replayable: true,
      },
    ],
    confidence: 0.86,
    ...overrides,
  };
}

describe("UncertaintyVerdict", () => {
  it("U1 有统计证据 → supported", () => {
    const { verdict, issues } = assessVerdict(input());
    expect(verdict.verdict).toBe("supported");
    expect(verdict.evidence_refs).toHaveLength(1);
    expect(verdict.evidence_fingerprint).toHaveLength(8);
    expect(issues.filter((item) => item.level === "error")).toEqual([]);
  });

  it("U2 缺沙箱/回测 → inconclusive", () => {
    const { verdict } = assessVerdict(
      input({ level: "U2", evidence: [], confidence: 0.9 }),
    );
    expect(verdict.verdict).toBe("inconclusive");
  });

  it("U2 有可复放回测 → supported", () => {
    const { verdict } = assessVerdict(
      input({
        level: "U2",
        evidence: [
          {
            ref: "backtest:run-9",
            kind: "backtest",
            replayable: true,
            sample_size: 500,
          },
        ],
        confidence: 0.9,
      }),
    );
    expect(verdict.verdict).toBe("supported");
  });

  it("U2 不可复放 → inconclusive", () => {
    const { verdict } = assessVerdict(
      input({
        level: "U2",
        evidence: [{ ref: "backtest:x", kind: "backtest", replayable: false }],
        confidence: 0.9,
      }),
    );
    expect(verdict.verdict).toBe("inconclusive");
  });

  it("U3 同源转载只计 1 个 → inconclusive", () => {
    const { verdict } = assessVerdict(
      input({
        level: "U3",
        evidence: [
          { ref: "https://a", kind: "source", origin: "reuters" },
          { ref: "https://b", kind: "source", origin: "reuters" },
        ],
        confidence: 0.8,
      }),
    );
    expect(verdict.verdict).toBe("inconclusive");
  });

  it("U3 两个独立来源 → supported", () => {
    const { verdict } = assessVerdict(
      input({
        level: "U3",
        evidence: [
          { ref: "https://a", kind: "source", origin: "reuters" },
          { ref: "https://b", kind: "rea", origin: "33-rea" },
        ],
        confidence: 0.8,
      }),
    );
    expect(verdict.verdict).toBe("supported");
  });

  it("存在反证 → contradicted", () => {
    const { verdict } = assessVerdict(
      input({
        evidence: [
          ...input().evidence,
          { ref: "stats:opposite", kind: "statistics", sample_size: 300, contradicts: true },
        ],
      }),
    );
    expect(verdict.verdict).toBe("contradicted");
  });

  it("证据过期 → 剔除后 inconclusive", () => {
    const { verdict } = assessVerdict(
      input({
        evidence: [
          { ref: "stats:old", kind: "statistics", sample_size: 240, fresh: false },
        ],
      }),
    );
    expect(verdict.verdict).toBe("inconclusive");
    expect(verdict.evidence_refs).toEqual([]);
  });

  it("PoE 分数不足 → needs_human", () => {
    const { verdict } = assessVerdict(input({ poe_score: 0.62 }));
    expect(verdict.verdict).toBe("needs_human");
  });

  it("校验器拦截 supported 但无证据的伪造记录", () => {
    const { verdict } = assessVerdict(input());
    const issues = validateVerdict({ ...verdict, evidence_refs: [] });
    expect(issues.map((item) => item.code)).toContain("supported_without_evidence");
  });
});

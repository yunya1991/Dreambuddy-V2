import { combineGateVotes, type GateVote } from "./gate-quorum";

function vote(
  model: string,
  family: string,
  verdict: GateVote["verdict"],
  overrides: Partial<GateVote> = {},
): GateVote {
  return {
    model_id: model,
    provider: family,
    family,
    verdict,
    confidence: 0.9,
    latency_ms: 100,
    degraded: verdict === "needs_human",
    ...overrides,
  };
}

describe("gate-quorum", () => {
  it("两个异构家族全部通过 → pass", () => {
    const result = combineGateVotes(
      [vote("qwen4-max", "alibaba", "pass"), vote("jev-latest", "typesafe", "pass")],
      { quorum: "all", minDistinctModels: 2 },
    );
    expect(result.verdict).toBe("pass");
    expect(result.distinct_families).toBe(2);
  });

  it("同家族多实例只算一票", () => {
    const result = combineGateVotes(
      [
        vote("qwen4-max", "alibaba", "pass"),
        vote("qwen3.8-flash", "alibaba", "pass"),
      ],
      { quorum: "all", minDistinctModels: 2 },
    );
    expect(result.verdict).toBe("needs_human");
    expect(result.reasons).toContain("insufficient_distinct_gate_models:1<2");
  });

  it("会签中任一反对 → fail", () => {
    const result = combineGateVotes(
      [vote("qwen4-max", "alibaba", "pass"), vote("jev-latest", "typesafe", "fail")],
      { quorum: "all", minDistinctModels: 2 },
    );
    expect(result.verdict).toBe("fail");
  });

  it("或签中任一通过 → pass", () => {
    const result = combineGateVotes(
      [vote("qwen4-max", "alibaba", "pass"), vote("jev-latest", "typesafe", "fail")],
      { quorum: "any", minDistinctModels: 2 },
    );
    expect(result.verdict).toBe("pass");
  });

  it("全部降级 → needs_human", () => {
    const result = combineGateVotes(
      [
        vote("qwen4-max", "alibaba", "needs_human"),
        vote("jev-latest", "typesafe", "needs_human"),
      ],
      { quorum: "all", minDistinctModels: 2 },
    );
    expect(result.verdict).toBe("needs_human");
    expect(result.reasons).toContain("all_gate_models_degraded");
  });
});

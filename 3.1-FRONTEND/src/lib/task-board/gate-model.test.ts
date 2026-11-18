import { normalizeGateVerdict, runGatePrecheck } from "./gate-model";
import { canApprove, resolveGateRoles } from "./roles";

describe("gate-model", () => {
  const input = {
    gate_kind: "acceptance" as const,
    evidence_ref: "spec:1:v1",
    evidence: { krs: [] },
  };

  it("未配置模型时降级为 needs_human", async () => {
    const verdict = await runGatePrecheck(input, { caller: null });
    expect(verdict.verdict).toBe("needs_human");
    expect(verdict.reasons).toContain("gate_model_unavailable");
    expect(verdict.degraded).toBe(true);
  });

  it("模型报错时降级为 needs_human", async () => {
    const verdict = await runGatePrecheck(input, {
      caller: async () => {
        throw new Error("timeout");
      },
      modelId: "qwen-gate",
    });
    expect(verdict.verdict).toBe("needs_human");
    expect(verdict.reasons).toContain("gate_model_error");
  });

  it("输出不合 schema 时降级", () => {
    expect(normalizeGateVerdict({ verdict: "ok" }).verdict).toBe("needs_human");
    expect(normalizeGateVerdict(null).verdict).toBe("needs_human");
  });

  it("pass 但仍有缺口时降级", () => {
    const verdict = normalizeGateVerdict({
      verdict: "pass",
      missing: ["macro.gdp_yoy"],
    });
    expect(verdict.verdict).toBe("needs_human");
    expect(verdict.reasons).toContain("evidence_gap_unresolved");
  });

  it("合法输出按原样返回", () => {
    const verdict = normalizeGateVerdict({
      verdict: "pass",
      reasons: ["krs 均有证据"],
      evidence_refs: ["okr:1"],
      confidence: 0.8,
    });
    expect(verdict.verdict).toBe("pass");
    expect(verdict.confidence).toBe(0.8);
    expect(verdict.degraded).toBe(false);
  });
});

describe("gate roles", () => {
  it("未配置角色表时进入 bootstrap，本地可用", () => {
    const resolved = resolveGateRoles("local@example.com", {});
    expect(resolved.bootstrap).toBe(true);
    expect(resolved.roles).toContain("admin");
  });

  it("按环境变量映射角色", () => {
    const resolved = resolveGateRoles("Risk@Example.com", {
      GATE_RISK_REVIEWERS: "risk@example.com",
      GATE_TEAM_LEADS: "lead@example.com",
    });
    expect(resolved.roles).toEqual(["owner", "risk_reviewer"]);
    expect(resolved.bootstrap).toBe(false);
    expect(canApprove(resolved.roles, ["risk_reviewer"])).toBe(true);
    expect(canApprove(resolved.roles, ["team_lead"])).toBe(false);
  });
});

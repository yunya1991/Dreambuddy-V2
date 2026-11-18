import { admitResidual } from "./residual-admission";

describe("残差记忆准入", () => {
  it("敏感信息禁入", () => {
    expect(admitResidual({ content: "token", sensitive: true }).form).toBe("reject");
  });

  it("轨迹倾倒禁入", () => {
    expect(admitResidual({ content: "step1...", trajectory: true }).code).toBe("trajectory");
  });

  it("重复指纹禁入", () => {
    expect(admitResidual({ content: "x", duplicate: true }).code).toBe("duplicate");
  });

  it("任一测试命中 → M3，不写库", () => {
    const result = admitResidual({
      content: "可从 REA 现场解析的结构",
      tests: { onsite: true },
    });
    expect(result.admit).toBe(false);
    expect(result.form).toBe("M3");
  });

  it("R1/R2 有 anchor → M1", () => {
    const result = admitResidual({
      content: "某次决策依赖的盘口异常",
      residual_kind: "R2",
      anchor: "chain:20261118:abc",
    });
    expect(result).toMatchObject({ admit: true, form: "M1" });
  });

  it("R1/R2 缺 anchor → reject", () => {
    expect(
      admitResidual({ content: "x", residual_kind: "R1" }).code,
    ).toBe("anchor_missing");
  });

  it("R3/R4 有 relations → M2", () => {
    const result = admitResidual({
      content: "失败路径：先加仓后止损",
      residual_kind: "R4",
      relations: ["加仓", "止损", "回撤"],
    });
    expect(result).toMatchObject({ admit: true, form: "M2" });
  });

  it("R3/R4 缺 relations → reject", () => {
    expect(
      admitResidual({ content: "x", residual_kind: "R3" }).code,
    ).toBe("relations_missing");
  });
});

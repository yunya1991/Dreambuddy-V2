import {
  buildModelRegistry,
  detectModelFamily,
  validateModelRegistry,
} from "./model-registry";

describe("model-registry", () => {
  it("按模型名识别家族", () => {
    expect(detectModelFamily("qwen-plus")).toBe("alibaba");
    expect(detectModelFamily("deepseek-chat")).toBe("deepseek");
    expect(detectModelFamily("kimi-k2")).toBe("moonshot");
    expect(detectModelFamily("gpt-4o-mini")).toBe("openai");
  });

  it("worker 复用 AGENT_*，judge/gate 未配置即为 null", () => {
    const registry = buildModelRegistry({
      AGENT_PROVIDER: "openai-compatible",
      AGENT_MODEL: "qwen-plus",
    });
    expect(registry.worker?.id).toBe("openai-compatible:qwen-plus");
    expect(registry.judge).toBeNull();
    expect(registry.gate).toBeNull();
  });

  it("生产严格模式：三类模型缺失即报错", () => {
    const registry = buildModelRegistry({ AGENT_MODEL: "qwen-plus" });
    const issues = validateModelRegistry(registry, { strict: true });
    const errors = issues
      .filter((issue) => issue.level === "error")
      .map((issue) => issue.code);
    expect(errors).toContain("missing_judge_model");
    expect(errors).toContain("missing_gate_model");
  });

  it("gate 与 worker 同源时拒绝", () => {
    const registry = buildModelRegistry({
      AGENT_MODEL: "qwen-plus",
      MODEL_JUDGE: "deepseek-chat",
      MODEL_GATE: "qwen-max",
    });
    const issues = validateModelRegistry(registry, { strict: true });
    expect(issues.map((issue) => issue.code)).toContain(
      "gate_not_heterogeneous",
    );
  });

  it("gate 拥有能力授权时拒绝", () => {
    const registry = buildModelRegistry({
      AGENT_MODEL: "qwen-plus",
      MODEL_JUDGE: "deepseek-chat",
      MODEL_GATE: "claude-sonnet",
    });
    expect(registry.gate).not.toBeNull();
    registry.gate!.allowedCapabilities = ["write_artifacts"];
    const issues = validateModelRegistry(registry, { strict: true });
    expect(issues.map((issue) => issue.code)).toContain("gate_has_capabilities");
  });

  it("三类异构且只读时校验通过", () => {
    const registry = buildModelRegistry({
      AGENT_MODEL: "qwen-plus",
      MODEL_JUDGE: "deepseek-chat",
      MODEL_GATE: "claude-sonnet",
      MODEL_GATE_SECONDARY: "jev-latest",
      MODEL_GATE_SECONDARY_PROVIDER: "typesafe",
    });
    const issues = validateModelRegistry(registry, { strict: true });
    expect(issues).toEqual([]);
  });

  it("主副门禁模型同源时拒绝", () => {
    const registry = buildModelRegistry({
      AGENT_MODEL: "qwen-plus",
      MODEL_JUDGE: "deepseek-chat",
      MODEL_GATE: "qwen4-max",
      MODEL_GATE_SECONDARY: "qwen3.8-flash",
      MODEL_GATE_SECONDARY_PROVIDER: "openai-compatible",
    });
    const codes = validateModelRegistry(registry, { strict: true }).map(
      (issue) => issue.code,
    );
    expect(codes).toContain("gate_secondary_not_heterogeneous");
  });
});

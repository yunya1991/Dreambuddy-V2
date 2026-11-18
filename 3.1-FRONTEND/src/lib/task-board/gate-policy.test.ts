import {
  DEFAULT_GATE_POLICIES,
  assertGatePolicySet,
  buildGatePolicy,
  validateGatePolicies,
} from "./gate-policy";
import type { ModelRegistry, ModelSpec } from "@/lib/model/model-registry";

function gateSpec(id: string, provider: string, family: string): ModelSpec {
  return {
    id,
    class: "gate",
    provider,
    family,
    model: id.split(":")[1] ?? id,
    temperature: 0,
    allowedCapabilities: [],
    enabled: true,
  };
}

describe("gate-policy", () => {
  it("五道门 × 四种风险的默认策略全部合法", () => {
    expect(DEFAULT_GATE_POLICIES).toHaveLength(20);
    expect(validateGatePolicies(DEFAULT_GATE_POLICIES)).toEqual([]);
  });

  it("高风险门要求双人 + 双异构模型", () => {
    const policy = buildGatePolicy("acceptance", "high");
    expect(policy.approver.min_distinct).toBe(2);
    expect(policy.approver.quorum).toBe("all");
    expect(policy.gate_model.min_distinct_models).toBe(2);
    expect(policy.gate_model.allowed_capabilities).toEqual([]);
    expect(policy.gate_model.temperature).toBe(0);
  });

  it("Agent 进入审批池直接判错", () => {
    const policy = buildGatePolicy("spec", "medium");
    policy.approver.roles = ["owner", "worker"];
    const codes = validateGatePolicies([policy]).map((issue) => issue.code);
    expect(codes).toContain("agent_in_approver");
  });

  it("超时自动通过被判错", () => {
    const policy = buildGatePolicy("dispatch", "medium");
    (policy.sla as { on_timeout: string }).on_timeout = "auto_approve";
    const codes = validateGatePolicies([policy]).map((issue) => issue.code);
    expect(codes).toContain("timeout_auto_approve");
  });

  it("预授权只能用于标准变更", () => {
    const policy = buildGatePolicy("intent", "low", "normal");
    policy.preauthorized.enabled = true;
    const codes = validateGatePolicies([policy]).map((issue) => issue.code);
    expect(codes).toContain("preauthorized_non_standard");
  });

  it("缺门禁策略时判错", () => {
    const codes = validateGatePolicies(
      DEFAULT_GATE_POLICIES.filter((policy) => policy.kind !== "summary"),
    ).map((issue) => issue.code);
    expect(codes).toContain("missing_gate_policy");
  });

  it("全权模式：低/中风险自动确认，验收门仍人工", () => {
    const intent = buildGatePolicy("intent", "low", "normal", "autonomy");
    expect(intent.mode).toBe("autonomy");
    expect(intent.auto_approve).toBe(true);
    expect(intent.human_required).toBe(false);

    const acceptance = buildGatePolicy(
      "acceptance",
      "high",
      "normal",
      "autonomy",
    );
    expect(acceptance.auto_approve).toBe(false);
    expect(acceptance.human_required).toBe(true);
  });

  it("人工干预模式：所有门都必须人工确认", () => {
    const intent = buildGatePolicy("intent", "low", "normal", "human");
    expect(intent.auto_approve).toBe(false);
    expect(intent.human_required).toBe(true);
  });

  it("高风险门自动确认被判错", () => {
    const policy = buildGatePolicy("acceptance", "high", "normal", "autonomy");
    policy.auto_approve = true;
    policy.human_required = false;
    const codes = validateGatePolicies([policy]).map((issue) => issue.code);
    expect(codes).toContain("high_risk_auto_approve");
    expect(codes).toContain("high_risk_without_human");
  });

  it("主副门禁模型都计入会签，不再误报模型不足", () => {
    const registry: ModelRegistry = {
      worker: null,
      judge: null,
      gate: gateSpec("qwen:qwen-plus", "qwen", "alibaba"),
      gate_secondary: gateSpec("typesafe:jev", "typesafe", "typesafe"),
    };
    const codes = assertGatePolicySet(DEFAULT_GATE_POLICIES, registry, {
      strict: false,
    }).map((issue) => issue.code);
    expect(codes).not.toContain("gate_models_insufficient_for_quorum");
  });

  it("只有主门禁时仍提示高风险门模型不足", () => {
    const registry: ModelRegistry = {
      worker: null,
      judge: null,
      gate: gateSpec("qwen:qwen-plus", "qwen", "alibaba"),
      gate_secondary: null,
    };
    const codes = assertGatePolicySet(DEFAULT_GATE_POLICIES, registry, {
      strict: false,
    }).map((issue) => issue.code);
    expect(codes).toContain("gate_models_insufficient_for_quorum");
  });
});

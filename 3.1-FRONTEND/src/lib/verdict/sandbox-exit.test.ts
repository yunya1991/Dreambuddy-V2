import {
  buildU2Verdict,
  createSandboxRegistry,
  runUnifiedSandbox,
  type SandboxAdapter,
  type SandboxMode,
  type SandboxRequest,
  type SandboxRun,
} from "./sandbox-exit";

function request(overrides: Partial<SandboxRequest> = {}): SandboxRequest {
  return {
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "该策略在样本外仍有正收益",
    mode: "backtest",
    capability: "6-TRADING.backtest",
    ...overrides,
  };
}

function run(overrides: Partial<SandboxRun> = {}): SandboxRun {
  return {
    ok: true,
    run_id: "run-1",
    mode: "backtest",
    seed: 42,
    code_version: "abc123",
    data_version: "d-2026-11",
    sample_size: 240,
    out_of_sample: true,
    costs: { fee_bps: 2, slippage_bps: 5 },
    metrics: { sharpe: 1.2 },
    ...overrides,
  };
}

function registryFor(result: SandboxRun, mode: SandboxMode = "backtest") {
  const adapter: SandboxAdapter = {
    capability: "6-TRADING.backtest",
    mode,
    run: jest.fn(async () => result),
  };
  return createSandboxRegistry([adapter]);
}

describe("U2 沙箱统一出口", () => {
  it("合规回测 → ok，产出 sandbox + backtest 两条证据", async () => {
    const exit = await runUnifiedSandbox(request(), registryFor(run()));
    expect(exit.ok).toBe(true);
    expect(exit.blockers).toEqual([]);
    expect(exit.evidence.map((item) => item.kind)).toEqual(["sandbox", "backtest"]);
    expect(exit.evidence.every((item) => item.replayable)).toBe(true);
  });

  it("申请写权限 → 直接拒绝", async () => {
    const exit = await runUnifiedSandbox(
      request({ write_access: true }),
      registryFor(run()),
    );
    expect(exit.ok).toBe(false);
    expect(exit.blockers[0].code).toBe("write_access_forbidden");
    expect(exit.evidence).toEqual([]);
  });

  it("交易热路径 → 直接拒绝", async () => {
    const exit = await runUnifiedSandbox(
      request({ hot_path: true }),
      registryFor(run()),
    );
    expect(exit.blockers[0].code).toBe("hot_path_forbidden");
  });

  it("未注册能力 → capability_not_allowed", async () => {
    const exit = await runUnifiedSandbox(
      request({ capability: "unknown.capability" }),
      registryFor(run()),
    );
    expect(exit.ok).toBe(false);
    expect(exit.blockers[0].code).toBe("capability_not_allowed");
  });

  it("模式不匹配 → capability_not_allowed", async () => {
    const exit = await runUnifiedSandbox(
      request({ mode: "sandbox", capability: "6-TRADING.backtest" }),
      registryFor(run({ mode: "sandbox" }), "backtest"),
    );
    expect(exit.blockers[0].code).toBe("capability_not_allowed");
  });

  it("缺 seed / code_version / data_version → not_replayable", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      registryFor(run({ seed: undefined, code_version: "", data_version: "" })),
    );
    expect(exit.ok).toBe(false);
    const codes = exit.blockers.map((item) => item.code);
    expect(codes.filter((code) => code === "not_replayable")).toHaveLength(3);
    expect(exit.evidence).toEqual([]);
  });

  it("回测缺成本模型 → costs_missing", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      registryFor(run({ costs: { fee_bps: 2 } })),
    );
    expect(exit.blockers.some((item) => item.code === "costs_missing")).toBe(true);
  });

  it("回测样本量为 0 → sample_size_missing", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      registryFor(run({ sample_size: 0 })),
    );
    expect(exit.blockers.some((item) => item.code === "sample_size_missing")).toBe(true);
  });

  it("回测未声明样本外 → out_of_sample_missing", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      registryFor(run({ out_of_sample: false })),
    );
    expect(exit.blockers.some((item) => item.code === "out_of_sample_missing")).toBe(true);
  });

  it("沙箱模式不要求回测要素，也不产 backtest 证据", async () => {
    const exit = await runUnifiedSandbox(
      request({ mode: "sandbox", capability: "sandbox.exec" }),
      createSandboxRegistry([
        {
          capability: "sandbox.exec",
          mode: "sandbox",
          run: async () => run({ mode: "sandbox", sample_size: undefined, costs: undefined, out_of_sample: undefined }),
        },
      ]),
    );
    expect(exit.ok).toBe(true);
    expect(exit.evidence.map((item) => item.kind)).toEqual(["sandbox"]);
  });

  it("适配器异常 → adapter_failed", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      createSandboxRegistry([
        {
          capability: "6-TRADING.backtest",
          mode: "backtest",
          run: async () => {
            throw new Error("boom");
          },
        },
      ]),
    );
    expect(exit.ok).toBe(false);
    expect(exit.blockers[0].code).toBe("adapter_failed");
  });

  it("运行失败 → run_failed", async () => {
    const exit = await runUnifiedSandbox(
      request(),
      registryFor(run({ ok: false, error: "数据缺口" })),
    );
    expect(exit.blockers[0].code).toBe("run_failed");
    expect(exit.blockers[0].message).toBe("数据缺口");
  });
});

describe("U2 裁决", () => {
  it("合规出口 + 置信度 → supported", async () => {
    const exit = await runUnifiedSandbox(request(), registryFor(run()));
    const { verdict } = buildU2Verdict({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "该策略在样本外仍有正收益",
      exit,
      confidence: 0.9,
    });
    expect(verdict.verdict).toBe("supported");
    expect(verdict.level).toBe("U2");
  });

  it("出口失败 → 无证据，只能 inconclusive", async () => {
    const exit = await runUnifiedSandbox(
      request({ hot_path: true }),
      registryFor(run()),
    );
    const { verdict, issues } = buildU2Verdict({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "该策略在样本外仍有正收益",
      exit,
      confidence: 0.9,
    });
    expect(verdict.verdict).toBe("inconclusive");
    expect(verdict.evidence_refs).toEqual([]);
    expect(issues.some((item) => item.code === "hot_path_forbidden")).toBe(true);
  });
});

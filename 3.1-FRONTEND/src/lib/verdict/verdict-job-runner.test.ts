import type { SourceRecord } from "./cross-source-reconcile";
import {
  createTradingBacktestAdapter,
  executeVerdictJobRequest,
  type TradingRunner,
} from "./verdict-job-runner";
import type { VerdictJobRequest } from "./verdict-jobs";

const NOW = Date.UTC(2026, 10, 18);

function source(id: string, origin: string): SourceRecord {
  return {
    source_id: id,
    origin,
    stance: "support",
    published_at: NOW - 60_000,
  };
}

function u3(overrides: Partial<VerdictJobRequest> = {}): VerdictJobRequest {
  return {
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "该接口返回营收字段",
    level: "U3",
    sources: [source("s1", "docs"), source("s2", "repo")],
    confidence: 0.86,
    ...overrides,
  };
}

function u2(overrides: Partial<VerdictJobRequest> = {}): VerdictJobRequest {
  return {
    task_id: "task-1",
    trace_id: "trace-1",
    claim: "该策略在样本外仍有正收益",
    level: "U2",
    sandbox: {
      mode: "backtest",
      capability: "6-TRADING.backtest",
      params: { symbol: "BTC-USDT-SWAP" },
    },
    confidence: 0.9,
    ...overrides,
  };
}

const fullRunner: TradingRunner = async () => ({
  ok: true,
  output: {
    run_id: "run-1",
    seed: 7,
    code_version: "abc123",
    data_version: "d-2026-11",
    sample_size: 240,
    out_of_sample: true,
    fee_bps: 2,
    slippage_bps: 5,
    metrics: { sharpe: 1.2 },
  },
});

describe("裁决 job 执行器", () => {
  it("U3 多源一致 → supported", async () => {
    const { verdict } = await executeVerdictJobRequest(u3());
    expect(verdict.verdict).toBe("supported");
    expect(verdict.level).toBe("U3");
  });

  it("U3 单一来源 → inconclusive", async () => {
    const { verdict } = await executeVerdictJobRequest(
      u3({ sources: [source("s1", "docs")] }),
    );
    expect(verdict.verdict).toBe("inconclusive");
  });

  it("U2 完整回测输出 → supported", async () => {
    const { verdict } = await executeVerdictJobRequest(u2(), {
      backtestRunner: fullRunner,
    });
    expect(verdict.verdict).toBe("supported");
    expect(verdict.level).toBe("U2");
    expect(verdict.evidence_refs).toContain("backtest:run-1");
  });

  it("U2 缺 seed/版本/成本 → inconclusive", async () => {
    const incomplete: TradingRunner = async () => ({
      ok: true,
      output: { run_id: "run-2", sample_size: 10, out_of_sample: true },
    });
    const { verdict, issues } = await executeVerdictJobRequest(u2(), {
      backtestRunner: incomplete,
    });
    expect(verdict.verdict).toBe("inconclusive");
    expect(issues.some((item) => item.code === "not_replayable")).toBe(true);
    expect(issues.some((item) => item.code === "costs_missing")).toBe(true);
  });

  it("U2 脚本失败 → run_failed，无证据", async () => {
    const failing: TradingRunner = async () => ({
      ok: false,
      error: "数据缺口",
    });
    const { verdict, issues } = await executeVerdictJobRequest(u2(), {
      backtestRunner: failing,
    });
    expect(verdict.verdict).toBe("inconclusive");
    expect(verdict.evidence_refs).toEqual([]);
    expect(issues.some((item) => item.code === "run_failed")).toBe(true);
  });

  it("U2 缺 sandbox 配置 → sandbox_config_required", async () => {
    const { verdict, issues } = await executeVerdictJobRequest(
      u2({ sandbox: undefined }),
      { backtestRunner: fullRunner },
    );
    expect(verdict.verdict).toBe("inconclusive");
    expect(issues.some((item) => item.code === "sandbox_config_required")).toBe(
      true,
    );
  });

  it("适配器只读：不向脚本传递写权限字段", async () => {
    const runner = jest.fn(fullRunner);
    const adapter = createTradingBacktestAdapter(runner);
    await adapter.run({
      task_id: "task-1",
      trace_id: "trace-1",
      claim: "x",
      mode: "backtest",
      capability: "6-TRADING.backtest",
      params: { symbol: "BTC-USDT-SWAP" },
    });
    expect(runner).toHaveBeenCalledWith("dream-backtest", {
      symbol: "BTC-USDT-SWAP",
    });
  });
});

/**
 * 异步裁决 job 的真实执行器（P2.5 运行时接线）。
 *
 * - U2：统一出口 → 6-TRADING `dream-backtest` 适配器 → U2 裁决；
 * - U3：跨源对账 → U3 裁决。
 *
 * 所有能力调用只读；任何异常都收敛为可解释的裁决或 job 失败，不静默放行。
 */

import { buildU3Verdict } from "./cross-source-reconcile";
import {
  buildU2Verdict,
  createSandboxRegistry,
  runUnifiedSandbox,
  type SandboxAdapter,
  type SandboxRun,
} from "./sandbox-exit";
import type { VerdictJobRequest } from "./verdict-jobs";
import type { UncertaintyVerdict, VerdictIssue } from "./uncertainty-verdict";

export type TradingRunner = (
  skillId: string,
  inputs?: Record<string, unknown>,
) => Promise<{ ok: boolean; output?: unknown; error?: string }>;

async function defaultTradingRunner(
  skillId: string,
  inputs: Record<string, unknown> = {},
): Promise<{ ok: boolean; output?: unknown; error?: string }> {
  // 延迟加载：只有真正执行 U2 时才引入进程/DSH 依赖
  const { executeTradingBinding } = await import("@/lib/trading-capability");
  return executeTradingBinding(skillId, inputs);
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

/** 6-TRADING 回测脚本 → 统一 `SandboxRun` 契约。 */
export function createTradingBacktestAdapter(
  runner: TradingRunner = defaultTradingRunner,
): SandboxAdapter {
  return {
    capability: "6-TRADING.backtest",
    mode: "backtest",
    async run(request): Promise<SandboxRun> {
      const params = request.params ?? {};
      const result = await runner("dream-backtest", params);
      if (!result.ok) {
        return {
          ok: false,
          run_id: "",
          mode: "backtest",
          error: result.error || "回测脚本执行失败",
        };
      }
      const output = asRecord(result.output);
      return {
        ok: true,
        run_id: asString(output.run_id) ?? "",
        mode: "backtest",
        seed: (output.seed as string | number | undefined) ?? (params.seed as string | number | undefined),
        code_version:
          asString(output.code_version) ??
          asString(process.env.DREAMBUDDY_CODE_VERSION),
        data_version:
          asString(output.data_version) ?? asString(params.data_version),
        sample_size: asNumber(output.sample_size) ?? asNumber(output.trades) ?? 0,
        out_of_sample: output.out_of_sample === true,
        costs: {
          fee_bps:
            asNumber(output.fee_bps) ?? asNumber(params.fee_bps) ?? Number.NaN,
          slippage_bps:
            asNumber(output.slippage_bps) ??
            asNumber(params.slippage_bps) ??
            Number.NaN,
        },
        metrics: (output.metrics as Record<string, number> | undefined) ?? undefined,
      };
    },
  };
}

export interface VerdictJobDeps {
  backtestRunner?: TradingRunner;
}

/** job → 裁决。U2/U3 之外不猜测，直接失败。 */
export async function executeVerdictJobRequest(
  request: VerdictJobRequest,
  deps: VerdictJobDeps = {},
): Promise<{ verdict: UncertaintyVerdict; issues: VerdictIssue[] }> {
  if (request.level === "U2") {
    const config = request.sandbox;
    const registry = createSandboxRegistry([
      createTradingBacktestAdapter(deps.backtestRunner),
    ]);
    const exit = config
      ? await runUnifiedSandbox(
          {
            task_id: request.task_id,
            trace_id: request.trace_id,
            claim: request.claim,
            mode: config.mode,
            capability: config.capability,
            params: config.params,
          },
          registry,
        )
      : {
          ok: false,
          blockers: [
            {
              code: "sandbox_config_required",
              message: "U2 job 缺少 sandbox 配置",
            },
          ],
          evidence: [],
        };
    return buildU2Verdict({
      task_id: request.task_id,
      trace_id: request.trace_id,
      claim: request.claim,
      exit,
      confidence: request.confidence ?? null,
      poe_score: request.poe_score,
      dissent: request.dissent,
    });
  }

  if (request.level === "U3") {
    return buildU3Verdict({
      task_id: request.task_id,
      trace_id: request.trace_id,
      claim: request.claim,
      sources: request.sources ?? [],
      rea: request.rea,
      confidence: request.confidence ?? null,
      poe_score: request.poe_score,
      dissent: request.dissent,
    });
  }

  throw new Error(`不支持的裁决级别：${String(request.level)}`);
}

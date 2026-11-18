/**
 * U2 沙箱 / 回测统一出口（SPEC §3.6，P2.5 生产化）。
 *
 * 只做三件事：
 * 1. 守边界：写权限、交易热路径一律拒绝（红线 R4）；能力未注册即拒绝（deny-by-default）；
 * 2. 验证据：run_id + seed + code_version + data_version 必须齐全才可复放；
 *    回测还必须有样本量、成本/滑点、样本外标记；
 * 3. 统一信封：产出可直接裁决的 U2 证据，不让各壳自定义格式。
 *
 * 适配器由调用方注入（例如 6-TRADING `dream-backtest`），本模块不直接拉进程。
 */

import {
  assessVerdict,
  type UncertaintyVerdict,
  type VerdictEvidence,
  type VerdictIssue,
} from "./uncertainty-verdict";

export type SandboxMode = "sandbox" | "backtest";

export interface SandboxRequest {
  task_id: string;
  trace_id: string;
  claim: string;
  mode: SandboxMode;
  /** 能力 ID，例如 `sandbox.exec` / `6-TRADING.backtest` */
  capability: string;
  params?: Record<string, unknown>;
  /** 申请写权限：一律拒绝 */
  write_access?: boolean;
  /** 是否交易热路径：一律拒绝 */
  hot_path?: boolean;
}

export interface SandboxRun {
  ok: boolean;
  run_id: string;
  mode: SandboxMode;
  /** 可复放三要素 */
  seed?: string | number;
  code_version?: string;
  data_version?: string;
  /** 回测样本量 */
  sample_size?: number;
  /** 是否样本外 / walk-forward */
  out_of_sample?: boolean;
  /** 回测成本模型 */
  costs?: { fee_bps?: number; slippage_bps?: number };
  metrics?: Record<string, number>;
  error?: string;
}

export interface SandboxAdapter {
  capability: string;
  mode: SandboxMode;
  run(request: SandboxRequest): Promise<SandboxRun>;
}

export interface SandboxBlocker {
  code: string;
  message: string;
}

export interface SandboxExit {
  ok: boolean;
  blockers: SandboxBlocker[];
  evidence: VerdictEvidence[];
  run?: SandboxRun;
}

export interface SandboxRegistry {
  resolve(capability: string, mode: SandboxMode): SandboxAdapter | undefined;
  capabilities(): string[];
}

/** 注册表即白名单：未注册的能力不存在，调用直接拒绝。 */
export function createSandboxRegistry(adapters: SandboxAdapter[]): SandboxRegistry {
  const byKey = new Map<string, SandboxAdapter>();
  for (const adapter of adapters) {
    byKey.set(`${adapter.capability}::${adapter.mode}`, adapter);
  }
  return {
    resolve(capability, mode) {
      return byKey.get(`${capability}::${mode}`);
    },
    capabilities() {
      return [...byKey.keys()].map((key) => key.split("::")[0]);
    },
  };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function validateRun(run: SandboxRun, request: SandboxRequest): SandboxBlocker[] {
  const blockers: SandboxBlocker[] = [];
  if (run.mode !== request.mode) {
    blockers.push({
      code: "mode_mismatch",
      message: `运行模式 ${run.mode} 与请求 ${request.mode} 不一致`,
    });
  }
  if (!run.run_id?.trim()) {
    blockers.push({ code: "not_replayable", message: "缺少 run_id，无法复放" });
  }
  if (run.seed === undefined || run.seed === null || run.seed === "") {
    blockers.push({ code: "not_replayable", message: "缺少 seed，无法复放" });
  }
  if (!run.code_version?.trim()) {
    blockers.push({ code: "not_replayable", message: "缺少 code_version，无法复放" });
  }
  if (!run.data_version?.trim()) {
    blockers.push({ code: "not_replayable", message: "缺少 data_version，无法复放" });
  }

  if (request.mode === "backtest") {
    if (!isFiniteNumber(run.sample_size) || run.sample_size <= 0) {
      blockers.push({
        code: "sample_size_missing",
        message: "回测缺少有效样本量",
      });
    }
    if (
      !run.costs ||
      !isFiniteNumber(run.costs.fee_bps) ||
      !isFiniteNumber(run.costs.slippage_bps)
    ) {
      blockers.push({
        code: "costs_missing",
        message: "回测必须声明手续费与滑点",
      });
    }
    if (run.out_of_sample !== true) {
      blockers.push({
        code: "out_of_sample_missing",
        message: "回测必须声明样本外 / walk-forward",
      });
    }
  }
  return blockers;
}

function buildEvidence(run: SandboxRun): VerdictEvidence[] {
  const fingerprint = `${run.code_version}:${run.data_version}:${run.seed}`;
  const base: VerdictEvidence = {
    ref: `sandbox:${run.run_id}`,
    kind: "sandbox",
    fingerprint,
    fresh: true,
    replayable: true,
    sample_size: run.sample_size,
  };
  if (run.mode !== "backtest") return [base];
  return [
    base,
    {
      ...base,
      ref: `backtest:${run.run_id}`,
      kind: "backtest",
    },
  ];
}

/** 统一出口：先守边界，再跑适配器，最后验证据。 */
export async function runUnifiedSandbox(
  request: SandboxRequest,
  registry: SandboxRegistry,
): Promise<SandboxExit> {
  const blockers: SandboxBlocker[] = [];

  if (!request.task_id?.trim()) {
    blockers.push({ code: "task_id_required", message: "缺少 task_id" });
  }
  if (!request.claim?.trim()) {
    blockers.push({ code: "claim_required", message: "缺少可证伪 claim" });
  }
  if (request.write_access) {
    blockers.push({
      code: "write_access_forbidden",
      message: "沙箱/回测不得申请写权限（红线 R4）",
    });
  }
  if (request.hot_path) {
    blockers.push({
      code: "hot_path_forbidden",
      message: "交易热路径零接入（红线 R4）",
    });
  }
  if (blockers.length > 0) {
    return { ok: false, blockers, evidence: [] };
  }

  const adapter = registry.resolve(request.capability, request.mode);
  if (!adapter) {
    return {
      ok: false,
      blockers: [
        {
          code: "capability_not_allowed",
          message: `能力未注册或与模式不匹配：${request.capability} / ${request.mode}`,
        },
      ],
      evidence: [],
    };
  }

  let run: SandboxRun;
  try {
    run = await adapter.run(request);
  } catch (error) {
    return {
      ok: false,
      blockers: [
        {
          code: "adapter_failed",
          message: `适配器异常：${error instanceof Error ? error.message : String(error)}`,
        },
      ],
      evidence: [],
    };
  }

  if (!run.ok) {
    return {
      ok: false,
      blockers: [
        { code: "run_failed", message: run.error || "沙箱/回测执行失败" },
      ],
      run,
      evidence: [],
    };
  }

  const runBlockers = validateRun(run, request);
  if (runBlockers.length > 0) {
    return { ok: false, blockers: runBlockers, run, evidence: [] };
  }

  return { ok: true, blockers: [], run, evidence: buildEvidence(run) };
}

export interface U2VerdictInput {
  task_id: string;
  trace_id: string;
  claim: string;
  exit: SandboxExit;
  /** 额外的独立证据（如 L1 统计证据） */
  extra_evidence?: VerdictEvidence[];
  confidence?: number | null;
  poe_score?: number;
  dissent?: string[];
}

/** 出口结果 → U2 裁决。出口失败时不带任何证据，避免"跑过就算支持"。 */
export function buildU2Verdict(input: U2VerdictInput): {
  verdict: UncertaintyVerdict;
  issues: VerdictIssue[];
} {
  const evidence = input.exit.ok
    ? [...input.exit.evidence, ...(input.extra_evidence ?? [])]
    : [];
  const assessed = assessVerdict({
    task_id: input.task_id,
    trace_id: input.trace_id,
    claim: input.claim,
    level: "U2",
    evidence,
    methods: ["sandbox", ...(input.exit.run?.mode === "backtest" ? ["backtest"] : [])],
    confidence: input.confidence ?? null,
    poe_score: input.poe_score,
    dissent: input.dissent,
  });

  const issues = [...assessed.issues];
  for (const blocker of input.exit.blockers) {
    issues.push({
      level: "error",
      code: blocker.code,
      message: blocker.message,
    });
  }
  return { verdict: assessed.verdict, issues };
}

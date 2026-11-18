/**
 * 门禁会签（异构多模型）。
 *
 * 制度依据：会签 = 多个独立主体各自出结论；在 AI 层，独立性由
 * 「不同模型家族」保证，同模型多实例只算一票。
 *
 * 模型票永远只作预审意见：high / critical 门必须另有真人票。
 */

import type { GateVerdict } from "./gate-model";

export interface GateVote {
  model_id: string;
  provider: string;
  family: string;
  verdict: GateVerdict;
  /** 缺失记 null，不填 0 冒充 */
  confidence: number | null;
  latency_ms: number;
  degraded: boolean;
}

export interface QuorumOptions {
  quorum: "any" | "all" | "sequential";
  minDistinctModels: number;
  /** 独立性按家族去重（默认开） */
  requireDistinctFamilies?: boolean;
}

export interface QuorumResult {
  verdict: GateVerdict;
  distinct_models: number;
  distinct_families: number;
  votes: GateVote[];
  reasons: string[];
}

export function combineGateVotes(
  votes: GateVote[],
  opts: QuorumOptions,
): QuorumResult {
  const byModel = new Map<string, GateVote>();
  for (const vote of votes) {
    if (!byModel.has(vote.model_id)) byModel.set(vote.model_id, vote);
  }
  const unique = [...byModel.values()];
  const families = new Set(unique.map((vote) => vote.family));
  const distinctModels = unique.length;
  const distinctFamilies = families.size;

  const requireFamilies = opts.requireDistinctFamilies ?? true;
  const independentCount = requireFamilies ? distinctFamilies : distinctModels;

  const base = {
    distinct_models: distinctModels,
    distinct_families: distinctFamilies,
    votes: unique,
  };

  if (independentCount < opts.minDistinctModels) {
    return {
      ...base,
      verdict: "needs_human",
      reasons: [
        `insufficient_distinct_gate_models:${independentCount}<${opts.minDistinctModels}`,
      ],
    };
  }

  const usable = unique.filter(
    (vote) => !vote.degraded && vote.verdict !== "needs_human",
  );
  const passes = usable.filter((vote) => vote.verdict === "pass");
  const failures = usable.filter((vote) => vote.verdict === "fail");

  if (usable.length === 0) {
    return {
      ...base,
      verdict: "needs_human",
      reasons: ["all_gate_models_degraded"],
    };
  }

  if (opts.quorum === "any") {
    if (passes.length > 0) {
      return { ...base, verdict: "pass", reasons: ["any_pass"] };
    }
    if (failures.length === usable.length) {
      return { ...base, verdict: "fail", reasons: ["all_fail"] };
    }
    return { ...base, verdict: "needs_human", reasons: ["no_pass_no_consensus"] };
  }

  // all / sequential：任一反对即不通过，全部通过才通过
  if (failures.length > 0) {
    return {
      ...base,
      verdict: "fail",
      reasons: [`fail_votes:${failures.length}`],
    };
  }
  if (passes.length === usable.length) {
    return { ...base, verdict: "pass", reasons: ["all_pass"] };
  }
  return {
    ...base,
    verdict: "needs_human",
    reasons: ["needs_human_votes_present"],
  };
}

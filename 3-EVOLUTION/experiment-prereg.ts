/**
 * 实验预注册（W4 T4.1）。
 * 目的：先锁判据，再看结果；禁止事后改指标/样本/阈值。
 * 纯函数，无 IO；FAIL-OPEN 由调用侧处理。
 */

export type PreregDirection = "higher_is_better" | "lower_is_better";
export type PreregVerdict = "supported" | "rejected" | "inconclusive";

export interface ExperimentSample {
  /** 样本单位：trade / day / user_event */
  unit: string;
  /** 最小样本量，交易类默认 ≥ 30 */
  min_size: number;
  /** 回测区间，ISO 日期 */
  period_start: string;
  period_end: string;
  /** 样本外占比，0-1；低于 0.2 给出警告 */
  out_of_sample_ratio: number;
}

export interface ExperimentPrereg {
  prereg_id: string;
  proposal_id: string;
  hypothesis: string;
  metric: string;
  direction: PreregDirection;
  baseline_value: number;
  /** 达到即 supported */
  success_threshold: number;
  /** 达到/劣于即 rejected */
  failure_threshold: number;
  sample: ExperimentSample;
  /** 停止规则，必填，防止“再跑一次看看” */
  stopping_rule: string;
  registered_at: string;
  /** 判据指纹；冻结后任何字段变化都会被发现 */
  criteria_hash?: string;
  locked: boolean;
}

export interface PreregIssue {
  level: "error" | "warning";
  code: string;
  message: string;
}

export function validatePrereg(p: ExperimentPrereg): PreregIssue[] {
  const issues: PreregIssue[] = [];
  const err = (code: string, message: string) =>
    issues.push({ level: "error", code, message });
  const warn = (code: string, message: string) =>
    issues.push({ level: "warning", code, message });

  if (!p.prereg_id) err("missing_prereg_id", "缺少 prereg_id");
  if (!p.proposal_id) err("missing_proposal_id", "缺少 proposal_id");
  if (!p.hypothesis?.trim()) err("missing_hypothesis", "缺少可证伪假设");
  if (!p.metric?.trim()) err("missing_metric", "缺少指标");
  if (!p.stopping_rule?.trim()) err("missing_stopping_rule", "缺少停止规则");

  const s = p.sample;
  if (!s || !s.unit) err("missing_sample_unit", "缺少样本单位");
  if (!s || !(s.min_size > 0)) err("invalid_min_size", "min_size 必须 > 0");
  else if (s.min_size < 30) warn("small_sample", "min_size < 30，统计功效不足");
  if (!s?.period_start || !s?.period_end) err("missing_period", "缺少样本区间");
  if (s && s.out_of_sample_ratio < 0.2)
    warn("low_out_of_sample", "样本外占比 < 20%，过拟合风险高");

  if (p.direction === "higher_is_better") {
    if (!(p.success_threshold > p.baseline_value))
      err("inconsistent_threshold", "higher_is_better 要求 success > baseline");
    if (!(p.failure_threshold < p.success_threshold))
      err("inconsistent_threshold", "failure 必须低于 success");
  } else {
    if (!(p.success_threshold < p.baseline_value))
      err("inconsistent_threshold", "lower_is_better 要求 success < baseline");
    if (!(p.failure_threshold > p.success_threshold))
      err("inconsistent_threshold", "failure 必须高于 success");
  }
  return issues;
}

/** 判据指纹：只覆盖判据字段，不覆盖结果字段。 */
export function criteriaHash(p: ExperimentPrereg): string {
  const payload = JSON.stringify([
    p.metric,
    p.direction,
    p.baseline_value,
    p.success_threshold,
    p.failure_threshold,
    p.sample?.min_size,
    p.sample?.period_start,
    p.sample?.period_end,
    p.sample?.out_of_sample_ratio,
    p.stopping_rule,
  ]);
  let h = 5381;
  for (let i = 0; i < payload.length; i += 1) {
    h = ((h << 5) + h + payload.charCodeAt(i)) >>> 0;
  }
  return `ph1:${h.toString(16)}`;
}

/** 冻结：返回新对象，写入指纹。 */
export function freezePrereg(p: ExperimentPrereg): ExperimentPrereg {
  return { ...p, locked: true, criteria_hash: criteriaHash(p) };
}

/** 冻结后被改动 → false。 */
export function isPreregIntact(p: ExperimentPrereg): boolean {
  return Boolean(p.locked && p.criteria_hash && p.criteria_hash === criteriaHash(p));
}

/** 结果回填：只读判据，按预注册阈值裁决，不改任何阈值。 */
export function evaluatePrereg(
  p: ExperimentPrereg,
  result: { value: number; sample_size: number },
): { verdict: PreregVerdict; reason: string } {
  if (!p.locked || !isPreregIntact(p)) {
    return { verdict: "inconclusive", reason: "prereg_not_locked_or_tampered" };
  }
  if (!Number.isFinite(result.value) || !(result.sample_size > 0)) {
    return { verdict: "inconclusive", reason: "invalid_result" };
  }
  if (result.sample_size < p.sample.min_size) {
    return {
      verdict: "inconclusive",
      reason: `sample_size ${result.sample_size} < min ${p.sample.min_size}`,
    };
  }

  const better =
    p.direction === "higher_is_better"
      ? result.value >= p.success_threshold
      : result.value <= p.success_threshold;
  if (better) return { verdict: "supported", reason: "reached_success_threshold" };

  const worse =
    p.direction === "higher_is_better"
      ? result.value <= p.failure_threshold
      : result.value >= p.failure_threshold;
  if (worse) return { verdict: "rejected", reason: "reached_failure_threshold" };

  return { verdict: "inconclusive", reason: "between_thresholds" };
}

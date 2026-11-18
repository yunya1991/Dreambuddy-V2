/**
 * 残差记忆准入（35 / SPEC-ResidualMemory-Admission）。
 *
 * 只保留"不可由基础模型、单一事实源或现场求解再推导"的信息。
 * 记忆形态：
 * - M1 指针：存 anchor，用时重建；
 * - M2 联想：存关系/结构；
 * - M3 零记忆：现场可重建，不写库。
 */

export type ResidualKind = "R1" | "R2" | "R3" | "R4";
export type MemoryForm = "M1" | "M2" | "M3" | "reject";

export interface ResidualCandidate {
  content: string;
  /** trace 贯穿（T5.1）：来源 run / task */
  trace_id?: string;
  /** 四禁入：敏感、轨迹倾倒、重复、可推导 */
  sensitive?: boolean;
  trajectory?: boolean;
  duplicate?: boolean;
  derivable?: boolean;
  /** 三测试：任一命中即无需记忆（M3） */
  tests?: {
    deletion?: boolean; // 删除后无影响
    recompute?: boolean; // 可重算
    onsite?: boolean; // 现场可解析
  };
  residual_kind?: ResidualKind;
  anchor?: string;
  relations?: string[];
}

export interface AdmissionResult {
  admit: boolean;
  form: MemoryForm;
  code: string;
  reason: string;
  /** trace 贯穿（T5.1）：随候选透传，缺失为空串 */
  trace_id?: string;
}

function decideResidual(candidate: ResidualCandidate): AdmissionResult {
  if (!candidate.content?.trim()) {
    return { admit: false, form: "reject", code: "empty", reason: "内容为空" };
  }
  if (candidate.sensitive) {
    return { admit: false, form: "reject", code: "sensitive", reason: "敏感信息禁入" };
  }
  if (candidate.trajectory) {
    return { admit: false, form: "reject", code: "trajectory", reason: "过程/轨迹倾倒禁入" };
  }
  if (candidate.duplicate) {
    return { admit: false, form: "reject", code: "duplicate", reason: "重复指纹，已有记忆" };
  }

  const tests = candidate.tests ?? {};
  if (candidate.derivable || tests.deletion || tests.recompute || tests.onsite) {
    return {
      admit: false,
      form: "M3",
      code: "derivable",
      reason: "现场/事实源可重建，保留方法不保留内容",
    };
  }

  if (candidate.residual_kind === "R3" || candidate.residual_kind === "R4") {
    if ((candidate.relations?.length ?? 0) === 0) {
      return {
        admit: false,
        form: "reject",
        code: "relations_missing",
        reason: "关系型残差缺少 relations",
      };
    }
    return {
      admit: true,
      form: "M2",
      code: "association",
      reason: "保留关系结构，不复制长文",
    };
  }

  if (candidate.anchor) {
    return {
      admit: true,
      form: "M1",
      code: "pointer",
      reason: "只存指针，用时按 anchor 重建",
    };
  }

  if (candidate.residual_kind === "R1" || candidate.residual_kind === "R2") {
    return {
      admit: false,
      form: "reject",
      code: "anchor_missing",
      reason: "可残差化但缺少 anchor，无法重建",
    };
  }

  return {
    admit: false,
    form: "reject",
    code: "no_residual_value",
    reason: "未识别出不可推导的残差价值",
  };
}

/** 对外入口：透传 trace_id，保证记忆与来源 run 可追溯。 */
export function admitResidual(candidate: ResidualCandidate): AdmissionResult {
  const result = decideResidual(candidate);
  return { ...result, trace_id: candidate.trace_id || "" };
}

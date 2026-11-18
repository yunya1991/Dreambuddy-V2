/**
 * 验收门消费 verdict（T1.5）。
 * 规则：只看 acceptance 门；Ticket 声明 required_verdict_level 时才强制。
 */

import type {
  UncertaintyLevel,
  UncertaintyVerdict,
} from "./uncertainty-verdict";

const RANK: Record<UncertaintyLevel, number> = {
  U0: 0,
  U1: 1,
  U2: 2,
  U3: 3,
};

export type VerdictGateError =
  | "verdict_required"
  | "verdict_level_insufficient"
  | "verdict_contradicted"
  | "verdict_inconclusive"
  | "verdict_evidence_empty";

export type VerdictGateCheck =
  | { ok: true }
  | {
      ok: false;
      error: VerdictGateError;
      message: string;
      required_level: UncertaintyLevel;
      verdict: UncertaintyVerdict | null;
    };

export function checkVerdictForGate(input: {
  required: UncertaintyLevel | undefined;
  verdict: UncertaintyVerdict | null;
}): VerdictGateCheck {
  const { required, verdict } = input;
  if (!required) return { ok: true };

  if (!verdict) {
    return {
      ok: false,
      error: "verdict_required",
      message: `验收门需要 ${required} 级裁决，但尚未生成`,
      required_level: required,
      verdict: null,
    };
  }

  if (RANK[verdict.level] < RANK[required]) {
    return {
      ok: false,
      error: "verdict_level_insufficient",
      message: `裁决级别 ${verdict.level} 低于要求的 ${required}`,
      required_level: required,
      verdict,
    };
  }

  if (verdict.verdict === "contradicted") {
    return {
      ok: false,
      error: "verdict_contradicted",
      message: "裁决存在反证，不能通过验收",
      required_level: required,
      verdict,
    };
  }

  if (verdict.verdict !== "supported") {
    return {
      ok: false,
      error: "verdict_inconclusive",
      message: `裁决为 ${verdict.verdict}，需补证据或转人工`,
      required_level: required,
      verdict,
    };
  }

  if (verdict.evidence_refs.length === 0) {
    return {
      ok: false,
      error: "verdict_evidence_empty",
      message: "supported 裁决缺少证据引用",
      required_level: required,
      verdict,
    };
  }

  return { ok: true };
}

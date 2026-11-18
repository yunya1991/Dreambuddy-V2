/**
 * UncertaintyVerdict（SPEC §3.6）：把"不确定"收敛成可复算的证据结论。
 *
 * 定位：证据信封，不是第三套裁判。
 * - 上承 L0/L1 事实、U2 沙箱/回测、U3 采集/REA；
 * - 下接统一 PoE（poe_score）与 45 业务门禁；
 * - 生产模型/Worker 不得单独给出 verdict。
 */

export type UncertaintyLevel = "U0" | "U1" | "U2" | "U3";
export type Verdict = "supported" | "contradicted" | "inconclusive" | "needs_human";
export type EvidenceKind = "fact" | "statistics" | "sandbox" | "backtest" | "source" | "rea";

export interface VerdictEvidence {
  /** 证据引用：`spec:xxx:v2` / `backtest:run-123` / `url:...` */
  ref: string;
  kind: EvidenceKind;
  /** 来源标识；同一来源转载只计 1 个（U3 去重） */
  origin?: string;
  /** 证据内容指纹，用于判断是否过期 */
  fingerprint?: string;
  /** false 表示已过期/与当前版本不一致 */
  fresh?: boolean;
  /** 与命题相反的证据 */
  contradicts?: boolean;
  replayable?: boolean;
  sample_size?: number;
  effect_size?: number;
}

export interface VerdictInput {
  task_id: string;
  trace_id: string;
  claim: string;
  level: UncertaintyLevel;
  evidence: VerdictEvidence[];
  methods?: string[];
  confidence?: number | null;
  poe_score?: number;
  dissent?: string[];
  replayable?: boolean;
  now?: number;
}

export interface UncertaintyVerdict {
  verdict_id: string;
  task_id: string;
  trace_id: string;
  claim: string;
  level: UncertaintyLevel;
  methods: string[];
  evidence_refs: string[];
  evidence_fingerprint: string;
  sample_size?: number;
  effect_size?: number;
  confidence: number | null;
  verdict: Verdict;
  poe_score?: number;
  dissent: string[];
  replayable: boolean;
  created_at: number;
}

export interface VerdictIssue {
  level: "error" | "warning";
  code: string;
  message: string;
}

const REQUIRED_KINDS: Record<UncertaintyLevel, EvidenceKind[]> = {
  U0: ["fact"],
  U1: ["statistics"],
  U2: ["sandbox", "backtest"],
  U3: ["source", "rea"],
};

/** FNV-1a 32 位，够做内容指纹，不用于安全 */
function hash(input: string): string {
  let value = 0x811c9dc5;
  for (let i = 0; i < input.length; i += 1) {
    value ^= input.charCodeAt(i);
    value = Math.imul(value, 0x01000193);
  }
  return (value >>> 0).toString(16).padStart(8, "0");
}

function evidenceFingerprint(evidence: VerdictEvidence[]): string {
  const parts = evidence
    .filter((item) => item.fresh !== false)
    .map((item) => `${item.kind}:${item.ref}:${item.fingerprint ?? ""}`)
    .sort();
  return hash(parts.join("|"));
}

function distinctOrigins(evidence: VerdictEvidence[]): number {
  const seen = new Set<string>();
  for (const item of evidence) {
    if (item.fresh === false) continue;
    if (item.kind !== "source" && item.kind !== "rea") continue;
    seen.add(item.origin || item.ref);
  }
  return seen.size;
}

function hasRequiredEvidence(
  level: UncertaintyLevel,
  evidence: VerdictEvidence[],
): boolean {
  const fresh = evidence.filter((item) => item.fresh !== false);
  if (level === "U0") {
    return fresh.some((item) => item.kind === "fact");
  }
  if (level === "U1") {
    return fresh.some(
      (item) => item.kind === "statistics" && (item.sample_size ?? 0) > 0,
    );
  }
  if (level === "U2") {
    return fresh.some(
      (item) =>
        (item.kind === "sandbox" || item.kind === "backtest") &&
        item.replayable !== false,
    );
  }
  return distinctOrigins(fresh) >= 2;
}

/**
 * 生成裁决。核心规则：
 * - 证据不足一律 inconclusive，不"凑通过"；
 * - 有反证 → contradicted；
 * - PoE < 0.7 或有未解释分歧且置信度不足 → needs_human；
 * - U2 必须可复放，U3 至少两个独立来源。
 */
export function assessVerdict(input: VerdictInput): {
  verdict: UncertaintyVerdict;
  issues: VerdictIssue[];
} {
  const issues: VerdictIssue[] = [];
  const claim = input.claim?.trim() ?? "";
  const evidence = input.evidence ?? [];
  const fresh = evidence.filter((item) => item.fresh !== false);
  const fingerprint = evidenceFingerprint(evidence);
  const now = input.now ?? Date.now();

  if (!claim) {
    issues.push({ level: "error", code: "claim_required", message: "claim 不能为空" });
  }
  if (!input.task_id) {
    issues.push({ level: "error", code: "task_id_required", message: "task_id 不能为空" });
  }
  if (evidence.length === 0) {
    issues.push({
      level: "warning",
      code: "evidence_empty",
      message: "没有任何证据，只能给 inconclusive",
    });
  }
  if (fresh.length < evidence.length) {
    issues.push({
      level: "warning",
      code: "evidence_stale",
      message: "存在过期证据，已从裁决中剔除",
    });
  }
  if (!hasRequiredEvidence(input.level, evidence)) {
    issues.push({
      level: "warning",
      code: "evidence_insufficient",
      message: `${input.level} 所需证据不足：${REQUIRED_KINDS[input.level].join(" / ")}`,
    });
  }

  const confidence = input.confidence ?? null;
  const hasContradiction = fresh.some((item) => item.contradicts === true);
  const replayable =
    input.replayable ??
    (fresh.length > 0 && fresh.every((item) => item.replayable !== false));

  let verdict: Verdict;
  if (claim && evidence.length === 0) {
    verdict = "inconclusive";
  } else if (hasContradiction) {
    verdict = "contradicted";
  } else if (!hasRequiredEvidence(input.level, evidence)) {
    verdict = "inconclusive";
  } else if (input.level === "U2" && !replayable) {
    verdict = "inconclusive";
  } else if (confidence === null && (input.level === "U2" || input.level === "U3")) {
    verdict = "needs_human";
  } else if (input.poe_score !== undefined && input.poe_score < 0.7) {
    verdict = "needs_human";
  } else if (
    (input.dissent?.length ?? 0) > 0 &&
    confidence !== null &&
    confidence < 0.7
  ) {
    verdict = "needs_human";
  } else {
    verdict = "supported";
  }

  const sampleSizes = fresh
    .map((item) => item.sample_size)
    .filter((value): value is number => typeof value === "number");
  const effectSizes = fresh
    .map((item) => item.effect_size)
    .filter((value): value is number => typeof value === "number");

  const result: UncertaintyVerdict = {
    verdict_id: `verdict:${input.task_id}:${input.level}:${fingerprint}`,
    task_id: input.task_id,
    trace_id: input.trace_id || input.task_id,
    claim,
    level: input.level,
    methods:
      input.methods && input.methods.length > 0
        ? input.methods
        : [...new Set(fresh.map((item) => item.kind))],
    evidence_refs: fresh.map((item) => item.ref),
    evidence_fingerprint: fingerprint,
    sample_size: sampleSizes.length > 0 ? Math.max(...sampleSizes) : undefined,
    effect_size: effectSizes.length > 0 ? effectSizes[0] : undefined,
    confidence: confidence,
    verdict,
    poe_score: input.poe_score,
    dissent: input.dissent ?? [],
    replayable,
    created_at: now,
  };

  return { verdict: result, issues };
}

/** 存储前校验：防止手写 JSON 绕过规则 */
export function validateVerdict(value: UncertaintyVerdict): VerdictIssue[] {
  const issues: VerdictIssue[] = [];
  if (!value.verdict_id) {
    issues.push({ level: "error", code: "verdict_id_required", message: "缺少 verdict_id" });
  }
  if (!value.claim) {
    issues.push({ level: "error", code: "claim_required", message: "缺少 claim" });
  }
  if (!REQUIRED_KINDS[value.level]) {
    issues.push({ level: "error", code: "level_invalid", message: "level 非法" });
  }
  if (!["supported", "contradicted", "inconclusive", "needs_human"].includes(value.verdict)) {
    issues.push({ level: "error", code: "verdict_invalid", message: "verdict 非法" });
  }
  if (!value.evidence_fingerprint) {
    issues.push({
      level: "error",
      code: "fingerprint_required",
      message: "缺少证据指纹，无法判断是否过期",
    });
  }
  if (value.verdict === "supported" && value.evidence_refs.length === 0) {
    issues.push({
      level: "error",
      code: "supported_without_evidence",
      message: "supported 必须至少有一条证据",
    });
  }
  return issues;
}

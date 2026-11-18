/**
 * U3 跨源自动对账（SPEC §3.6，P2.5 生产化）。
 *
 * 职责：
 * - 去重：同 origin、同内容指纹、同规范化 URL 只计 1 个独立来源；
 * - 过期剔除：超过 max_age_ms 的来源不参与结论；
 * - 字段对账：同一字段在多源间取值不一致 → 冲突，结论降为 inconclusive；
 * - 产出可直接喂给 `assessVerdict` 的 U3 证据。
 *
 * 边界：只做证据归一，不产最终业务结论；裁决仍由 A / Adjudicator 产出。
 */

import {
  assessVerdict,
  type UncertaintyVerdict,
  type VerdictEvidence,
  type VerdictIssue,
} from "./uncertainty-verdict";

export type SourceStance = "support" | "refute" | "neutral";

export interface SourceRecord {
  source_id: string;
  /** 来源主体（媒体/机构/仓库）；同一主体多篇只计 1 个独立来源 */
  origin: string;
  url?: string;
  /** 内容指纹；相同指纹视为转载 */
  content_hash?: string;
  /** 发布时间（epoch ms）；缺失视为新鲜 */
  published_at?: number;
  stance: SourceStance;
  /** 结构化字段，用于同字段对账 */
  fields?: Record<string, string | number>;
}

export interface ReconcileOptions {
  now?: number;
  /** 证据最大年龄，默认 30 天 */
  max_age_ms?: number;
  /** 数值字段相对误差容差，默认 0（精确比较） */
  numeric_tolerance?: number;
  /** 独立来源下限，默认 2 */
  min_independent?: number;
}

export interface SourceDuplicate {
  source_id: string;
  duplicate_of: string;
  reason: "same_origin" | "same_content" | "same_url";
}

export interface FieldConflict {
  field: string;
  values: { source_id: string; origin: string; value: string | number }[];
}

export interface ReconcileResult {
  ok: boolean;
  independent: SourceRecord[];
  duplicates: SourceDuplicate[];
  stale: string[];
  independent_origins: string[];
  support: number;
  refute: number;
  neutral: number;
  /** support / (support + refute)；无正反立场时为 0 */
  agreement_ratio: number;
  field_conflicts: FieldConflict[];
  verdict_signal: "supported" | "contradicted" | "inconclusive";
  reasons: string[];
  evidence: VerdictEvidence[];
}

const DAY_MS = 24 * 60 * 60 * 1000;
const TRACKING_KEYS = ["utm_", "spm", "fbclid", "gclid", "ref", "from"];

/** URL 规范化：去协议 / www / 末尾斜杠 / 跟踪参数，用于转载识别 */
export function canonicalUrl(url: string): string {
  let value = url.trim().toLowerCase().split("#", 1)[0];
  value = value.replace(/^https?:\/\//, "").replace(/^www\./, "");
  const queryIndex = value.indexOf("?");
  const path = (queryIndex >= 0 ? value.slice(0, queryIndex) : value).replace(/\/+$/, "");
  if (queryIndex < 0) return path;
  const kept = value
    .slice(queryIndex + 1)
    .split("&")
    .filter((pair) => {
      const key = pair.split("=", 1)[0];
      return !TRACKING_KEYS.some((tracking) =>
        tracking.endsWith("_") ? key.startsWith(tracking) : key === tracking,
      );
    })
    .sort();
  return kept.length > 0 ? `${path}?${kept.join("&")}` : path;
}

function sameValue(
  left: string | number,
  right: string | number,
  tolerance: number,
): boolean {
  if (typeof left === "number" && typeof right === "number") {
    const scale = Math.max(1, Math.abs(left), Math.abs(right));
    return Math.abs(left - right) <= tolerance * scale;
  }
  return String(left).trim() === String(right).trim();
}

interface FieldEntry {
  source_id: string;
  origin: string;
  value: string | number;
}

function findFieldConflicts(
  sources: SourceRecord[],
  tolerance: number,
): FieldConflict[] {
  const byField = new Map<string, FieldEntry[]>();
  for (const source of sources) {
    for (const [field, value] of Object.entries(source.fields ?? {})) {
      const entries = byField.get(field) ?? [];
      entries.push({ source_id: source.source_id, origin: source.origin, value });
      byField.set(field, entries);
    }
  }

  const conflicts: FieldConflict[] = [];
  for (const [field, entries] of byField) {
    const groups: { representative: string | number; size: number }[] = [];
    for (const entry of entries) {
      const hit = groups.find((group) =>
        sameValue(group.representative, entry.value, tolerance),
      );
      if (hit) hit.size += 1;
      else groups.push({ representative: entry.value, size: 1 });
    }
    if (groups.length > 1) {
      conflicts.push({ field, values: entries });
    }
  }
  return conflicts;
}

/**
 * 跨源对账主入口（纯函数）。
 * 判据：
 * - 独立来源 < min → inconclusive；
 * - 存在字段冲突 → inconclusive（交人工或补证据，不强行多数决）；
 * - 反证来源达到下限且多于支持 → contradicted；
 * - 支持来源达到下限且多于反证 → supported；
 * - 其余 → inconclusive。
 */
export function reconcileSources(
  sources: SourceRecord[],
  options: ReconcileOptions = {},
): ReconcileResult {
  const now = options.now ?? Date.now();
  const maxAge = options.max_age_ms ?? 30 * DAY_MS;
  const tolerance = options.numeric_tolerance ?? 0;
  const minIndependent = options.min_independent ?? 2;

  const duplicates: SourceDuplicate[] = [];
  const stale: string[] = [];
  const independent: SourceRecord[] = [];
  const seenOrigin = new Map<string, string>();
  const seenHash = new Map<string, string>();
  const seenUrl = new Map<string, string>();

  for (const source of sources) {
    if (
      typeof source.published_at === "number" &&
      now - source.published_at > maxAge
    ) {
      stale.push(source.source_id);
      continue;
    }
    const hashKey = source.content_hash?.trim();
    if (hashKey && seenHash.has(hashKey)) {
      duplicates.push({
        source_id: source.source_id,
        duplicate_of: seenHash.get(hashKey)!,
        reason: "same_content",
      });
      continue;
    }
    const urlKey = source.url ? canonicalUrl(source.url) : "";
    if (urlKey && seenUrl.has(urlKey)) {
      duplicates.push({
        source_id: source.source_id,
        duplicate_of: seenUrl.get(urlKey)!,
        reason: "same_url",
      });
      continue;
    }
    const originKey = source.origin.trim().toLowerCase();
    if (seenOrigin.has(originKey)) {
      duplicates.push({
        source_id: source.source_id,
        duplicate_of: seenOrigin.get(originKey)!,
        reason: "same_origin",
      });
      continue;
    }

    independent.push(source);
    seenOrigin.set(originKey, source.source_id);
    if (hashKey) seenHash.set(hashKey, source.source_id);
    if (urlKey) seenUrl.set(urlKey, source.source_id);
  }

  const support = independent.filter((item) => item.stance === "support").length;
  const refute = independent.filter((item) => item.stance === "refute").length;
  const neutral = independent.filter((item) => item.stance === "neutral").length;
  const resolved = support + refute;
  const fieldConflicts = findFieldConflicts(independent, tolerance);
  const reasons: string[] = [];

  let signal: ReconcileResult["verdict_signal"];
  if (independent.length < minIndependent) {
    signal = "inconclusive";
    reasons.push("insufficient_independent_sources");
  } else if (fieldConflicts.length > 0) {
    signal = "inconclusive";
    reasons.push("field_conflict");
  } else if (refute >= minIndependent && refute > support) {
    signal = "contradicted";
    reasons.push("majority_refute");
  } else if (support >= minIndependent && support > refute) {
    signal = "supported";
    reasons.push("majority_support");
  } else {
    signal = "inconclusive";
    reasons.push("no_consensus");
  }
  if (duplicates.length > 0) reasons.push("duplicates_removed");
  if (stale.length > 0) reasons.push("stale_excluded");

  const evidence: VerdictEvidence[] = independent.map((source) => ({
    ref: source.url || `source:${source.source_id}`,
    kind: "source",
    origin: source.origin,
    fingerprint: source.content_hash,
    fresh: true,
    replayable: true,
    contradicts: source.stance === "refute",
  }));

  return {
    ok: signal !== "inconclusive",
    independent,
    duplicates,
    stale,
    independent_origins: independent.map((item) => item.origin),
    support,
    refute,
    neutral,
    agreement_ratio: resolved > 0 ? support / resolved : 0,
    field_conflicts: fieldConflicts,
    verdict_signal: signal,
    reasons,
    evidence,
  };
}

export interface U3VerdictInput {
  task_id: string;
  trace_id: string;
  claim: string;
  sources: SourceRecord[];
  /** REA 结构事实证据，与采集证据一起构成三角验证 */
  rea?: VerdictEvidence[];
  reconciliation?: ReconcileOptions;
  confidence?: number | null;
  poe_score?: number;
  dissent?: string[];
}

/** 对账结果 → U3 裁决。对账判 inconclusive 时不得因来源数量"凑成" supported。 */
export function buildU3Verdict(input: U3VerdictInput): {
  reconciliation: ReconcileResult;
  verdict: UncertaintyVerdict;
  issues: VerdictIssue[];
} {
  const reconciliation = reconcileSources(input.sources, input.reconciliation);
  const evidence = [...reconciliation.evidence, ...(input.rea ?? [])];
  const assessed = assessVerdict({
    task_id: input.task_id,
    trace_id: input.trace_id,
    claim: input.claim,
    level: "U3",
    evidence,
    methods: ["collect", "reconcile", ...(input.rea?.length ? ["rea"] : [])],
    confidence: input.confidence ?? null,
    poe_score: input.poe_score,
    dissent: input.dissent,
  });

  const issues = [...assessed.issues];
  let verdict = assessed.verdict;

  if (
    reconciliation.verdict_signal === "inconclusive" &&
    verdict.verdict === "supported"
  ) {
    verdict = {
      ...verdict,
      verdict: "inconclusive",
      dissent: [...verdict.dissent, ...reconciliation.reasons],
    };
    issues.push({
      level: "warning",
      code: "reconcile_inconclusive",
      message: `跨源对账未收敛：${reconciliation.reasons.join(" / ")}`,
    });
  }

  if (
    reconciliation.verdict_signal === "contradicted" &&
    verdict.verdict !== "contradicted"
  ) {
    verdict = { ...verdict, verdict: "contradicted" };
  }

  return { reconciliation, verdict, issues };
}

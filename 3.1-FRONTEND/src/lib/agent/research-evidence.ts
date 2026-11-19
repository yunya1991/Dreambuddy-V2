/**
 * 研究证据归一（MERS / 数据研究看板 → 对话与裁决）。
 *
 * 纪律（对齐 54-L1 SPEC §14.7 / §15.6）：
 * - 只消费后端只读投影，不在前端重算任何统计量；
 * - 只陈述历史统计关系，不产出 direction / order / position 字段；
 * - 产物缺失或降级一律 FAIL-OPEN，由调用方如实标注，不阻断对话。
 */

import type { VisualSpec } from "@/components/visual/types";
import { l1BaseUrl } from "../l1-base-url";

export interface ResearchEvidenceItem {
  relation: string;
  method: string | null;
  transform: string | null;
  horizon: number;
  rank_ic: number | null;
  hit_rate: number | null;
  base_rate: number | null;
  holdout_hit_rate: number | null;
  p_adj: number | null;
  n: number;
  status: string;
  gate_pass: number;
}

export interface ResearchDiscoveryItem {
  method: string | null;
  series: string | null;
  transform: string | null;
  horizon: number;
  rank_ic: number | null;
  holdout_ic: number | null;
  p_adj: number | null;
  stability: number | null;
  n: number;
  status: string;
  eval_at: string | null;
  data_version: string | null;
}

export interface ResearchEvidence {
  available: boolean;
  target: string;
  as_of: string | null;
  eval_at: string | null;
  data_version: string | null;
  status: "ok" | "candidate_only" | "unavailable";
  rows: number;
  evaluable: number;
  gate_pass: number;
  stable: number;
  counts: { stable: number; candidate: number; decayed: number; other: number };
  top: ResearchEvidenceItem[];
  discovery: ResearchDiscoveryItem[];
  caveats: string[];
  reason?: string;
}

export interface ResearchEvidenceOptions {
  horizon?: number;
  timeoutMs?: number;
}

const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; value: ResearchEvidence }>();

function num(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function int(value: unknown): number {
  const parsed = num(value);
  return parsed === null ? 0 : Math.round(parsed);
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** A 股/美股代码没有 MERS 覆盖，直接返回不可用，避免无意义请求。 */
function isMersUnsupported(symbol: string): boolean {
  return /^\d/.test(symbol) || symbol.includes(".");
}

function unavailable(target: string, reason: string): ResearchEvidence {
  return {
    available: false,
    target,
    as_of: null,
    eval_at: null,
    data_version: null,
    status: "unavailable",
    rows: 0,
    evaluable: 0,
    gate_pass: 0,
    stable: 0,
    counts: { stable: 0, candidate: 0, decayed: 0, other: 0 },
    top: [],
    discovery: [],
    caveats: [reason],
    reason,
  };
}

function normalizeTargetBlock(block: Record<string, unknown>): ResearchEvidence {
  const target = String(block.target ?? "").trim().toUpperCase();
  const available = block.available === true;
  if (!available) {
    return unavailable(target, String(block.reason ?? "MERS 未覆盖该标的"));
  }

  const countsRaw = (block.counts ?? {}) as Record<string, unknown>;
  const top = Array.isArray(block.top)
    ? (block.top as Record<string, unknown>[]).map((row) => ({
        relation: String(row.relation ?? "unmapped"),
        method: str(row.method),
        transform: str(row.transform),
        horizon: int(row.horizon),
        rank_ic: num(row.rank_ic),
        hit_rate: num(row.hit_rate),
        base_rate: num(row.base_rate),
        holdout_hit_rate: num(row.holdout_hit_rate),
        p_adj: num(row.p_adj),
        n: int(row.n),
        status: String(row.status ?? "candidate"),
        gate_pass: int(row.gate_pass),
      }))
    : [];
  const discovery = Array.isArray(block.discovery)
    ? (block.discovery as Record<string, unknown>[]).map((row) => ({
        method: str(row.method),
        series: str(row.series),
        transform: str(row.transform),
        horizon: int(row.horizon),
        rank_ic: num(row.rank_ic),
        holdout_ic: num(row.holdout_ic),
        p_adj: num(row.p_adj),
        stability: num(row.stability),
        n: int(row.n),
        status: String(row.status ?? "candidate"),
        eval_at: str(row.eval_at),
        data_version: str(row.data_version),
      }))
    : [];

  const gatePass = int(block.gate_pass);
  const stable = int(block.stable);
  const status: ResearchEvidence["status"] =
    gatePass > 0 && stable > 0 ? "ok" : "candidate_only";

  return {
    available: true,
    target,
    as_of: null,
    eval_at: null,
    data_version:
      discovery.find((item) => item.data_version)?.data_version ?? null,
    status,
    rows: int(block.rows),
    evaluable: int(block.evaluable),
    gate_pass: gatePass,
    stable,
    counts: {
      stable: int(countsRaw.stable),
      candidate: int(countsRaw.candidate),
      decayed: int(countsRaw.decayed),
      other: int(countsRaw.other),
    },
    top,
    discovery,
    caveats: Array.isArray(block.caveats)
      ? (block.caveats as unknown[]).map((item) => String(item))
      : [],
  };
}

/**
 * 取单个标的的研究证据（MERS 注册表 + 最近一期发现）。
 * 8s 超时、60s 缓存、FAIL-OPEN；不产出任何方向字段。
 */
export async function fetchResearchEvidence(
  symbol: string,
  options: ResearchEvidenceOptions = {},
): Promise<ResearchEvidence> {
  const raw = String(symbol ?? "").trim();
  const target = raw.split("/")[0].toUpperCase();
  if (!target) return unavailable("", "未提供标的");
  if (isMersUnsupported(target)) {
    return unavailable(target, "MERS 仅覆盖加密资产，该标的无关系评估");
  }

  const horizon = Math.max(1, Math.round(options.horizon ?? 1));
  const cacheKey = `${target}|${horizon}`;
  const hit = cache.get(cacheKey);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) return hit.value;

  const timeoutMs = Math.max(1000, options.timeoutMs ?? 8000);
  try {
    const url = new URL("/api/visual/research", l1BaseUrl());
    url.searchParams.set("top", "12");
    url.searchParams.set("target", target);
    url.searchParams.set("horizon", String(horizon));
    const signal =
      typeof AbortSignal.timeout === "function"
        ? AbortSignal.timeout(timeoutMs)
        : undefined;
    const res = await fetch(url, {
      cache: "no-store",
      headers: { Accept: "application/json" },
      ...(signal ? { signal } : {}),
    });
    const json = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (!res.ok || !json) return unavailable(target, `研究接口不可用（http_${res.status}）`);

    const block = json.target as Record<string, unknown> | undefined;
    if (!block) return unavailable(target, "研究接口未返回 target 区块");

    const evidence = normalizeTargetBlock(block);
    evidence.as_of = str(json.as_of);
    evidence.eval_at = str((json.source as Record<string, unknown> | undefined)?.eval_at);
    if (!evidence.data_version) {
      evidence.data_version = str(
        (json.source as Record<string, unknown> | undefined)?.data_version,
      );
    }
    if (evidence.available) cache.set(cacheKey, { at: Date.now(), value: evidence });
    return evidence;
  } catch (e) {
    return unavailable(
      target,
      `研究证据获取失败：${e instanceof Error ? e.message : "unknown"}`,
    );
  }
}

/** ≤600 字符的紧凑引用块，供 pipeline 输出与提示词使用。 */
export function renderResearchBrief(evidence: ResearchEvidence): string {
  const header = `研究证据[${evidence.target || "?"}] as_of=${evidence.as_of || "—"} data_version=${evidence.data_version || "—"} status=${evidence.status} gate_pass=${evidence.gate_pass} stable=${evidence.stable} rows=${evidence.rows}`;
  const top = evidence.top
    .slice(0, 3)
    .map(
      (item) =>
        `${item.relation}/${item.method ?? "?"} h=${item.horizon} RankIC=${fmt(item.rank_ic)} 命中${fmt(item.hit_rate)}/基线${fmt(item.base_rate)} holdout=${fmt(item.holdout_hit_rate)} n=${item.n} (${item.status}, gate_pass=${item.gate_pass})`,
    );
  const discovery = evidence.discovery
    .slice(0, 2)
    .map(
      (item) =>
        `发现 ${item.method ?? "?"} h=${item.horizon} RankIC=${fmt(item.rank_ic)} holdout_ic=${fmt(item.holdout_ic)} p_adj=${fmt(item.p_adj)}`,
    );
  const caveats = evidence.caveats.length
    ? evidence.caveats.map((item) => `[注意] ${item}`)
    : [];
  const text = [header, ...top, ...discovery, ...caveats].filter(Boolean).join("\n");
  return text.length > 600 ? `${text.slice(0, 597)}...` : text;
}

function fmt(value: number | null): string {
  return value === null ? "—" : String(Math.round(value * 10000) / 10000);
}

/** 深链：研究页按标的预填。 */
export function researchLink(symbol: string): string {
  const target = String(symbol ?? "").split("/")[0].toUpperCase();
  return `/dashboard/visual/research?base=${encodeURIComponent(target)}`;
}

const VISUAL_CAVEAT = "仅历史统计关系，不代表未来收益或方向";

/**
 * 从 `/api/visual/research` 响应直接构建图表（供能力层复用，避免二次请求）。
 * 只做展示投影，不重算统计量。
 */
export function buildResearchVisualsFromPayload(
  payload: Record<string, unknown>,
): VisualSpec[] {
  const block = payload?.target as Record<string, unknown> | undefined;
  if (!block || block.available !== true) return [];
  const evidence = normalizeTargetBlock(block);
  evidence.as_of = str(payload.as_of);
  return buildResearchVisuals(evidence);
}

/**
 * 研究证据 → 看板同源 VisualSpec（表格；有跨期限发现时补矩阵）。
 * 只做展示投影，不重算统计量。
 */
export function buildResearchVisuals(evidence: ResearchEvidence): VisualSpec[] {
  if (!evidence.available || evidence.top.length === 0) return [];

  const table: VisualSpec = {
    id: `research-${evidence.target}`,
    kind: "table",
    spec_version: "1.0",
    title: `${evidence.target} 关系证据（历史统计）`,
    source_capability: "research.snapshot",
    n_scope: "per_row",
    dataset: {
      columns: [
        { key: "relation", label: "关系类", type: "string" },
        { key: "method", label: "方法", type: "string" },
        { key: "horizon", label: "期限", type: "number" },
        { key: "rank_ic", label: "RankIC", type: "number" },
        { key: "hit_rate", label: "命中率", type: "percent" },
        { key: "base_rate", label: "基线", type: "percent" },
        { key: "holdout_hit_rate", label: "样本外命中", type: "percent" },
        { key: "status", label: "状态", type: "string" },
      ],
      rows: evidence.top.map((item) => ({ ...item })),
      groups: [],
    },
    encodings: {},
    quality_ref: "quality",
    truncated: false,
    caveat: VISUAL_CAVEAT,
  };

  const horizons = [...new Set(evidence.discovery.map((item) => item.horizon))].sort(
    (a, b) => a - b,
  );
  const methods = [...new Set(evidence.discovery.map((item) => item.method ?? "?"))];
  if (horizons.length < 2 || methods.length === 0) return [table];

  const values = methods.map((method) =>
    horizons.map((horizon) => {
      const row = evidence.discovery.find(
        (item) => (item.method ?? "?") === method && item.horizon === horizon,
      );
      return row?.rank_ic ?? null;
    }),
  );
  const matrix: VisualSpec = {
    id: `research-discovery-${evidence.target}`,
    kind: "matrix",
    spec_version: "1.0",
    title: `${evidence.target} 发现候选（方法 × 期限 RankIC）`,
    source_capability: "research.snapshot",
    n_scope: "per_cell",
    dataset: {
      row_labels: methods,
      col_labels: horizons.map((item) => `h=${item}`),
      values,
    },
    encodings: {},
    quality_ref: "quality",
    truncated: false,
    caveat: VISUAL_CAVEAT,
  };
  return [table, matrix];
}

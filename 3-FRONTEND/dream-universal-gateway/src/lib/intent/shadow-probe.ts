/**
 * shadow-probe.ts — 影子对比探针
 * PROP-20260829-C · Phase 2（Z3 §2.2/2.3 实现）
 *
 * 语义：
 *  - 旧路径结果为准（chat route fc_shadow 分支先跑 recognizeIntentLLM）；
 *    统一管线仅并行执行并记录差异，不改变任何对外行为。
 *  - 预算上限（Z3 §2.3 硬编码）：SHADOW_BUDGET=200 样本，达到自动停影子
 *    （以磁盘样本数为准，跨进程重启仍生效）；影子 FC 调用 max_tokens≤50。
 *  - 记忆污染封闭：影子调用传 recordMemory=false，统一管线识别结果
 *    不写入 intent-memory（P3 价值过滤/隔离仓建成前不得积累样本）。
 *  - 任何影子失败静默吞掉，绝不影响主路径。
 *
 * 产物：GW/intent-shadow/shadow.jsonl（appendFileSync 原子追加，逐行 JSON）。
 */
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { recognizeIntentUnified } from './intent-unified';
import { canonToLegacy, UnifiedIntentResult } from './intent-schema';

/** 硬编码预算：样本数达到即自动停影子（Z3 §2.3） */
export const SHADOW_BUDGET = 200;
/**
 * 硬编码上限：影子 FC 调用 max_tokens（Z3 §2.3 原设计 ≤50，实测修正为 150）
 * 实证依据（2026-08-29，qwen3.8-max + enable_thinking:false）：
 *   FC tool_call 真实 completion_tokens = 91~99（4 条样例：98/99/91/97）；
 *   50 会截断 arguments JSON → FC 解析失败 → 影子全部落规则兜底，探针失去意义。
 *   150 = 观测峰值 99 × 1.5 安全边际。200 样本 × ~100 token ≈ ¥1-2（Z3 预算内）。
 */
export const SHADOW_MAX_TOKENS= 150;
/** 影子调用超时：不拖累主路径（主路径不 await 影子） */
export const SHADOW_TIMEOUT_MS = 10_000;

const SHADOW_DIR = join(process.cwd(), 'intent-shadow');
const SHADOW_FILE = join(SHADOW_DIR, 'shadow.jsonl');

/** 旧路径结果的最小结构约束（chat/task 各自的 IntentResult 均满足） */
export interface LegacyLikeResult {
  intent: string;
  confidence?: number;
  method?: string;
  intent_method_actual?: string;
}

export interface ShadowRecord {
  ts: string;
  seq: number;
  input: string;               // 截断 200 字符，避免长文本膨胀
  user_role: string;
  legacy_intent: string;
  legacy_method?: string;
  legacy_confidence?: number;
  unified_intent?: string;     // 正典 35 型
  unified_legacy?: string;     // 正典降级 legacy 15 型（与旧路径对比的口径）
  unified_method?: string;
  unified_loop?: string;
  match: boolean | null;       // null = 影子调用失败无法对比
  latency_ms: number;
  error?: string;
}

let cachedCount = -1;

/** 当前影子样本数（磁盘行数为准，进程内缓存） */
export function shadowSampleCount(force = false): number {
  if (cachedCount >= 0 && !force) return cachedCount;
  try {
    if (!existsSync(SHADOW_FILE)) {
      cachedCount = 0;
    } else {
      const txt = readFileSync(SHADOW_FILE, 'utf8');
      cachedCount = txt.split('\n').filter(l => l.trim().length > 0).length;
    }
  } catch {
    cachedCount = 0;
  }
  return cachedCount;
}

/** 预算是否耗尽（Z3 §2.3 自动停影子判据） */
export function shadowBudgetExhausted(): boolean {
  return shadowSampleCount() >= SHADOW_BUDGET;
}

/**
 * 影子探针主体。调用方约定：主路径不得 await 本函数
 * （chat route: `void runShadowProbe(...).catch(() => {})`）。
 */
export async function runShadowProbe(
  message: string,
  context: Parameters<typeof recognizeIntentUnified>[1],
  legacy: LegacyLikeResult
): Promise<void> {
  try {
    if (shadowBudgetExhausted()) return;  // 预算上限：自动停影子
    const t0 = Date.now();
    let unified: UnifiedIntentResult | undefined;
    let error: string | undefined;
    try {
      unified = await recognizeIntentUnified(message, context, {
        method: 'fc',
        timeoutMs: SHADOW_TIMEOUT_MS,
        fcMaxTokens: SHADOW_MAX_TOKENS,
        recordMemory: false,   // 记忆污染封闭：影子期不落 intent-memory
        uid: 'shadow-probe',
      });
    } catch (e) {
      error = (e as Error).message;
    }
    const unifiedLegacy = unified ? canonToLegacy(unified.intent) : undefined;
    const rec: ShadowRecord = {
      ts: new Date().toISOString(),
      seq: shadowSampleCount() + 1,
      input: message.slice(0, 200),
      user_role: context?.user_role ?? 'FREE',
      legacy_intent: legacy.intent,
      legacy_method: legacy.intent_method_actual ?? legacy.method,
      legacy_confidence: legacy.confidence,
      unified_intent: unified?.intent,
      unified_legacy: unifiedLegacy,
      unified_method: unified?.method,
      unified_loop: unified?.loop,
      match: unified ? unifiedLegacy === legacy.intent : null,
      latency_ms: Date.now() - t0,
      ...(error ? { error } : {}),
    };
    if (!existsSync(SHADOW_DIR)) mkdirSync(SHADOW_DIR, { recursive: true });
    appendFileSync(SHADOW_FILE, JSON.stringify(rec) + '\n');  // 原子追加
    cachedCount = rec.seq;
  } catch {
    // 影子失败静默吞掉，绝不影响主路径
  }
}

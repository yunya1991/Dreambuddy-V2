/**
 * l1-answer-guard — AI Agent 模式下对 L1 确定性直答的 L2 门禁
 *
 * 设计：DESIGN-20261118-L1答案L2门禁-v0.1.md
 *   G1 规则门（零 token）：空答/占位、意图-答案结构、实体一致、方向矛盾 → fail；
 *                        日期过期、多指标覆盖不足 → uncertain。
 *   G3 LLM 轻审：仅灰区调用，judge 由调用方注入（模型/超时/计费留在 route 层）。
 *
 * 约束：本模块不直接调用模型、不发请求；纯函数 + 本地词表读取，便于单测。
 */

import * as fs from 'fs';
import * as path from 'path';
import { FRONTEND_DIR } from './runtime-paths';

export type GateVerdict = 'pass' | 'fail' | 'uncertain' | 'timeout';

export interface GateInput {
  message: string;
  intent: string;
  answer: string;
  data?: unknown;
  routeSignal?: { decision?: string; reasons?: string[]; route_confidence?: number };
}

export interface GateResult {
  verdict: GateVerdict;
  reasons: string[];
  missing: string[];
  gateMs: number;
  judgeMs?: number;
}

export interface GateOptions {
  allowJudge: boolean;
  /** 返回 judge 原始文本（应为 JSON）；抛错/超时由 guard 统一处理 */
  judge?: (prompt: string) => Promise<string>;
}

// ============================================================
// 实体词表：直接复用 entity_aliases.json（随别名扩张自动生效）
// ============================================================

interface AliasTable {
  /** alias(小写) -> 标准符号 */
  aliasToSymbol: Map<string, string>;
  /** symbol -> 全部别名（含符号本身） */
  symbolToAliases: Map<string, string[]>;
  /** 按长度倒序的别名列表，避免「比特币」被「比特」截断 */
  orderedAliases: string[];
}

let cachedTable: AliasTable | null = null;

export function loadAliasTable(): AliasTable {
  if (cachedTable) return cachedTable;

  const file = path.join(FRONTEND_DIR, 'scripts', 'entity_aliases.json');
  const aliasToSymbol = new Map<string, string>();
  const symbolToAliases = new Map<string, string[]>();

  try {
    const raw = JSON.parse(fs.readFileSync(file, 'utf8')) as Record<string, string[]>;
    for (const [symbol, aliases] of Object.entries(raw)) {
      const all = [symbol, ...(Array.isArray(aliases) ? aliases : [])];
      symbolToAliases.set(symbol, all);
      for (const alias of all) {
        const key = String(alias).toLowerCase();
        if (key) aliasToSymbol.set(key, symbol);
      }
    }
  } catch (e) {
    console.warn('[L1Gate] entity_aliases.json 读取失败，实体规则降级:', e instanceof Error ? e.message : e);
  }

  const orderedAliases = [...aliasToSymbol.keys()]
    .filter((a) => a.length >= 2)
    .sort((a, b) => b.length - a.length);

  cachedTable = { aliasToSymbol, symbolToAliases, orderedAliases };
  return cachedTable;
}

/** 从用户问题中抽取实体（返回标准符号，去重） */
export function extractEntities(message: string): string[] {
  const table = loadAliasTable();
  const lower = (message || '').toLowerCase();
  const found: string[] = [];
  const consumed = new Set<string>();

  for (const alias of table.orderedAliases) {
    if (!lower.includes(alias)) continue;
    const symbol = table.aliasToSymbol.get(alias);
    if (!symbol) continue;
    // 已被更长的别名覆盖的区间不再重复计（如「比特币」命中后跳过「比特」）
    if (consumed.has(alias)) continue;
    consumed.add(alias);
    if (!found.includes(symbol)) found.push(symbol);
  }
  return found;
}

/** 答案是否提及该实体（符号或任一别名） */
function answerMentions(answer: string, symbol: string): boolean {
  const table = loadAliasTable();
  const lower = (answer || '').toLowerCase();
  const aliases = table.symbolToAliases.get(symbol) || [symbol];
  return aliases.some((a) => lower.includes(String(a).toLowerCase()));
}

// ============================================================
// G1 规则
// ============================================================

const PLACEHOLDER_PATTERN = /暂无数据|未知|加载中|分析中|处理中|计算中|N\/A|not available|loading/i;
const NUMBER_PATTERN = /\d[\d,]*\.?\d*/;
const EXPLICIT_DATE_PATTERN = /(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})/;

const METRIC_KEYWORDS = [
  '资金费率', '持仓量', '多空比', '恐惧贪婪', '恐慌贪婪', '市值', '波动率',
  '成交量', '换手', '最高', '最低', '涨跌', '支撑', '阻力',
];

const BEARISH_WORDS = /跌|下跌|回调|回落|走弱|看空|空头/;
const BULLISH_WORDS = /涨|上涨|反弹|走强|看多|多头/;

function isPlaceholder(answer: string): boolean {
  const head = (answer || '').slice(0, 80);
  return PLACEHOLDER_PATTERN.test(head);
}

function isToday(dateText: string): boolean {
  const m = dateText.match(EXPLICIT_DATE_PATTERN);
  if (!m) return true;
  const now = new Date();
  return (
    Number(m[1]) === now.getFullYear() &&
    Number(m[2]) === now.getMonth() + 1 &&
    Number(m[3]) === now.getDate()
  );
}

/** R2：意图-答案结构一致性 */
function checkIntentStructure(input: GateInput, entities: string[]): string[] {
  const answer = input.answer || '';
  const reasons: string[] = [];
  const missing: string[] = [];

  switch (input.intent) {
    case 'price_query': {
      if (!NUMBER_PATTERN.test(answer)) {
        reasons.push('R2:missing_price');
        missing.push('价格数值');
      }
      if (entities.length > 0 && !entities.some((e) => answerMentions(answer, e))) {
        reasons.push('R3:entity_mismatch');
        missing.push(entities.join('/'));
      }
      break;
    }
    case 'metric_series': {
      const nums = answer.match(/\d[\d,]*\.?\d*/g) || [];
      if (nums.length < 3 && !/历史|序列|近\d+|趋势/.test(answer)) {
        reasons.push('R2:insufficient_series');
        missing.push('时间序列数据点');
      }
      break;
    }
    case 'data_insight':
    case 'data_query': {
      if (entities.length > 0 && !entities.some((e) => answerMentions(answer, e))) {
        reasons.push('R3:entity_mismatch');
        missing.push(entities.join('/'));
      }
      if (!NUMBER_PATTERN.test(answer)) {
        reasons.push('R2:missing_value');
        missing.push('数值字段');
      }
      break;
    }
    case 'artifact_query':
    case 'doc_search': {
      if (!/来源|引用|文档|知识库|出处|source|ref/i.test(answer)) {
        reasons.push('R2:missing_source');
        missing.push('来源引用');
      }
      break;
    }
    default:
      break;
  }

  return reasons;
}

/** R4：方向矛盾（问题显式看跌，答案只讲上涨） */
function checkDirection(input: GateInput): string[] {
  const q = input.message || '';
  const a = input.answer || '';
  if (BEARISH_WORDS.test(q) && !BEARISH_WORDS.test(a) && BULLISH_WORDS.test(a)) {
    return ['R4:direction_conflict'];
  }
  if (BULLISH_WORDS.test(q) && BEARISH_WORDS.test(q) === false && !BULLISH_WORDS.test(a) && BEARISH_WORDS.test(a)) {
    return ['R4:direction_conflict'];
  }
  return [];
}

/** R6：多指标覆盖（客观缺失 → 直接 fail，无需 judge） */
function checkCoverage(input: GateInput): { reasons: string[]; missing: string[] } {
  const reasons: string[] = [];
  const missing: string[] = [];
  const answer = input.answer || '';
  const asked = METRIC_KEYWORDS.filter((k) => (input.message || '').includes(k));
  if (asked.length >= 2) {
    const lack = asked.filter((k) => !answer.includes(k));
    if (lack.length > 0) {
      reasons.push('R6:partial_coverage');
      missing.push(...lack);
    }
  }
  return { reasons, missing };
}

/** R5：灰区（交 LLM 轻审） */
function checkSoftRules(input: GateInput): { reasons: string[]; missing: string[] } {
  const reasons: string[] = [];
  const missing: string[] = [];
  const answer = input.answer || '';

  // R5：答案里出现了明确的旧日期
  const dateMatch = answer.match(EXPLICIT_DATE_PATTERN);
  if (dateMatch && !isToday(dateMatch[0])) {
    reasons.push('R5:stale_data');
    missing.push('最新时间戳');
  }

  return { reasons, missing };
}

export function runG1(input: GateInput): { verdict: GateVerdict; reasons: string[]; missing: string[] } {
  const answer = (input.answer || '').trim();
  const entities = extractEntities(input.message);

  if (!answer || isPlaceholder(answer)) {
    return { verdict: 'fail', reasons: ['R1:empty_or_placeholder'], missing: ['有效答案'] };
  }

  const coverage = checkCoverage(input);
  const hard = [...checkIntentStructure(input, entities), ...checkDirection(input), ...coverage.reasons];
  if (hard.length > 0) {
    const missing = entities.length
      ? [...entities, ...coverage.missing]
      : [...coverage.missing];
    return { verdict: 'fail', reasons: hard, missing };
  }

  const soft = checkSoftRules(input);
  if (soft.reasons.length > 0) {
    return { verdict: 'uncertain', reasons: soft.reasons, missing: soft.missing };
  }

  return { verdict: 'pass', reasons: [], missing: [] };
}

// ============================================================
// G3 Judge prompt
// ============================================================

export function buildJudgePrompt(input: GateInput, g1: { reasons: string[]; missing: string[] }): string {
  const dataPreview = (() => {
    try {
      return JSON.stringify(input.data ?? null).slice(0, 800);
    } catch {
      return 'null';
    }
  })();

  return [
    '你是答案审核员。只判断两件事：',
    '1) 这条答案是否真正回答了用户的问题；',
    '2) 答案是否与给定数据矛盾。',
    '不评价文风，不补充新事实，不做推理延展。',
    '',
    '【用户问题】',
    input.message.slice(0, 1000),
    '',
    `【L1 意图】${input.intent}`,
    '',
    '【L1 答案】',
    (input.answer || '').slice(0, 1500),
    '',
    '【结构化数据】',
    dataPreview,
    '',
    `【规则门未决原因】${g1.reasons.join(', ') || 'none'}；缺失项：${g1.missing.join('、') || 'none'}`,
    '',
    '只输出 JSON，不要输出任何其他文本：',
    '{"verdict":"pass|fail","reasons":["..."],"missing":["..."]}',
  ].join('\n');
}

function parseJudgeOutput(text: string): { verdict: 'pass' | 'fail'; reasons: string[]; missing: string[] } {
  const start = text.indexOf('{');
  const end = text.lastIndexOf('}');
  if (start === -1 || end <= start) throw new Error('judge_output_not_json');
  const obj = JSON.parse(text.slice(start, end + 1)) as {
    verdict?: string;
    reasons?: unknown;
    missing?: unknown;
  };
  const verdict = obj.verdict === 'fail' ? 'fail' : 'pass';
  return {
    verdict,
    reasons: Array.isArray(obj.reasons) ? obj.reasons.map(String).slice(0, 5) : [],
    missing: Array.isArray(obj.missing) ? obj.missing.map(String).slice(0, 5) : [],
  };
}

// ============================================================
// 入口
// ============================================================

const JUDGE_TIMEOUT_MS = 15_000;

export async function reviewL1Answer(input: GateInput, opts: GateOptions): Promise<GateResult> {
  const started = Date.now();
  const g1 = runG1(input);

  if (g1.verdict === 'pass' || g1.verdict === 'fail') {
    return { ...g1, gateMs: Date.now() - started };
  }

  // uncertain 且未允许 judge → 保守放行（避免无谓接管）
  if (!opts.allowJudge || !opts.judge) {
    return { ...g1, gateMs: Date.now() - started };
  }

  const judgeStart = Date.now();
  try {
    const text = await Promise.race([
      opts.judge(buildJudgePrompt(input, g1)),
      new Promise<string>((_, reject) =>
        setTimeout(() => reject(new Error('judge_timeout')), JUDGE_TIMEOUT_MS),
      ),
    ]);
    const judged = parseJudgeOutput(text);
    return {
      verdict: judged.verdict,
      reasons: judged.verdict === 'fail' ? judged.reasons : [],
      missing: judged.verdict === 'fail' ? judged.missing : [],
      gateMs: Date.now() - started,
      judgeMs: Date.now() - judgeStart,
    };
  } catch (e) {
    // FAIL-OPEN：judge 不可用 → 放行并打标，不阻断主链路
    return {
      verdict: 'timeout',
      reasons: [...g1.reasons, e instanceof Error ? e.message : 'judge_failed'],
      missing: g1.missing,
      gateMs: Date.now() - started,
      judgeMs: Date.now() - judgeStart,
    };
  }
}

/** 接管上下文：注入 agent，要求先核实再答 */
export function buildTakeoverContext(input: GateInput, gate: GateResult): string {
  return [
    '[L1 直答未通过 L2 门禁]',
    `用户问题：${input.message.slice(0, 1000)}`,
    `L1 草稿：${(input.answer || '').slice(0, 1200)}`,
    `未通过原因：${gate.reasons.join(', ') || 'unknown'}`,
    `缺失项：${gate.missing.join('、') || 'unknown'}`,
    '',
    '要求：',
    '1. 先使用可用工具核实数据，再回答；',
    '2. 不要复述 L1 草稿；',
    '3. 若工具取不到数据，明确说明“暂无数据”，禁止编造。',
  ].join('\n');
}

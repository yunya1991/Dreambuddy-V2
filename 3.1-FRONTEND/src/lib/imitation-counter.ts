/**
 * ImitationCounter — 模仿计数器
 * ====================================
 * 记录"同类模仿 query→次数"，达 N 次触发 skill-creator 沉淀。
 *
 * 设计原则（SIE-SPEC §3.2.4 M-1 修复 — 循环依赖隔离边界）：
 *   1. 模仿执行的 query 不写回 TF-IDF 索引（本模块不操作 SkillSelector）
 *   2. 沉淀后标记 sedimentation_triggered=true，防重复触发
 *   3. 路径 B 不调 knowledge-ingest（本模块无该依赖）
 *   4. 历史计数不清零：即使外部索引更新导致走路径 A，计数保留
 *
 * 归一化规则（SIE-SPEC §3.4 m-2 修复 — 纯正则，零 LLM 依赖，对齐 HC-1）：
 *   1. 数字 → {number}
 *   2. 已知 symbol → {symbol}
 *   3. 百分比 → {pct}
 *   4. 时间表达式 → {time}
 *   5. 转小写 + 去多余空格
 *
 * 位置: 3.1-FRONTEND/src/lib/imitation-counter.ts
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// 1. 类型定义
// ============================================================

export interface ImitationRecord {
  query_pattern: string;
  count: number;
  first_seen: number;
  last_seen: number;
  document_sources: string[];
  execution_plan_examples: string[];
  sedimentation_triggered: boolean;
}

export interface IncrementResult {
  triggered: boolean;
  current_count: number;
}

// ============================================================
// 2. 配置
// ============================================================

const COUNTER_CONFIG = {
  /** 沉淀门槛 N（SIE-SPEC §3.4，默认 3，可配置） */
  get threshold(): number {
    const env = process.env.IMITATION_THRESHOLD;
    return env ? parseInt(env, 10) || 3 : 3;
  },
  /** execution_plan_examples 最大保留条数 */
  max_plan_examples: 3,
  /** 持久化文件路径 */
  get dataPath(): string {
    const candidatePaths = [
      path.resolve(process.cwd(), 'data', 'imitation-counter.json'),
      path.resolve(process.cwd(), '3.1-FRONTEND', 'data', 'imitation-counter.json'),
      path.resolve(__dirname, '..', 'data', 'imitation-counter.json'),
    ];
    for (const p of candidatePaths) {
      const dir = path.dirname(p);
      if (fs.existsSync(dir)) return p;
    }
    // fallback：用第一个候选路径，并确保目录存在
    const fallback = candidatePaths[0];
    const dir = path.dirname(fallback);
    if (!fs.existsSync(dir)) {
      try { fs.mkdirSync(dir, { recursive: true }); } catch { /* ignore */ }
    }
    return fallback;
  },
};

/** 已知 symbol 列表（来自 18-DB 配置，此处为常见交易对） */
const KNOWN_SYMBOLS = [
  '比特币', '以太坊', 'BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'ADA', 'DOGE',
  '狗狗币', '索拉纳', '瑞波币', '艾达', '莱特币', 'LTC',
  'BSV', 'DOT', '波卡', 'MATIC', 'Polygon', 'AVAX', 'LINK', 'UNI',
  'ATOM', 'ARB', 'OP', 'APT', 'NEAR', 'FIL', 'ICP',
];

// ============================================================
// 3. ImitationCounter 主类
// ============================================================

export class ImitationCounter {
  private records: Map<string, ImitationRecord> = new Map();
  private loaded = false;

  constructor() {
    this.load();
  }

  // --------------------------------------------------------
  // 归一化（m-2 修复，纯正则，零 LLM 依赖）
  // --------------------------------------------------------

  /**
   * 把用户原始 query 归一化为模式串
   * 规则：数字→{number} / symbol→{symbol} / 百分比→{pct} / 时间→{time} / 转小写去空格
   */
  normalizePattern(raw: string): string {
    let pattern = raw;

    // 1. 已知 symbol → {symbol}（先替换 symbol，避免被数字规则误伤）
    // 消费周围空格，使 '比特币' 和 ' BTC ' 归一化一致
    for (const sym of KNOWN_SYMBOLS) {
      // 转义正则特殊字符
      const escaped = sym.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      pattern = pattern.replace(new RegExp(`\\s*${escaped}\\s*`, 'gi'), ' {symbol} ');
    }

    // 2. 百分比 → {pct}（如 "5%" "12.5%"）
    pattern = pattern.replace(/\d+(?:\.\d+)?\s*%/g, '{pct}');

    // 3. 时间表达式 → {time}（消费周围空格，使 '昨天' 和 '2026-10-08 ' 归一化一致）
    // ISO 日期: 2026-10-08
    pattern = pattern.replace(/\s*\d{4}-\d{1,2}-\d{1,2}\s*/g, ' {time} ');
    // 中文相对时间: 昨天/今天/明天/前天/后天
    pattern = pattern.replace(/\s*(前天|昨天|今天|明天|后天|大前天|大后天)\s*/g, ' {time} ');
    pattern = pattern.replace(/\s*\d+\s*天[前后]\s*/g, ' {time} ');
    pattern = pattern.replace(/\s*\d+\s*小时[前后]\s*/g, ' {time} ');
    pattern = pattern.replace(/\s*\d+\s*分钟[前后]\s*/g, ' {time} ');

    // 4. 数字 → {number}（最后替换，避免误伤已替换的占位符）
    // 注意：{symbol} {pct} {time} 中的字母不匹配，但 {number} 本身含字母不会被数字规则匹配
    pattern = pattern.replace(/\b\d+(?:\.\d+)?\b/g, '{number}');

    // 5. 转小写 + 去多余空格
    pattern = pattern.toLowerCase().replace(/\s+/g, ' ').trim();

    return pattern;
  }

  // --------------------------------------------------------
  // 计数 + 阈值触发
  // --------------------------------------------------------

  /**
   * 增加同类模仿的计数。达 N 次触发 skill-creator 沉淀。
   * M-1 修复：已触发沉淀的 pattern 不再重复触发。
   */
  increment(
    rawQuery: string,
    docSources: string[],
    plan: string,
  ): IncrementResult {
    const pattern = this.normalizePattern(rawQuery);
    let record = this.records.get(pattern);

    if (!record) {
      record = {
        query_pattern: pattern,
        count: 0,
        first_seen: Date.now(),
        last_seen: Date.now(),
        document_sources: [],
        execution_plan_examples: [],
        sedimentation_triggered: false,
      };
      this.records.set(pattern, record);
    }

    // M-1: 已触发沉淀的 pattern 不再重复触发
    if (record.sedimentation_triggered) {
      return { triggered: false, current_count: record.count };
    }

    record.count += 1;
    record.last_seen = Date.now();

    // 合并 document_sources（去重）
    for (const src of docSources) {
      if (!record.document_sources.includes(src)) {
        record.document_sources.push(src);
      }
    }

    // 保留 execution_plan_examples（最多 max_plan_examples 条）
    if (record.execution_plan_examples.length < COUNTER_CONFIG.max_plan_examples) {
      record.execution_plan_examples.push(plan);
    }

    // 检查是否达阈值
    const triggered = record.count >= COUNTER_CONFIG.threshold;
    if (triggered) {
      record.sedimentation_triggered = true;
    }

    this.save();
    return { triggered, current_count: record.count };
  }

  // --------------------------------------------------------
  // 查询方法
  // --------------------------------------------------------

  /** 获取某 pattern 的当前计数 */
  getCount(rawQuery: string): number {
    const pattern = this.normalizePattern(rawQuery);
    return this.records.get(pattern)?.count || 0;
  }

  /** 获取所有记录 */
  getRecords(): ImitationRecord[] {
    return Array.from(this.records.values());
  }

  // --------------------------------------------------------
  // 重置（测试用）
  // --------------------------------------------------------

  reset(): void {
    this.records.clear();
    this.save();
  }

  // --------------------------------------------------------
  // 持久化
  // --------------------------------------------------------

  private load(): void {
    if (this.loaded) return;
    this.loaded = true;
    try {
      const dataPath = COUNTER_CONFIG.dataPath;
      if (fs.existsSync(dataPath)) {
        const raw = fs.readFileSync(dataPath, 'utf-8');
        const arr: ImitationRecord[] = JSON.parse(raw);
        this.records = new Map(arr.map(r => [r.query_pattern, r]));
      }
    } catch {
      // 文件不存在或解析失败，使用空 Map
      this.records = new Map();
    }
  }

  private save(): void {
    try {
      const dataPath = COUNTER_CONFIG.dataPath;
      const dir = path.dirname(dataPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      const arr = Array.from(this.records.values());
      fs.writeFileSync(dataPath, JSON.stringify(arr, null, 2), 'utf-8');
    } catch {
      // 写盘失败不阻塞主流程（FAIL-OPEN）
    }
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: ImitationCounter | null = null;

export function getImitationCounter(): ImitationCounter {
  if (!_instance) {
    _instance = new ImitationCounter();
  }
  return _instance;
}

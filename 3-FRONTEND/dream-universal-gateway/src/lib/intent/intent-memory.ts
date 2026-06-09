/**
 * Intent Memory Bank - 意图识别记忆库
 * v1.0 | 2026-05-16
 *
 * 核心职责:
 * 1. 记录每次意图识别结果 (input, intent, confidence, method, routing)
 * 2. 收集用户反馈 (correct/incorrect + 纠正意图)
 * 3. 统计分析 (准确率、混淆矩阵、方法分布、趋势)
 * 4. 模式发现 (LLM 识别到但规则未匹配的高频模式)
 * 5. 置信度调整 (基于反馈自动优化 experience-memory.json)
 * 6. 持久化存储 (RingBuffer 1000 条 + JSON 文件)
 */

import path from 'path';
import fs from 'fs';
import { IntentType, ComplexityLevel, ExperiencePattern } from './fallback-engine';

// ============================================================
// 类型定义
// ============================================================

export interface IntentMemoryRecord {
  id: string;
  timestamp: string;
  input: string;                    // 用户原始消息 (截断前100字)
  recognized_intent: IntentType;
  recognized_confidence: number;
  recognized_method: 'llm' | 'rule' | 'follow_up' | 'default';
  recognized_complexity: ComplexityLevel;
  matched_pattern_id?: string;
  llm_intent?: IntentType;
  llm_confidence?: number;
  routing_chain: string[];
  user_feedback?: 'correct' | 'incorrect' | null;
  corrected_intent?: IntentType;
  session_id: string;
  user_role: 'FREE' | 'PRO' | 'ADMIN';
}

export interface CandidatePattern {
  keywords: string[];
  intent: IntentType;
  occurrences: number;
  suggested_confidence: number;
  suggested_pattern: string;
  source: 'llm_only' | 'user_corrected';
}

export interface ConfidenceAdjustment {
  pattern_id: string;
  current_confidence: number;
  suggested_confidence: number;
  reason: string;
  delta: number;
}

export interface IntentMemoryStats {
  total_records: number;
  accuracy_rate: number;            // 0-100
  method_distribution: Record<string, number>;
  intent_distribution: Record<string, number>;
  confusion_matrix: Record<string, Record<string, number>>;
  feedback_counts: { correct: number; incorrect: number; pending: number };
  avg_confidence: number;
  trend: { date: string; method: string; count: number }[];
}

// ============================================================
// 持久化路径
// ============================================================

const MEMORY_DIR = path.resolve(process.cwd(), 'intent-memory');
const RECORDS_PATH = path.join(MEMORY_DIR, 'records.json');
const STATS_PATH = path.join(MEMORY_DIR, 'stats.json');
const EXPERIENCE_MEMORY_PATH = path.resolve(
  process.cwd(),
  '..',
  'skills',
  'user-intent-recognition',
  'experience-memory.json'
);

const MAX_RECORDS = 1000;

// ============================================================
// RingBuffer + 内存存储
// ============================================================

class RingBuffer<T> {
  private buffer: (T | undefined)[];
  private head = 0;
  private count = 0;
  private readonly capacity: number;

  constructor(capacity: number) {
    this.capacity = capacity;
    this.buffer = new Array(capacity);
  }

  push(item: T): void {
    this.buffer[this.head] = item;
    this.head = (this.head + 1) % this.capacity;
    if (this.count < this.capacity) this.count++;
  }

  toArray(): T[] {
    const result: T[] = [];
    if (this.count < this.capacity) {
      for (let i = 0; i < this.count; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
    } else {
      for (let i = this.head; i < this.capacity; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
      for (let i = 0; i < this.head; i++) {
        const item = this.buffer[i];
        if (item !== undefined) result.push(item);
      }
    }
    return result;
  }

  filter(predicate: (item: T) => boolean, limit?: number): T[] {
    const all = this.toArray();
    const filtered = all.filter(predicate);
    filtered.reverse();
    return limit ? filtered.slice(0, limit) : filtered;
  }

  findById(id: string): T | undefined {
    return this.toArray().find(
      (item: any) => item.id === id
    );
  }

  update(id: string, updater: (item: T) => T): boolean {
    for (let i = 0; i < this.capacity; i++) {
      const item = this.buffer[i];
      if (item && (item as any).id === id) {
        this.buffer[i] = updater(item);
        return true;
      }
    }
    return false;
  }

  get size(): number {
    return this.count;
  }
}

// ============================================================
// Intent Memory Bank 单例
// ============================================================

class IntentMemoryBank {
  private records: RingBuffer<IntentMemoryRecord>;
  private stats: { correct: number; incorrect: number; pending: number; methodDist: Record<string, number>; intentDist: Record<string, number>; confusion: Record<string, Record<string, number>> };
  private experiencePatterns: ExperiencePattern[] = [];
  private experienceLoaded = false;

  constructor() {
    this.records = new RingBuffer(MAX_RECORDS);
    this.stats = { correct: 0, incorrect: 0, pending: 0, methodDist: {}, intentDist: {}, confusion: {} };
    this.loadFromDisk();
    this.loadExperienceMemory();
  }

  // ---- 持久化 ----

  private loadFromDisk(): void {
    try {
      if (fs.existsSync(RECORDS_PATH)) {
        const raw = fs.readFileSync(RECORDS_PATH, 'utf-8');
        const data = JSON.parse(raw);
        const records: IntentMemoryRecord[] = data.records || [];
        for (const r of records) {
          this.records.push(r);
          this.updateStatsFromRecord(r);
        }
        console.log(`[IntentMemory] Loaded ${records.length} records from disk`);
      }
    } catch (e) {
      console.warn('[IntentMemory] Failed to load records from disk:', e);
    }
  }

  private saveToDisk(): void {
    try {
      if (!fs.existsSync(MEMORY_DIR)) {
        fs.mkdirSync(MEMORY_DIR, { recursive: true });
      }
      const records = this.records.toArray();
      fs.writeFileSync(RECORDS_PATH, JSON.stringify({ records, total: records.length, saved_at: new Date().toISOString() }, null, 2));

      // 保存聚合统计
      fs.writeFileSync(STATS_PATH, JSON.stringify({
        ...this.stats,
        updated_at: new Date().toISOString(),
      }, null, 2));
    } catch (e) {
      console.warn('[IntentMemory] Failed to save to disk:', e);
    }
  }

  private updateStatsFromRecord(r: IntentMemoryRecord): void {
    this.stats.methodDist[r.recognized_method] = (this.stats.methodDist[r.recognized_method] || 0) + 1;
    this.stats.intentDist[r.recognized_intent] = (this.stats.intentDist[r.recognized_intent] || 0) + 1;

    // 混淆矩阵
    if (r.llm_intent) {
      if (!this.stats.confusion[r.llm_intent]) this.stats.confusion[r.llm_intent] = {};
      this.stats.confusion[r.llm_intent][r.recognized_intent] =
        (this.stats.confusion[r.llm_intent][r.recognized_intent] || 0) + 1;
    }

    // 反馈计数
    if (r.user_feedback === 'correct') this.stats.correct++;
    else if (r.user_feedback === 'incorrect') this.stats.incorrect++;
    else this.stats.pending++;
  }

  // ---- 记录识别 ----

  recordRecognition(data: {
    input: string;
    recognized_intent: IntentType;
    recognized_confidence: number;
    recognized_method: 'llm' | 'rule' | 'follow_up' | 'default';
    recognized_complexity: ComplexityLevel;
    matched_pattern_id?: string;
    llm_intent?: IntentType;
    llm_confidence?: number;
    routing_chain: string[];
    session_id: string;
    user_role: 'FREE' | 'PRO' | 'ADMIN';
  }): string {
    const record: IntentMemoryRecord = {
      id: `mem_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      timestamp: new Date().toISOString(),
      input: data.input.slice(0, 100),
      recognized_intent: data.recognized_intent,
      recognized_confidence: data.recognized_confidence,
      recognized_method: data.recognized_method,
      recognized_complexity: data.recognized_complexity,
      matched_pattern_id: data.matched_pattern_id,
      llm_intent: data.llm_intent,
      llm_confidence: data.llm_confidence,
      routing_chain: data.routing_chain,
      session_id: data.session_id,
      user_role: data.user_role,
      user_feedback: null,
    };

    this.records.push(record);
    this.updateStatsFromRecord(record);
    this.saveToDisk();

    return record.id;
  }

  // ---- 反馈 ----

  recordFeedback(recordId: string, feedback: 'correct' | 'incorrect', correctedIntent?: IntentType): boolean {
    const updated = this.records.update(recordId, (r) => ({
      ...r,
      user_feedback: feedback,
      corrected_intent: feedback === 'incorrect' ? correctedIntent : undefined,
    }));

    if (updated) {
      // 重新统计
      if (feedback === 'correct') this.stats.correct++;
      else this.stats.incorrect++;
      this.stats.pending = Math.max(0, this.stats.pending - 1);
      this.saveToDisk();
    }

    return updated;
  }

  // ---- 查询 ----

  getRecords(options?: {
    intent?: IntentType;
    method?: string;
    feedback?: 'correct' | 'incorrect' | 'pending';
    session_id?: string;
    limit?: number;
  }): IntentMemoryRecord[] {
    const { intent, method, feedback, session_id, limit = 50 } = options || {};

    return this.records.filter((r) => {
      if (intent && r.recognized_intent !== intent) return false;
      if (method && r.recognized_method !== method) return false;
      if (feedback === 'correct' && r.user_feedback !== 'correct') return false;
      if (feedback === 'incorrect' && r.user_feedback !== 'incorrect') return false;
      if (feedback === 'pending' && r.user_feedback !== null) return false;
      if (session_id && r.session_id !== session_id) return false;
      return true;
    }, limit);
  }

  getRecordById(id: string): IntentMemoryRecord | undefined {
    return this.records.findById(id);
  }

  // ---- 统计 ----

  getStats(): IntentMemoryStats {
    const all = this.records.toArray();
    const total = all.length;
    if (total === 0) {
      return {
        total_records: 0, accuracy_rate: 0, method_distribution: {},
        intent_distribution: {}, confusion_matrix: {},
        feedback_counts: { correct: 0, incorrect: 0, pending: 0 },
        avg_confidence: 0, trend: [],
      };
    }

    const correctCount = all.filter(r => r.user_feedback === 'correct').length;
    const incorrectCount = all.filter(r => r.user_feedback === 'incorrect').length;
    const accuracyRate = (correctCount + incorrectCount) > 0
      ? Math.round((correctCount / (correctCount + incorrectCount)) * 100)
      : 0;

    const avgConfidence = Math.round((all.reduce((s, r) => s + r.recognized_confidence, 0) / total) * 100) / 100;

    // 方法分布
    const methodDist: Record<string, number> = {};
    const intentDist: Record<string, number> = {};
    const confusion: Record<string, Record<string, number>> = {};
    for (const r of all) {
      methodDist[r.recognized_method] = (methodDist[r.recognized_method] || 0) + 1;
      intentDist[r.recognized_intent] = (intentDist[r.recognized_intent] || 0) + 1;
      if (r.llm_intent) {
        if (!confusion[r.llm_intent]) confusion[r.llm_intent] = {};
        confusion[r.llm_intent][r.recognized_intent] = (confusion[r.llm_intent][r.recognized_intent] || 0) + 1;
      }
    }

    // 趋势 (按天分组)
    const trendMap: Record<string, Record<string, number>> = {};
    for (const r of all) {
      const date = r.timestamp.slice(0, 10);
      if (!trendMap[date]) trendMap[date] = {};
      trendMap[date][r.recognized_method] = (trendMap[date][r.recognized_method] || 0) + 1;
    }
    const trend = Object.entries(trendMap).flatMap(([date, methods]) =>
      Object.entries(methods).map(([method, count]) => ({ date, method, count }))
    );

    return {
      total_records: total,
      accuracy_rate: accuracyRate,
      method_distribution: methodDist,
      intent_distribution: intentDist,
      confusion_matrix: confusion,
      feedback_counts: { correct: correctCount, incorrect: incorrectCount, pending: total - correctCount - incorrectCount },
      avg_confidence: avgConfidence,
      trend,
    };
  }

  // ---- 模式发现 ----

  getCandidatePatterns(): CandidatePattern[] {
    const all = this.records.toArray();
    // 找出 LLM 识别到但规则未匹配的记录
    const llmOnlyRecords = all.filter(r =>
      r.recognized_method === 'llm' && !r.matched_pattern_id
    );

    // 按意图分组，提取关键词
    const grouped: Record<string, Array<{ input: string; confidence: number }>> = {};
    for (const r of llmOnlyRecords) {
      if (!grouped[r.recognized_intent]) grouped[r.recognized_intent] = [];
      grouped[r.recognized_intent].push({ input: r.input, confidence: r.recognized_confidence });
    }

    const candidates: CandidatePattern[] = [];
    for (const [intent, records] of Object.entries(grouped)) {
      if (records.length < 3) continue; // 至少 3 次才推荐

      // 提取 ngram 关键词
      const keywordCounts: Record<string, number> = {};
      for (const r of records) {
        const words = extractKeywords(r.input);
        for (const w of words) {
          keywordCounts[w] = (keywordCounts[w] || 0) + 1;
        }
      }

      // 取出现次数 >= 2 的关键词
      const frequent = Object.entries(keywordCounts)
        .filter(([, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([word]) => word);

      if (frequent.length > 0) {
        const avgConf = records.reduce((s, r) => s + r.confidence, 0) / records.length;
        candidates.push({
          keywords: frequent,
          intent: intent as IntentType,
          occurrences: records.length,
          suggested_confidence: Math.round(avgConf * 100) / 100,
          suggested_pattern: frequent.join('|'),
          source: 'llm_only',
        });
      }
    }

    // 用户纠正产生的候选
    const correctedRecords = all.filter(r =>
      r.user_feedback === 'incorrect' && r.corrected_intent
    );
    const correctedGrouped: Record<string, Array<{ input: string }>> = {};
    for (const r of correctedRecords) {
      const ci = r.corrected_intent!;
      if (!correctedGrouped[ci]) correctedGrouped[ci] = [];
      correctedGrouped[ci].push({ input: r.input });
    }
    for (const [intent, records] of Object.entries(correctedGrouped)) {
      if (records.length < 2) continue;
      const keywordCounts: Record<string, number> = {};
      for (const r of records) {
        for (const w of extractKeywords(r.input)) {
          keywordCounts[w] = (keywordCounts[w] || 0) + 1;
        }
      }
      const frequent = Object.entries(keywordCounts)
        .filter(([, count]) => count >= 2)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([word]) => word);

      if (frequent.length > 0) {
        candidates.push({
          keywords: frequent,
          intent: intent as IntentType,
          occurrences: records.length,
          suggested_confidence: 0.60,
          suggested_pattern: frequent.join('|'),
          source: 'user_corrected',
        });
      }
    }

    return candidates.sort((a, b) => b.occurrences - a.occurrences);
  }

  // ---- 置信度调整 ----

  getConfidenceAdjustments(): ConfidenceAdjustment[] {
    const patterns = this.loadExperienceMemory();
    const adjustments: ConfidenceAdjustment[] = [];
    const all = this.records.toArray();

    for (const pattern of patterns) {
      const matchedRecords = all.filter(r => r.matched_pattern_id === pattern.id);
      if (matchedRecords.length === 0) continue;

      let delta = 0;
      const reasons: string[] = [];

      for (const r of matchedRecords) {
        if (r.user_feedback === 'correct') delta += 0.02;
        else if (r.user_feedback === 'incorrect') delta -= 0.05;

        // LLM vs rule 对比
        if (r.llm_intent && r.llm_intent !== r.recognized_intent) {
          delta -= 0.01;
        } else if (r.llm_intent && r.llm_intent === r.recognized_intent) {
          delta += 0.005;
        }
      }

      if (delta === 0) continue;

      const newConf = Math.max(0.30, Math.min(0.98, pattern.confidence + delta));
      if (Math.abs(newConf - pattern.confidence) < 0.005) continue;

      if (delta > 0) reasons.push(`User confirmed ${matchedRecords.filter(r => r.user_feedback === 'correct').length} times`);
      if (delta < 0) reasons.push(`User rejected ${matchedRecords.filter(r => r.user_feedback === 'incorrect').length} times`);

      adjustments.push({
        pattern_id: pattern.id,
        current_confidence: pattern.confidence,
        suggested_confidence: Math.round(newConf * 100) / 100,
        reason: reasons.join('; ') || `Auto-adjusted from ${matchedRecords.length} records`,
        delta: Math.round(delta * 1000) / 1000,
      });
    }

    return adjustments.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  }

  // ---- 应用调整 ----

  applyAdjustments(adjustments: ConfidenceAdjustment[]): boolean {
    if (adjustments.length === 0) return false;

    const patterns = this.loadExperienceMemory();
    let changed = 0;

    for (const adj of adjustments) {
      const pattern = patterns.find(p => p.id === adj.pattern_id);
      if (pattern) {
        pattern.confidence = adj.suggested_confidence;
        changed++;
      }
    }

    if (changed > 0) {
      this.writeExperienceMemory(patterns);
      console.log(`[IntentMemory] Applied ${changed} confidence adjustments`);
      return true;
    }
    return false;
  }

  // ---- 采纳候选模式 ----

  adoptCandidate(candidate: CandidatePattern): boolean {
    const patterns = this.loadExperienceMemory();
    const maxId = patterns.reduce((max, p) => {
      const num = parseInt(p.id.split('_')[1] || '0', 10);
      return Math.max(max, num);
    }, 0);

    const newPattern: ExperiencePattern = {
      id: `eq_${String(maxId + 1).padStart(3, '0')}`,
      patterns: candidate.keywords,
      intent: candidate.intent,
      confidence: candidate.suggested_confidence,
      entities_template: { symbol: '{{auto_detect}}' },
      complexity: 'moderate',
      source: candidate.source === 'user_corrected' ? 'user_feedback' : 'llm_discovery',
      usage_count: candidate.occurrences,
    };

    patterns.push(newPattern);
    this.writeExperienceMemory(patterns);
    console.log(`[IntentMemory] Adopted new pattern: ${newPattern.id} (${candidate.suggested_pattern})`);
    return true;
  }

  // ---- 经验模式库加载/写入 ----

  loadExperienceMemory(): ExperiencePattern[] {
    if (this.experienceLoaded) return this.experiencePatterns;

    try {
      if (fs.existsSync(EXPERIENCE_MEMORY_PATH)) {
        const raw = fs.readFileSync(EXPERIENCE_MEMORY_PATH, 'utf-8');
        const data = JSON.parse(raw);
        this.experiencePatterns = data.patterns || [];
      }
    } catch (e) {
      console.warn('[IntentMemory] Failed to load experience memory:', e);
      this.experiencePatterns = [];
    }

    this.experienceLoaded = true;
    return this.experiencePatterns;
  }

  private writeExperienceMemory(patterns: ExperiencePattern[]): void {
    try {
      if (!fs.existsSync(EXPERIENCE_MEMORY_PATH)) {
        const dir = path.dirname(EXPERIENCE_MEMORY_PATH);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      }

      // 更新 intent_distribution
      const dist: Record<string, number> = {};
      for (const p of patterns) {
        dist[p.intent] = (dist[p.intent] || 0) + 1;
      }

      const data = {
        version: '1.1',
        updated_at: new Date().toISOString().slice(0, 10),
        description: '经验长期记忆 - 常见用户意图模式库 (auto-evolved)',
        patterns,
        total_patterns: patterns.length,
        intent_distribution: dist,
      };

      fs.writeFileSync(EXPERIENCE_MEMORY_PATH, JSON.stringify(data, null, 2));
      this.experiencePatterns = patterns;
      console.log(`[IntentMemory] Saved ${patterns.length} patterns to experience-memory.json`);
    } catch (e) {
      console.warn('[IntentMemory] Failed to write experience memory:', e);
    }
  }

  // ---- 更新路由链 ----

  updateLastRoutingChain(sessionId: string, chain: string[]): void {
    const all = this.records.toArray();
    for (let i = all.length - 1; i >= 0; i--) {
      if (all[i].session_id === sessionId && all[i].routing_chain.length === 0) {
        this.records.update(all[i].id, (r) => ({ ...r, routing_chain: chain }));
        this.saveToDisk();
        return;
      }
    }
  }

  // ---- 便捷访问 ----

  get totalRecords(): number {
    return this.records.size;
  }
}

// ============================================================
// Ngram 关键词提取
// ============================================================

function extractKeywords(input: string): string[] {
  // 去除标点、emoji
  const cleaned = input.replace(/[^\w\u4e00-\u9fff\s]/g, '').trim().toLowerCase();
  if (cleaned.length < 2) return [];

  const keywords: string[] = [];
  // 2-gram 和 3-gram
  for (let i = 0; i < cleaned.length - 1; i++) {
    keywords.push(cleaned.slice(i, i + 2));
    if (i < cleaned.length - 2) {
      keywords.push(cleaned.slice(i, i + 3));
    }
  }
  // 去重
  return [...new Set(keywords)];
}

// ============================================================
// 导出单例
// ============================================================

const intentMemory = new IntentMemoryBank();
export default intentMemory;

// 便捷函数
export function recordRecognition(data: {
  input: string;
  recognized_intent: IntentType;
  recognized_confidence: number;
  recognized_method: 'llm' | 'rule' | 'follow_up' | 'default';
  recognized_complexity: ComplexityLevel;
  matched_pattern_id?: string;
  llm_intent?: IntentType;
  llm_confidence?: number;
  routing_chain: string[];
  session_id: string;
  user_role: 'FREE' | 'PRO' | 'ADMIN';
}): string {
  return intentMemory.recordRecognition(data);
}

export function recordFeedback(recordId: string, feedback: 'correct' | 'incorrect', correctedIntent?: IntentType): boolean {
  return intentMemory.recordFeedback(recordId, feedback, correctedIntent);
}

export function getMemoryRecords(options?: {
  intent?: IntentType;
  method?: string;
  feedback?: 'correct' | 'incorrect' | 'pending';
  session_id?: string;
  limit?: number;
}): IntentMemoryRecord[] {
  return intentMemory.getRecords(options);
}

export function getMemoryStats(): IntentMemoryStats {
  return intentMemory.getStats();
}

export function getCandidatePatterns(): CandidatePattern[] {
  return intentMemory.getCandidatePatterns();
}

export function getConfidenceAdjustments(): ConfidenceAdjustment[] {
  return intentMemory.getConfidenceAdjustments();
}

export function applyAdjustments(adjustments: ConfidenceAdjustment[]): boolean {
  return intentMemory.applyAdjustments(adjustments);
}

export function adoptCandidate(candidate: CandidatePattern): boolean {
  return intentMemory.adoptCandidate(candidate);
}

export function loadExperienceMemory(): ExperiencePattern[] {
  return intentMemory.loadExperienceMemory();
}

export function updateLastRoutingChain(sessionId: string, chain: string[]): void {
  return intentMemory.updateLastRoutingChain(sessionId, chain);
}

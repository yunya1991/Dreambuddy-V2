/**
 * Hermes-Style User Preference Memory
 * v1.0 | 2026-06-16
 *
 * 核心设计理念（参考 Hermes AI 记忆系统）:
 * 1. 有限容量约束 — 最多 50 条核心记忆，防止无限膨胀
 * 2. 优先级驱动淘汰 — 低重要性/过时记忆自动被淘汰
 * 3. 记忆进化 — 相似记忆合并强化，冗余记忆被清除
 * 4. 强制更新 — 用户反馈驱动记忆即时更新和演化
 * 5. 核心记忆原则 — 只记忆影响策略输出的关键偏好
 *
 * 与 IntentMemoryBank 的区别:
 * - IntentMemoryBank: 意图识别经验（系统级，学习的是"用户通常问什么"）
 * - UserPreferenceMemory: 用户个人偏好（用户级，学习的是"这个用户喜欢什么"）
 */

import path from 'path';
import fs from 'fs';

// ============================================================
// 类型定义
// ============================================================

/** 记忆类型枚举 — 只存储影响 S 系列策略输出的核心偏好 */
export type PreferenceType =
  | 'response_style'      // 响应风格偏好
  | 'risk_tolerance'      // 风险承受能力
  | 'preferred_symbols'   // 常分析的交易品种
  | 'conclusion_style'    // 结论偏好（详细/摘要/行动）
  | 'strategy_feedback'    // 策略反馈历史
  | 'interaction_count'    // 交互频次
  | 'language_preference'; // 语言偏好（zh/en）

export type ResponseStyle = 'data_driven' | 'macro_narrative' | 'structured_list';
export type RiskTolerance = 'low' | 'medium' | 'high';
export type ConclusionStyle = 'detailed' | 'summary' | 'action_only';

/** 单条记忆 */
export interface MemoryEntry {
  id: string;
  type: PreferenceType;
  value: any;                // 值（类型由 type 决定）
  importance: number;         // 重要性 0.0–1.0（决定淘汰优先级）
  lastReinforced: number;     // 上次强化时间（epoch ms）
  createdAt: number;         // 创建时间
  reinforcementCount: number; // 被强化次数（同一偏好重复出现时 +1）
  source: 'explicit_feedback' | 'implicit_behavior' | 'pattern_inference';
  evidence: string;          // 佐证文本（用于解释为什么记忆被建立）
}

/** 用户记忆快照 — 用于注入到 LLM prompt */
export interface MemorySnapshot {
  preferred_style: ResponseStyle | null;
  risk_tolerance: RiskTolerance | null;
  preferred_symbols: string[];
  conclusion_style: ConclusionStyle | null;
  recent_adjustments: string[];  // 最近 N 次调整记录
  interaction_count: number;
  memory_age_days: number;        // 最老记忆的年龄（天）
  total_memories: number;
}

/** 记忆系统统计 */
export interface MemoryStats {
  totalMemories: number;
  maxCapacity: number;
  utilizationRate: number;         // 容量利用率
  avgImportance: number;
  oldestMemoryAgeDays: number;
  newestMemoryAgeDays: number;
  typeDistribution: Record<string, number>;
  evolutionCount: number;          // 进化/合并次数
  pruneCount: number;             // 淘汰次数
}

// ============================================================
// 系统约束常量
// ============================================================

const MAX_MEMORIES_PER_USER = 50;      // 硬性上限：每个用户最多 50 条记忆
const MIN_IMPORTANCE_TO_KEEP = 0.12;  // 淘汰阈值：重要性低于此值立即淘汰
const DECAY_RATE_PER_DAY = 0.03;      // 自然衰减率：每天 -3% 重要性
const REINFORCEMENT_BOOST = 0.15;    // 强化增量：每次确认 +15% 重要性
const EVOLUTION_SIMILARITY_THRESHOLD = 0.72; // 合并阈值：相似度 > 72% 则合并
const MAX_EVIDENCE_LENGTH = 80;       // 佐证文本最大长度

// ============================================================
// 用户偏好记忆库
// ============================================================

class UserPreferenceMemoryStore {
  /** 用户 ID → 记忆列表 */
  private memories: Map<string, MemoryEntry[]> = new Map();

  /** 记忆操作统计（用于调试） */
  private stats: Map<string, { evolutionCount: number; pruneCount: number }> = new Map();

  /** 持久化目录 */
  private memoryDir: string;

  constructor() {
    this.memoryDir = path.resolve(process.cwd(), 'user-preference-memory');
    this.ensureDir();
    this.loadAllFromDisk();
  }

  private ensureDir(): void {
    if (!fs.existsSync(this.memoryDir)) {
      fs.mkdirSync(this.memoryDir, { recursive: true });
    }
  }

  // ============================================================
  // 持久化
  // ============================================================

  private userFile(userId: string): string {
    const safe = userId.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 64);
    return path.join(this.memoryDir, `${safe}.json`);
  }

  private loadAllFromDisk(): void {
    try {
      const files = fs.readdirSync(this.memoryDir);
      let loaded = 0;
      for (const file of files) {
        if (!file.endsWith('.json')) continue;
        try {
          const raw = fs.readFileSync(path.join(this.memoryDir, file), 'utf-8');
          const data = JSON.parse(raw);
          const entries: MemoryEntry[] = (data.memories || []).map((m: any) => ({
            ...m,
            // 确保时间戳是数字
            lastReinforced: Number(m.lastReinforced),
            createdAt: Number(m.createdAt),
            reinforcementCount: Number(m.reinforcementCount),
          }));
          this.memories.set(data.userId, entries);
          this.stats.set(data.userId, {
            evolutionCount: data.evolutionCount || 0,
            pruneCount: data.pruneCount || 0,
          });
          loaded++;
        } catch { /* ignore corrupted files */ }
      }
      console.log(`[UserPreferenceMemory] Loaded memories for ${loaded} users`);
    } catch (e) {
      console.warn('[UserPreferenceMemory] Failed to load from disk:', e);
    }
  }

  private saveToDisk(userId: string): void {
    const entries = this.memories.get(userId) || [];
    const stat = this.stats.get(userId) || { evolutionCount: 0, pruneCount: 0 };
    try {
      fs.writeFileSync(this.userFile(userId), JSON.stringify({
        userId,
        memories: entries,
        evolutionCount: stat.evolutionCount,
        pruneCount: stat.pruneCount,
        updatedAt: new Date().toISOString(),
      }, null, 2));
    } catch (e) {
      console.warn(`[UserPreferenceMemory] Failed to save for user ${userId}:`, e);
    }
  }

  // ============================================================
  // 核心 API：学习（Learn）
  // ============================================================

  /**
   * 学习新的用户偏好
   *
   * 策略：
   * 1. 如果存在相似记忆 → 合并（强化），不增加数量
   * 2. 如果不存在 → 添加（可能触发淘汰）
   * 3. 容量已满 → 先淘汰低优先级记忆，再添加
   */
  learn(params: {
    userId: string;
    type: PreferenceType;
    value: any;
    importance: number;         // 0.0–1.0，首次学习时建议 0.5
    source: MemoryEntry['source'];
    evidence: string;            // 用户说过的原话（截断）
  }): { action: 'added' | 'evolved' | 'pruned' | 'nochange'; merged?: boolean } {
    const { userId, type, value, importance, source, evidence } = params;

    if (!this.memories.has(userId)) {
      this.memories.set(userId, []);
      this.stats.set(userId, { evolutionCount: 0, pruneCount: 0 });
    }

    const entries = this.memories.get(userId)!;
    const now = Date.now();

    // 1. 尝试合并相似记忆
    const similarIdx = this.findSimilarMemory(entries, type, value);
    if (similarIdx >= 0) {
      const existing = entries[similarIdx];
      // 合并：新值替换旧值，重要性取 max，强化次数 +1
      const newImportance = Math.min(1.0, Math.max(existing.importance, importance) + REINFORCEMENT_BOOST);
      entries[similarIdx] = {
        ...existing,
        value,
        importance: newImportance,
        lastReinforced: now,
        reinforcementCount: existing.reinforcementCount + 1,
        source: this.mergeSource(existing.source, source),
        evidence: evidence.slice(0, MAX_EVIDENCE_LENGTH),
      };

      const stat = this.stats.get(userId)!;
      stat.evolutionCount++;

      // 排序：重要性高的排前面（便于淘汰时从末尾删除）
      this.sortByPriority(entries);
      this.saveToDisk(userId);
      return { action: 'evolved', merged: true };
    }

    // 2. 容量已满？先淘汰
    if (entries.length >= MAX_MEMORIES_PER_USER) {
      const before = entries.length;
      this.pruneLowPriority(entries, 5); // 淘汰至少 5 条最低优先级
      const stat = this.stats.get(userId)!;
      stat.pruneCount += (before - entries.length);
    }

    // 3. 添加新记忆
    const newEntry: MemoryEntry = {
      id: `mem_${now}_${Math.random().toString(36).slice(2, 6)}`,
      type,
      value,
      importance: Math.min(1.0, importance),
      lastReinforced: now,
      createdAt: now,
      reinforcementCount: 1,
      source,
      evidence: evidence.slice(0, MAX_EVIDENCE_LENGTH),
    };

    entries.push(newEntry);
    this.sortByPriority(entries);
    this.saveToDisk(userId);
    return { action: 'added' };
  }

  // ============================================================
  // 核心 API：提取（Retrieve）
  // ============================================================

  /**
   * 提取用户记忆快照 — 用于注入到 LLM prompt
   */
  retrieve(userId: string): MemorySnapshot {
    const entries = this.memories.get(userId) || [];
    if (entries.length === 0) {
      return {
        preferred_style: null,
        risk_tolerance: null,
        preferred_symbols: [],
        conclusion_style: null,
        recent_adjustments: [],
        interaction_count: 0,
        memory_age_days: 0,
        total_memories: 0,
      };
    }

    const now = Date.now();
    const oneDayMs = 86_400_000;

    // 应用衰减
    const decayed = entries.map(e => {
      const daysSinceReinforce = (now - e.lastReinforced) / oneDayMs;
      const decayedImportance = Math.max(
        MIN_IMPORTANCE_TO_KEEP / 2,
        e.importance - daysSinceReinforce * DECAY_RATE_PER_DAY
      );
      return { ...e, importance: decayedImportance };
    });

    // 提取各类偏好（取最重要的一条）
    const preferred_style = this.extractTop(
      decayed, e => e.type === 'response_style', e => e.value as ResponseStyle
    );
    const risk_tolerance = this.extractTop(
      decayed, e => e.type === 'risk_tolerance', e => e.value as RiskTolerance
    );
    const conclusion_style = this.extractTop(
      decayed, e => e.type === 'conclusion_style', e => e.value as ConclusionStyle
    );
    const preferred_symbols = this.extractTopArray(
      decayed, e => e.type === 'preferred_symbols'
    );
    const interaction_count = this.extractTop(
      decayed, e => e.type === 'interaction_count', e => e.value as number
    ) || 0;

    // 最近调整历史（取最近 3 条 feedback）
    const recent_adjustments = decayed
      .filter(e => e.type === 'strategy_feedback')
      .sort((a, b) => b.lastReinforced - a.lastReinforced)
      .slice(0, 3)
      .map(e => `【${e.type}】${e.evidence}`);

    // 最老记忆的年龄
    const oldestEntry = decayed.sort((a, b) => a.createdAt - b.createdAt)[0];
    const memory_age_days = Math.round((now - oldestEntry.createdAt) / oneDayMs);

    return {
      preferred_style,
      risk_tolerance,
      preferred_symbols: preferred_symbols.slice(0, 5),
      conclusion_style,
      recent_adjustments,
      interaction_count,
      memory_age_days,
      total_memories: decayed.length,
    };
  }

  // ============================================================
  // 核心 API：遗忘（Forget/Prune）
  // ============================================================

  /**
   * 强制遗忘 — 当记忆数量超过容量时，删除最低优先级记忆
   */
  private pruneLowPriority(entries: MemoryEntry[], minToRemove: number): void {
    // 按重要性升序排序
    entries.sort((a, b) => a.importance - b.importance);

    let removed = 0;
    // 删除最低优先级的记忆（直到删除 minToRemove 条或达到容量上限）
    while (entries.length > 0 && removed < minToRemove && entries[0].importance < MIN_IMPORTANCE_TO_KEEP) {
      entries.shift();
      removed++;
    }

    // 如果删除了记忆，同步更新持久化
    if (removed > 0) {
      console.log(`[UserPreferenceMemory] Pruned ${removed} low-priority memories (threshold: ${MIN_IMPORTANCE_TO_KEEP})`);
    }
  }

  /**
   * 记忆衰减 — 自然老化，定期调用以降低长期未使用的记忆优先级
   */
  applyDecay(userId: string, decayDays: number = 7): number {
    const entries = this.memories.get(userId);
    if (!entries || entries.length === 0) return 0;

    const threshold = Date.now() - decayDays * 86_400_000;
    let decayed = 0;

    for (const e of entries) {
      if (e.lastReinforced < threshold && e.reinforcementCount < 2) {
        // 长期未强化 + 强化次数少 → 自然淘汰
        e.importance = Math.max(0, e.importance - DECAY_RATE_PER_DAY * decayDays);
        decayed++;
      }
    }

    // 淘汰已低于阈值的记忆
    const before = entries.length;
    this.pruneLowPriority(entries, 0);
    const removed = before - entries.length;

    if (decayed > 0 || removed > 0) {
      this.saveToDisk(userId);
    }

    return removed;
  }

  /**
   * 强制清除 — 删除某个类型的所有记忆
   */
  forgetType(userId: string, type: PreferenceType): void {
    const entries = this.memories.get(userId);
    if (!entries) return;

    const filtered = entries.filter(e => e.type !== type);
    this.memories.set(userId, filtered);
    this.saveToDisk(userId);
    console.log(`[UserPreferenceMemory] Forgot all ${type} memories for user ${userId}`);
  }

  // ============================================================
  // 辅助方法
  // ============================================================

  /** 查找相似记忆（用于合并进化） */
  private findSimilarMemory(entries: MemoryEntry[], type: PreferenceType, value: any): number {
    return entries.findIndex(e => {
      if (e.type !== type) return false;

      // 数值类型：直接比较
      if (typeof value === 'string' || typeof value === 'number') {
        return value === e.value;
      }

      // 数组类型：检查重叠率
      if (Array.isArray(value) && Array.isArray(e.value)) {
        const overlap = value.filter(v => e.value.includes(v)).length;
        return overlap / Math.max(value.length, e.value.length) >= EVOLUTION_SIMILARITY_THRESHOLD;
      }

      // 对象类型：检查关键字段
      if (typeof value === 'object' && typeof e.value === 'object') {
        return JSON.stringify(value) === JSON.stringify(e.value);
      }

      return false;
    });
  }

  /** 合并来源（优先保留显式反馈来源） */
  private mergeSource(a: MemoryEntry['source'], b: MemoryEntry['source']): MemoryEntry['source'] {
    const priority: Record<MemoryEntry['source'], number> = {
      explicit_feedback: 3,
      implicit_behavior: 2,
      pattern_inference: 1,
    };
    return priority[a] >= priority[b] ? a : b;
  }

  /** 按优先级排序（重要性高的在前） */
  private sortByPriority(entries: MemoryEntry[]): void {
    entries.sort((a, b) => {
      // 首次按重要性降序，次按强化次数降序
      if (Math.abs(b.importance - a.importance) > 0.05) {
        return b.importance - a.importance;
      }
      return b.reinforcementCount - a.reinforcementCount;
    });
  }

  /** 提取某个类型中优先级最高的值 */
  private extractTop<V>(
    entries: MemoryEntry[],
    filterFn: (e: MemoryEntry) => boolean,
    valueFn: (e: MemoryEntry) => V
  ): V | null {
    const filtered = entries.filter(filterFn);
    if (filtered.length === 0) return null;
    // 取重要性最高的
    filtered.sort((a, b) => b.importance - a.importance);
    return valueFn(filtered[0]);
  }

  /** 提取数组类型的值并合并 */
  private extractTopArray(
    entries: MemoryEntry[],
    filterFn: (e: MemoryEntry) => boolean
  ): any[] {
    const filtered = entries.filter(filterFn);
    if (filtered.length === 0) return [];
    const allValues = filtered.flatMap(e => Array.isArray(e.value) ? e.value : [e.value]);
    // 去重
    return [...new Set(allValues)];
  }

  // ============================================================
  // 统计
  // ============================================================

  getStats(userId: string): MemoryStats {
    const entries = this.memories.get(userId) || [];
    const stat = this.stats.get(userId) || { evolutionCount: 0, pruneCount: 0 };
    const now = Date.now();

    if (entries.length === 0) {
      return {
        totalMemories: 0, maxCapacity: MAX_MEMORIES_PER_USER,
        utilizationRate: 0, avgImportance: 0,
        oldestMemoryAgeDays: 0, newestMemoryAgeDays: 0,
        typeDistribution: {}, evolutionCount: 0, pruneCount: 0,
      };
    }

    const oneDayMs = 86_400_000;
    const oldestEntry = entries.reduce((a, b) => a.createdAt < b.createdAt ? a : b);
    const newestEntry = entries.reduce((a, b) => a.createdAt > b.createdAt ? a : b);

    const typeDist: Record<string, number> = {};
    let totalImportance = 0;
    for (const e of entries) {
      typeDist[e.type] = (typeDist[e.type] || 0) + 1;
      totalImportance += e.importance;
    }

    return {
      totalMemories: entries.length,
      maxCapacity: MAX_MEMORIES_PER_USER,
      utilizationRate: Math.round((entries.length / MAX_MEMORIES_PER_USER) * 100),
      avgImportance: Math.round((totalImportance / entries.length) * 100) / 100,
      oldestMemoryAgeDays: Math.round((now - oldestEntry.createdAt) / oneDayMs),
      newestMemoryAgeDays: Math.round((now - newestEntry.createdAt) / oneDayMs),
      typeDistribution: typeDist,
      evolutionCount: stat.evolutionCount,
      pruneCount: stat.pruneCount,
    };
  }

  get totalUsers(): number {
    return this.memories.size;
  }
}

// ============================================================
// 单例导出
// ============================================================

const userPreferenceMemory = new UserPreferenceMemoryStore();
export default userPreferenceMemory;

// ============================================================
// 便捷 API
// ============================================================

/**
 * 从用户消息中提取偏好信号（隐式学习）
 * 返回 null 表示没有检测到偏好信号
 */
export function detectPreferenceSignal(message: string, intent: string): {
  type: PreferenceType;
  value: any;
  importance: number;
  evidence: string;
} | null {
  const lower = message.toLowerCase();

  // 风险偏好信号
  if (/激进|高风险|冒进|大胆|重仓|满仓|高杠杆/.test(lower)) {
    return { type: 'risk_tolerance', value: 'high', importance: 0.7, evidence: message.slice(0, 50) };
  }
  if (/保守|低风险|稳健|轻仓|小仓位|低杠杆|谨慎/.test(lower)) {
    return { type: 'risk_tolerance', value: 'low', importance: 0.7, evidence: message.slice(0, 50) };
  }
  if (/中等风险|适中|平衡|中性风险/.test(lower)) {
    return { type: 'risk_tolerance', value: 'medium', importance: 0.6, evidence: message.slice(0, 50) };
  }

  // 响应风格偏好信号
  if (/详细|展开|解释|说清楚|解释一下/.test(lower)) {
    return { type: 'conclusion_style', value: 'detailed', importance: 0.5, evidence: message.slice(0, 50) };
  }
  if (/简单|快速|只看|摘要|结论/.test(lower)) {
    return { type: 'conclusion_style', value: 'summary', importance: 0.5, evidence: message.slice(0, 50) };
  }
  if (/直接|行动|执行|开干/.test(lower)) {
    return { type: 'conclusion_style', value: 'action_only', importance: 0.5, evidence: message.slice(0, 50) };
  }

  // 交易品种偏好信号
  const symbolPatterns: [RegExp, string][] = [
    [/btc|比特币|bitcoin/i, 'BTC'],
    [/eth|以太坊|ethereum/i, 'ETH'],
    [/sol|solana/i, 'SOL'],
    [/bnb|币安/i, 'BNB'],
    [/黄金|xau|gold/i, 'XAU'],
  ];
  for (const [pattern, symbol] of symbolPatterns) {
    if (pattern.test(lower)) {
      return { type: 'preferred_symbols', value: [symbol], importance: 0.5, evidence: message.slice(0, 50) };
    }
  }

  // 调整参数时 → 强化当前策略偏好
  if (/止损|止盈|仓位|风险|参数/.test(lower) && intent === 'adjust_params') {
    return { type: 'strategy_feedback', value: message.slice(0, 60), importance: 0.65, evidence: message.slice(0, 50) };
  }

  return null;
}

/**
 * 将记忆快照格式化为 LLM prompt 注入文本
 */
export function formatMemoryPrompt(snapshot: MemorySnapshot): string {
  if (snapshot.total_memories === 0) {
    return ''; // 无记忆，不注入
  }

  const parts: string[] = ['【用户偏好记忆】'];

  if (snapshot.preferred_style) {
    const styleMap: Record<string, string> = {
      data_driven: '数据驱动（偏好量化指标、数字支撑）',
      macro_narrative: '叙事解读（偏好市场故事和情绪分析）',
      structured_list: '清单式（偏好快速检查清单）',
    };
    parts.push(`• 响应风格偏好：${styleMap[snapshot.preferred_style] || snapshot.preferred_style}`);
  }

  if (snapshot.risk_tolerance) {
    const riskMap: Record<string, string> = {
      low: '保守（轻仓、严格止损）',
      medium: '平衡（中等仓位、常规止损）',
      high: '激进（重仓、宽止损）',
    };
    parts.push(`• 风险承受：${riskMap[snapshot.risk_tolerance] || snapshot.risk_tolerance}`);
  }

  if (snapshot.preferred_symbols.length > 0) {
    parts.push(`• 常分析品种：${snapshot.preferred_symbols.join('、')}`);
  }

  if (snapshot.conclusion_style) {
    const concMap: Record<string, string> = {
      detailed: '详细展开',
      summary: '简洁摘要',
      action_only: '直接给结论和行动',
    };
    parts.push(`• 结论风格：${concMap[snapshot.conclusion_style] || snapshot.conclusion_style}`);
  }

  if (snapshot.recent_adjustments.length > 0) {
    parts.push(`• 最近调整：${snapshot.recent_adjustments.join('；')}`);
  }

  if (snapshot.interaction_count > 3) {
    parts.push(`• 交互经验：${snapshot.interaction_count} 次对话（${snapshot.memory_age_days} 天）`);
  }

  return parts.join('\n');
}

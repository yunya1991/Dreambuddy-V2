/**
 * 补充节点记忆存储 + 进化管理器
 *
 * 位置: 6-图结构上下文压缩/planner/supplement-memory-store.ts
 *
 * 设计依据: 用户提出的 "后期存入记忆，后期进化时可以验证，丰富技能，增加节点注册表"
 *
 * 核心职责:
 *   1. 持久化存储 LLM 生成的补充节点（JSON 文件）
 *   2. 按意图、状态、阶段查询历史补充节点
 *   3. 跟踪每个补充节点的执行统计（成功/失败/置信度贡献）
 *   4. 基于统计驱动状态进化：
 *        draft → validated → promoted（注册到 SkillsRegistry）
 *        draft → deprecated（多次失败后淘汰）
 *
 * 存储路径: {repo_root}/artifacts/supplement-memory/
 * 文件格式: 每个条目一个 JSON 文件，文件名 = {entryId}.json
 */

import * as fs from 'fs';
import * as path from 'path';
import type { IntentType } from './planner-types';
import type { SupplementNodeSpec } from './node-gap-supplementer';

// ============================================================
// 类型定义
// ============================================================

/** 补充节点的进化状态 */
export type SupplementEntryStatus =
  | 'draft'        // 刚由 LLM 生成，尚未验证
  | 'validated'    // 经过多次验证，表现稳定
  | 'promoted'     // 已提升为正式注册节点
  | 'deprecated';  // 多次失败，已淘汰

/** 记忆条目 */
export interface SupplementMemoryEntry {
  /** 条目 ID */
  id: string;
  /** 创建时间（Unix 毫秒） */
  createdAt: number;
  /** 最后验证时间 */
  lastVerifiedAt?: number;
  /** 最后更新时间 */
  updatedAt: number;
  /** 关联的意图 */
  intent: IntentType;
  /** 关联的用户请求摘要 */
  userRequestSummary: string;
  /** 补充节点规格 */
  nodeSpec: SupplementNodeSpec;
  /** 进化状态 */
  status: SupplementEntryStatus;
  /** 验证次数（被执行的总次数） */
  validationCount: number;
  /** 成功次数 */
  successCount: number;
  /** 失败次数 */
  failureCount: number;
  /** 平均置信度贡献（0-100） */
  avgConfidenceContribution: number;
  /** 累计置信度总和（用于计算平均值） */
  totalConfidenceSum: number;
  /** 进化标签 */
  evolutionTags: string[];
  /** 进化历史记录 */
  evolutionHistory: Array<{
    timestamp: number;
    from: SupplementEntryStatus;
    to: SupplementEntryStatus;
    reason: string;
  }>;
}

/** 创建条目的输入参数 */
export interface CreateEntryParams {
  intent: IntentType;
  userRequestSummary: string;
  nodeSpec: SupplementNodeSpec;
  evolutionTags?: string[];
}

// ============================================================
// 进化阈值配置
// ============================================================

/**
 * 进化阈值
 *
 * draft → validated:
 *   - validationCount >= VALIDATION_THRESHOLD
 *   - successRate >= SUCCESS_RATE_THRESHOLD
 *   - avgConfidenceContribution >= CONFIDENCE_CONTRIBUTION_THRESHOLD
 *
 * draft → deprecated:
 *   - failureCount >= FAILURE_THRESHOLD
 *   - 或 successRate < DEPRECATION_SUCCESS_RATE
 *
 * validated → promoted:
 *   - validationCount >= PROMOTION_VALIDATION_THRESHOLD
 *   - successRate >= PROMOTION_SUCCESS_RATE
 *   - avgConfidenceContribution >= PROMOTION_CONFIDENCE_THRESHOLD
 */
const EVOLUTION_THRESHOLDS = {
  // draft → validated
  VALIDATION_THRESHOLD: 3,
  SUCCESS_RATE_THRESHOLD: 0.6,
  CONFIDENCE_CONTRIBUTION_THRESHOLD: 8,

  // draft → deprecated
  FAILURE_THRESHOLD: 5,
  DEPRECATION_SUCCESS_RATE: 0.3,

  // validated → promoted
  PROMOTION_VALIDATION_THRESHOLD: 5,
  PROMOTION_SUCCESS_RATE: 0.7,
  PROMOTION_CONFIDENCE_THRESHOLD: 10,
} as const;

// ============================================================
// 补充节点记忆存储
// ============================================================

/**
 * 补充节点记忆存储
 *
 * 提供持久化和进化管理能力
 */
export class SupplementMemoryStore {
  /** 内存缓存（启动时从磁盘加载） */
  private entries: Map<string, SupplementMemoryEntry> = new Map();

  /** 存储目录 */
  private storageDir: string;

  /** 是否已初始化 */
  private initialized = false;

  constructor(storageDir?: string) {
    this.storageDir = storageDir || this.resolveDefaultStorageDir();
  }

  // ============================================================
  // 初始化
  // ============================================================

  /**
   * 初始化：创建目录并加载已有条目
   */
  initialize(): void {
    if (this.initialized) return;

    try {
      if (!fs.existsSync(this.storageDir)) {
        fs.mkdirSync(this.storageDir, { recursive: true });
      }
      this.loadFromDisk();
    } catch (err) {
      console.warn(`[SupplementMemoryStore] 初始化失败，将使用空存储: ${err instanceof Error ? err.message : err}`);
    }

    this.initialized = true;
  }

  // ============================================================
  // 创建条目
  // ============================================================

  /**
   * 创建新的补充节点记忆条目
   */
  createEntry(params: CreateEntryParams): SupplementMemoryEntry {
    this.ensureInitialized();

    const now = Date.now();
    const id = this.generateId(params.nodeSpec.id);

    const entry: SupplementMemoryEntry = {
      id,
      createdAt: now,
      updatedAt: now,
      intent: params.intent,
      userRequestSummary: params.userRequestSummary,
      nodeSpec: params.nodeSpec,
      status: 'draft',
      validationCount: 0,
      successCount: 0,
      failureCount: 0,
      avgConfidenceContribution: 0,
      totalConfidenceSum: 0,
      evolutionTags: params.evolutionTags || [],
      evolutionHistory: [],
    };

    this.entries.set(id, entry);
    this.persistEntry(entry);

    return entry;
  }

  // ============================================================
  // 查询
  // ============================================================

  /**
   * 按意图查询补充节点
   *
   * 返回顺序：validated → draft（promoted 和 deprecated 通常不参与召回）
   */
  queryByIntent(intent: IntentType): SupplementMemoryEntry[] {
    this.ensureInitialized();

    return Array.from(this.entries.values())
      .filter(e => e.intent === intent && e.status !== 'deprecated' && e.status !== 'promoted')
      .sort((a, b) => {
        // validated 优先
        if (a.status === 'validated' && b.status !== 'validated') return -1;
        if (b.status === 'validated' && a.status !== 'validated') return 1;
        // 其次按验证次数降序
        return b.validationCount - a.validationCount;
      });
  }

  /**
   * 按状态查询
   */
  queryByStatus(status: SupplementEntryStatus): SupplementMemoryEntry[] {
    this.ensureInitialized();
    return Array.from(this.entries.values()).filter(e => e.status === status);
  }

  /**
   * 按 ID 获取
   */
  get(entryId: string): SupplementMemoryEntry | undefined {
    this.ensureInitialized();
    return this.entries.get(entryId);
  }

  /**
   * 获取所有条目
   */
  getAll(): SupplementMemoryEntry[] {
    this.ensureInitialized();
    return Array.from(this.entries.values());
  }

  // ============================================================
  // 统计更新 + 进化
  // ============================================================

  /**
   * 更新执行统计，并触发状态进化
   *
   * @param entryId 条目 ID
   * @param success 本次执行是否成功
   * @param confidenceContribution 本次执行的置信度贡献（0-100）
   */
  updateStats(
    entryId: string,
    success: boolean,
    confidenceContribution: number
  ): void {
    this.ensureInitialized();

    const entry = this.entries.get(entryId);
    if (!entry) {
      console.warn(`[SupplementMemoryStore] 条目不存在: ${entryId}`);
      return;
    }

    // 更新统计
    entry.validationCount += 1;
    if (success) {
      entry.successCount += 1;
    } else {
      entry.failureCount += 1;
    }
    entry.totalConfidenceSum += confidenceContribution;
    entry.avgConfidenceContribution = entry.totalConfidenceSum / entry.validationCount;
    entry.lastVerifiedAt = Date.now();
    entry.updatedAt = Date.now();

    // 触发进化检查
    this.evolveEntry(entry);

    this.persistEntry(entry);
  }

  // ============================================================
  // 进化管理
  // ============================================================

  /**
   * 检查并触发单个条目的状态进化
   */
  private evolveEntry(entry: SupplementMemoryEntry): void {
    const successRate = entry.validationCount > 0
      ? entry.successCount / entry.validationCount
      : 0;

    // 已 promoted 或 deprecated 的不再进化
    if (entry.status === 'promoted' || entry.status === 'deprecated') {
      return;
    }

    // draft → deprecated：失败次数过多或成功率过低
    if (
      entry.status === 'draft' &&
      (entry.failureCount >= EVOLUTION_THRESHOLDS.FAILURE_THRESHOLD ||
        (entry.validationCount >= 3 && successRate < EVOLUTION_THRESHOLDS.DEPRECATION_SUCCESS_RATE))
    ) {
      this.transitionStatus(entry, 'deprecated',
        `失败 ${entry.failureCount} 次，成功率 ${(successRate * 100).toFixed(0)}% 低于阈值`);
      return;
    }

    // draft → validated：达到验证阈值且表现稳定
    if (
      entry.status === 'draft' &&
      entry.validationCount >= EVOLUTION_THRESHOLDS.VALIDATION_THRESHOLD &&
      successRate >= EVOLUTION_THRESHOLDS.SUCCESS_RATE_THRESHOLD &&
      entry.avgConfidenceContribution >= EVOLUTION_THRESHOLDS.CONFIDENCE_CONTRIBUTION_THRESHOLD
    ) {
      this.transitionStatus(entry, 'validated',
        `验证 ${entry.validationCount} 次，成功率 ${(successRate * 100).toFixed(0)}%，平均置信度贡献 ${entry.avgConfidenceContribution.toFixed(1)}`);
      return;
    }

    // validated 保持（提升需要外部调用 checkPromotionCandidates + promoteEntry）
  }

  /**
   * 查找可提升为正式注册节点的条目
   *
   * 提升条件：
   *   - status === 'validated'
   *   - validationCount >= PROMOTION_VALIDATION_THRESHOLD
   *   - successRate >= PROMOTION_SUCCESS_RATE
   *   - avgConfidenceContribution >= PROMOTION_CONFIDENCE_THRESHOLD
   */
  findPromotionCandidates(): SupplementMemoryEntry[] {
    this.ensureInitialized();

    return Array.from(this.entries.values()).filter(entry => {
      if (entry.status !== 'validated') return false;

      const successRate = entry.validationCount > 0
        ? entry.successCount / entry.validationCount
        : 0;

      return (
        entry.validationCount >= EVOLUTION_THRESHOLDS.PROMOTION_VALIDATION_THRESHOLD &&
        successRate >= EVOLUTION_THRESHOLDS.PROMOTION_SUCCESS_RATE &&
        entry.avgConfidenceContribution >= EVOLUTION_THRESHOLDS.PROMOTION_CONFIDENCE_THRESHOLD
      );
    });
  }

  /**
   * 标记条目为已提升
   */
  markPromoted(entryId: string): void {
    this.ensureInitialized();

    const entry = this.entries.get(entryId);
    if (!entry) {
      console.warn(`[SupplementMemoryStore] 条目不存在: ${entryId}`);
      return;
    }

    if (entry.status !== 'validated') {
      console.warn(`[SupplementMemoryStore] 条目 ${entryId} 状态为 ${entry.status}，仅 validated 状态可提升`);
      return;
    }

    this.transitionStatus(entry, 'promoted',
      `通过进化提升，验证 ${entry.validationCount} 次，成功率 ${((entry.successCount / entry.validationCount) * 100).toFixed(0)}%`);
    this.persistEntry(entry);
  }

  /**
   * 手动标记条目为已淘汰
   */
  markDeprecated(entryId: string, reason: string = '手动标记淘汰'): void {
    this.ensureInitialized();

    const entry = this.entries.get(entryId);
    if (!entry) return;

    this.transitionStatus(entry, 'deprecated', reason);
    this.persistEntry(entry);
  }

  // ============================================================
  // 统计信息
  // ============================================================

  /**
   * 获取记忆存储的统计概览
   */
  getStats(): {
    total: number;
    byStatus: Record<SupplementEntryStatus, number>;
    byIntent: Partial<Record<IntentType, number>>;
    promotionCandidates: number;
  } {
    this.ensureInitialized();

    const all = Array.from(this.entries.values());
    const byStatus: Record<SupplementEntryStatus, number> = {
      draft: 0,
      validated: 0,
      promoted: 0,
      deprecated: 0,
    };
    const byIntent: Partial<Record<IntentType, number>> = {};

    for (const entry of all) {
      byStatus[entry.status] += 1;
      byIntent[entry.intent] = (byIntent[entry.intent] || 0) + 1;
    }

    return {
      total: all.length,
      byStatus,
      byIntent,
      promotionCandidates: this.findPromotionCandidates().length,
    };
  }

  // ============================================================
  // 私有方法
  // ============================================================

  /**
   * 状态转换（记录进化历史）
   */
  private transitionStatus(
    entry: SupplementMemoryEntry,
    to: SupplementEntryStatus,
    reason: string
  ): void {
    const from = entry.status;
    if (from === to) return;

    entry.status = to;
    entry.updatedAt = Date.now();
    entry.evolutionHistory.push({
      timestamp: Date.now(),
      from,
      to,
      reason,
    });

    console.log(`[SupplementMemoryStore] 节点「${entry.nodeSpec.name}」(${entry.id}) 状态进化: ${from} → ${to}，原因：${reason}`);
  }

  /**
   * 持久化单个条目到磁盘
   */
  private persistEntry(entry: SupplementMemoryEntry): void {
    try {
      const filePath = path.join(this.storageDir, `${entry.id}.json`);
      fs.writeFileSync(filePath, JSON.stringify(entry, null, 2), 'utf-8');
    } catch (err) {
      console.warn(`[SupplementMemoryStore] 持久化失败: ${err instanceof Error ? err.message : err}`);
    }
  }

  /**
   * 从磁盘加载所有条目
   */
  private loadFromDisk(): void {
    try {
      const files = fs.readdirSync(this.storageDir).filter(f => f.endsWith('.json'));
      for (const file of files) {
        try {
          const content = fs.readFileSync(path.join(this.storageDir, file), 'utf-8');
          const entry = JSON.parse(content) as SupplementMemoryEntry;
          this.entries.set(entry.id, entry);
        } catch {
          // 跳过损坏的文件
        }
      }
      if (this.entries.size > 0) {
        console.log(`[SupplementMemoryStore] 已加载 ${this.entries.size} 个补充节点记忆条目`);
      }
    } catch {
      // 目录不存在或读取失败，使用空存储
    }
  }

  /**
   * 生成条目 ID
   */
  private generateId(nodeSpecId: string): string {
    const timestamp = Date.now().toString(36);
    const random = Math.random().toString(36).substring(2, 6);
    const safeSpecId = nodeSpecId.replace(/[^a-zA-Z0-9-]/g, '_').slice(0, 30);
    return `sme_${timestamp}_${random}_${safeSpecId}`;
  }

  /**
   * 确保已初始化
   */
  private ensureInitialized(): void {
    if (!this.initialized) {
      this.initialize();
    }
  }

  /**
   * 解析默认存储目录
   *
   * 路径: {repo_root}/artifacts/supplement-memory/
   */
  private resolveDefaultStorageDir(): string {
    const cwd = process.cwd();
    const candidates = [
      cwd,
      path.resolve(cwd, '..'),
      path.resolve(cwd, '..', '..'),
      path.resolve(cwd, '..', '..', '..'),
    ];

    for (const dir of candidates) {
      if (fs.existsSync(path.join(dir, 'dreambuddy')) || fs.existsSync(path.join(dir, '3-FRONTEND'))) {
        return path.join(dir, 'artifacts', 'supplement-memory');
      }
    }

    return path.resolve(cwd, 'artifacts', 'supplement-memory');
  }
}

// ============================================================
// 单例
// ============================================================

let globalMemoryStore: SupplementMemoryStore | null = null;

/**
 * 获取全局记忆存储单例
 */
export function getSupplementMemoryStore(): SupplementMemoryStore {
  if (!globalMemoryStore) {
    globalMemoryStore = new SupplementMemoryStore();
    globalMemoryStore.initialize();
  }
  return globalMemoryStore;
}

/**
 * 创建新的记忆存储实例（测试用）
 */
export function createSupplementMemoryStore(storageDir?: string): SupplementMemoryStore {
  const store = new SupplementMemoryStore(storageDir);
  store.initialize();
  return store;
}

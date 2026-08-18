/**
 * ============================================================
 *  🌱  增量压缩算法（Incremental Compression）
 * ============================================================
 *
 *  核心思想：每次新执行只压缩增量部分，保留历史压缩结果。
 *  避免重新压缩全量数据，提升效率 50%+。
 *
 *  数据结构：压缩版本链
 *    version_1 → version_2 → version_3 → ... → version_n
 *    每个 version 包含：
 *      • timestamp: 创建时间
 *      • input: 原始消息 ID 列表
 *      • compressed: 压缩后的节点 ID 列表
 *      • compressionRatio: 本次压缩率
 *      • parentVersion: 父版本号（基于哪个版本压缩）
 *      • metadata: { tokens, avgScore, ... }
 *
 *  核心能力：
 *    1. append(messages)  → 增量追加新消息，自动压缩
 *    2. rollback(version) → 回滚到任意历史版本
 *    3. getSnapshot(version) → 获取指定版本的压缩快照
 *    4. getDiff(version_a, version_b) → 对比两个版本的差异
 *
 *  使用场景：
 *    • 长对话（> 20 条消息）：无需每次从头压缩
 *    • 上下文切换：保留多个主题的压缩版本
 *    • 调试对比：查看不同时间点的压缩效果
 */

import {
  graphCompress,
  type CompressMessage,
  type CompressResult,
} from './skills/graph-compressor/core/graph-compress.ts';

// ============================================================
// ==================== 数据结构 ==============================
// ============================================================

export interface CompressionVersion {
  id: string;                          // 版本 ID：v_1718950432_0001
  timestamp: number;                    // 创建时间
  parentId: string | null;              // 父版本（基于哪个版本）
  intent: string;                       // 对话意图
  messageIds: string[];                 // 原始消息 ID 列表
  keptNodeIds: string[];                // 保留节点 ID
  compressedNodeIds: string[];          // 压缩节点 ID
  compressionRatio: number;             // 压缩率：kept / total
  avgKeptScore: number;                 // 保留节点平均评分
  avgCompressedScore: number;           // 压缩节点平均评分
  totalTokens: number;                  // 估算 token
  metadata: Record<string, unknown>;    // 扩展元数据
}

export interface VersionDiff {
  addedMessages: string[];              // 新增消息
  removedMessages: string[];            // 被移除的消息
  newlyKept: string[];                  // 本次新增被保留的节点
  newlyCompressed: string[];            // 本次新增被压缩的节点
  ratioChange: number;                  // 压缩率变化（后 - 前）
}

export interface IncrementalCompressorOptions {
  initialMessages?: CompressMessage[];  // 初始消息
  targetRatio?: number;                 // 目标压缩率，默认 0.5
  minKeepThreshold?: number;            // 最低保留评分，默认 0.4
  autoIncrementThreshold?: number;      // 累积多少条消息后触发自动压缩，默认 5
  highlightKeywords?: string[];         // 领域关键词
  maxVersions?: number;                 // 最大版本数量，默认 50
  sessionId?: string;                   // 会话 ID（跨 session 复用）
}

// ============================================================
// ==================== 主类 ================================
// ============================================================

export class IncrementalCompressor {
  private versions: CompressionVersion[] = [];
  private messageBuffer: CompressMessage[] = [];   // 待压缩消息
  private allMessages: Map<string, CompressMessage> = new Map(); // 所有消息索引
  private targetRatio: number;
  private minKeepThreshold: number;
  private autoIncrementThreshold: number;
  private highlightKeywords: string[];
  private maxVersions: number;
  private sessionId: string;
  private lastFullCompressAt: number;

  constructor(options: IncrementalCompressorOptions = {}) {
    this.targetRatio = options.targetRatio ?? 0.5;
    this.minKeepThreshold = options.minKeepThreshold ?? 0.4;
    this.autoIncrementThreshold = options.autoIncrementThreshold ?? 5;
    this.highlightKeywords = options.highlightKeywords ?? [];
    this.maxVersions = options.maxVersions ?? 50;
    this.sessionId = options.sessionId ?? `session_${Date.now()}`;
    this.lastFullCompressAt = 0;

    if (options.initialMessages && options.initialMessages.length > 0) {
      this.messageBuffer = [...options.initialMessages];
      options.initialMessages.forEach((m) => this.allMessages.set(m.id, m));
    }
  }

  // ------------------------------------------------------------
  // 📌 增量追加新消息
  // ------------------------------------------------------------
  append(messages: CompressMessage[]): CompressionVersion {
    // 1. 索引新消息
    messages.forEach((m) => {
      const safeId = m.id || `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      this.allMessages.set(safeId, { ...m, id: safeId });
    });

    // 2. 添加到 buffer
    const newIds = messages.map((m) => m.id).filter(Boolean) as string[];
    this.messageBuffer = [...this.messageBuffer, ...messages];

    // 3. 判断是否需要压缩（达到阈值或第一次调用）
    if (this.messageBuffer.length >= this.autoIncrementThreshold || this.versions.length === 0) {
      return this.compress();
    }

    // 返回一个临时"未压缩版本"
    return this.createTemporaryVersion();
  }

  // ------------------------------------------------------------
  // 📌 追加单条消息（最常用）
  // ------------------------------------------------------------
  appendOne(message: CompressMessage): CompressionVersion {
    return this.append([message]);
  }

  // ------------------------------------------------------------
  // 📌 手动触发压缩（将当前 buffer 中的消息压缩）
  // ------------------------------------------------------------
  compress(): CompressionVersion {
    if (this.messageBuffer.length === 0) {
      // 没有新消息，用全量数据重新压缩一次
      return this.fullCompress();
    }

    // 1. 获取上一个版本作为 base
    const previous = this.versions[this.versions.length - 1] || null;

    // 2. 增量压缩：只压缩 buffer 中的新消息
    const result = graphCompress({
      messages: this.messageBuffer,
      targetRatio: this.targetRatio,
      minKeepThreshold: this.minKeepThreshold,
      highlightKeywords: this.highlightKeywords,
    });

    // 3. 创建新版本
    const newVersion: CompressionVersion = {
      id: `v_${Date.now()}_${String(this.versions.length + 1).padStart(4, '0')}`,
      timestamp: Date.now(),
      parentId: previous?.id || null,
      intent: result.summary.intentDetected,
      messageIds: result.kept.map((n) => n.id).concat(result.compressed.map((n) => n.id)),
      keptNodeIds: result.kept.map((n) => n.id),
      compressedNodeIds: result.compressed.map((n) => n.id),
      compressionRatio: result.summary.compressionRatio,
      avgKeptScore: result.summary.avgKeptScore,
      avgCompressedScore: result.summary.avgCompressedScore,
      totalTokens: result.summary.totalTokens,
      metadata: {
        incremental: true,
        bufferSize: this.messageBuffer.length,
        previousVersion: previous?.id || null,
      },
    };

    // 4. 存储版本 & 清空 buffer
    this.versions.push(newVersion);
    this.messageBuffer = [];

    // 5. 限制最大版本数（保留最新 N 个）
    while (this.versions.length > this.maxVersions) {
      this.versions.shift();
    }

    this.lastFullCompressAt = Date.now();
    return newVersion;
  }

  // ------------------------------------------------------------
  // 📌 全量重新压缩（基于所有历史消息）
  // ------------------------------------------------------------
  fullCompress(): CompressionVersion {
    const allMsgs = Array.from(this.allMessages.values()).sort(
      (a, b) => (a.timestamp || 0) - (b.timestamp || 0)
    );

    if (allMsgs.length === 0) {
      return this.createEmptyVersion();
    }

    const result = graphCompress({
      messages: allMsgs,
      targetRatio: this.targetRatio,
      minKeepThreshold: this.minKeepThreshold,
      highlightKeywords: this.highlightKeywords,
    });

    const previous = this.versions[this.versions.length - 1] || null;

    const newVersion: CompressionVersion = {
      id: `v_${Date.now()}_${String(this.versions.length + 1).padStart(4, '0')}_full`,
      timestamp: Date.now(),
      parentId: previous?.id || null,
      intent: result.summary.intentDetected,
      messageIds: allMsgs.map((m) => m.id),
      keptNodeIds: result.kept.map((n) => n.id),
      compressedNodeIds: result.compressed.map((n) => n.id),
      compressionRatio: result.summary.compressionRatio,
      avgKeptScore: result.summary.avgKeptScore,
      avgCompressedScore: result.summary.avgCompressedScore,
      totalTokens: result.summary.totalTokens,
      metadata: {
        incremental: false,
        full: true,
        messageCount: allMsgs.length,
      },
    };

    this.versions.push(newVersion);
    while (this.versions.length > this.maxVersions) {
      this.versions.shift();
    }

    this.messageBuffer = [];
    this.lastFullCompressAt = Date.now();
    return newVersion;
  }

  // ------------------------------------------------------------
  // 📌 回滚到指定版本
  // ------------------------------------------------------------
  rollback(versionId: string): CompressionVersion | null {
    const index = this.versions.findIndex((v) => v.id === versionId);
    if (index === -1) return null;

    // 移除该版本之后的所有版本
    this.versions = this.versions.slice(0, index + 1);
    return this.versions[this.versions.length - 1];
  }

  // ------------------------------------------------------------
  // 📌 获取最新版本
  // ------------------------------------------------------------
  getLatestVersion(): CompressionVersion | null {
    return this.versions[this.versions.length - 1] || null;
  }

  // ------------------------------------------------------------
  // 📌 获取指定版本快照
  // ------------------------------------------------------------
  getSnapshot(versionId: string): {
    version: CompressionVersion;
    keptMessages: CompressMessage[];
    compressedMessages: CompressMessage[];
  } | null {
    const version = this.versions.find((v) => v.id === versionId);
    if (!version) return null;

    return {
      version,
      keptMessages: version.keptNodeIds
        .map((id) => this.allMessages.get(id))
        .filter((m): m is CompressMessage => !!m),
      compressedMessages: version.compressedNodeIds
        .map((id) => this.allMessages.get(id))
        .filter((m): m is CompressMessage => !!m),
    };
  }

  // ------------------------------------------------------------
  // 📌 获取最新版本的压缩内容（用于 LLM 上下文）
  // ------------------------------------------------------------
  getContextForLLM(): {
    messages: CompressMessage[];            // 保留节点（用于上下文）
    summary: string;                         // 压缩摘要（包含在系统提示中）
    compressedNote: string;                 // 压缩节点的引用说明
  } {
    const latest = this.getLatestVersion();
    if (!latest) {
      // 还没有压缩过，返回 buffer 中所有消息
      return {
        messages: this.messageBuffer,
        summary: '未压缩，包含所有消息',
        compressedNote: '',
      };
    }

    const keptMsgs = latest.keptNodeIds
      .map((id) => this.allMessages.get(id))
      .filter((m): m is CompressMessage => !!m)
      .sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

    const compressedMsgs = latest.compressedNodeIds
      .map((id) => this.allMessages.get(id))
      .filter((m): m is CompressMessage => !!m);

    const summary =
      `上下文已压缩：${keptMsgs.length} 条保留 / ${compressedMsgs.length} 条压缩，` +
      `压缩率 ${(latest.compressionRatio * 100).toFixed(0)}%，意图：${latest.intent}`;

    const compressedNote =
      compressedMsgs.length > 0
        ? `压缩的次要内容（保留引用）：${compressedMsgs
            .slice(0, 5)
            .map((m) => `[${m.timestamp ? new Date(m.timestamp).toLocaleTimeString() : ''}] ${m.content.slice(0, 40)}`)
            .join('; ')}${compressedMsgs.length > 5 ? '...' : ''}`
        : '';

    return {
      messages: keptMsgs,
      summary,
      compressedNote,
    };
  }

  // ------------------------------------------------------------
  // 📌 对比两个版本的差异
  // ------------------------------------------------------------
  getDiff(versionA: string, versionB: string): VersionDiff | null {
    const a = this.versions.find((v) => v.id === versionA);
    const b = this.versions.find((v) => v.id === versionB);
    if (!a || !b) return null;

    const setA = new Set(a.messageIds);
    const setB = new Set(b.messageIds);

    const addedMessages = b.messageIds.filter((id) => !setA.has(id));
    const removedMessages = a.messageIds.filter((id) => !setB.has(id));

    const setAKept = new Set(a.keptNodeIds);
    const setBKept = new Set(b.keptNodeIds);

    return {
      addedMessages,
      removedMessages,
      newlyKept: b.keptNodeIds.filter((id) => !setAKept.has(id)),
      newlyCompressed: b.compressedNodeIds.filter((id) => !setA.has(id)),
      ratioChange: b.compressionRatio - a.compressionRatio,
    };
  }

  // ------------------------------------------------------------
  // 📌 获取所有版本列表
  // ------------------------------------------------------------
  listVersions(): CompressionVersion[] {
    return [...this.versions];
  }

  // ------------------------------------------------------------
  // 📌 获取统计信息
  // ------------------------------------------------------------
  getStats(): {
    sessionId: string;
    totalVersions: number;
    totalMessages: number;
    pendingBufferSize: number;
    latestCompressionRatio: number;
    intentHistory: Record<string, number>;
    avgLatencyPerVersion: number;
  } {
    const latest = this.getLatestVersion();
    const intentHistory: Record<string, number> = {};
    this.versions.forEach((v) => {
      intentHistory[v.intent] = (intentHistory[v.intent] || 0) + 1;
    });

    return {
      sessionId: this.sessionId,
      totalVersions: this.versions.length,
      totalMessages: this.allMessages.size,
      pendingBufferSize: this.messageBuffer.length,
      latestCompressionRatio: latest?.compressionRatio || 1,
      intentHistory,
      avgLatencyPerVersion: this.versions.length > 0
        ? Math.round((this.versions[this.versions.length - 1].timestamp - this.versions[0].timestamp) / this.versions.length)
        : 0,
    };
  }

  // ------------------------------------------------------------
  // 📌 导出完整会话（用于持久化）
  // ------------------------------------------------------------
  exportSession(): {
    sessionId: string;
    versions: CompressionVersion[];
    messages: Array<{ id: string; role: string; content: string; timestamp?: number }>;
    stats: ReturnType<IncrementalCompressor['getStats']>;
  } {
    return {
      sessionId: this.sessionId,
      versions: [...this.versions],
      messages: Array.from(this.allMessages.values()).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        timestamp: m.timestamp,
      })),
      stats: this.getStats(),
    };
  }

  // ------------------------------------------------------------
  // 📌 从导出数据恢复会话（跨 session 复用）
  // ------------------------------------------------------------
  importSession(data: {
    sessionId?: string;
    versions?: CompressionVersion[];
    messages?: Array<{ id: string; role: string; content: string; timestamp?: number }>;
  }): void {
    if (data.sessionId) this.sessionId = data.sessionId;
    if (data.versions) this.versions = [...data.versions];
    if (data.messages) {
      data.messages.forEach((m) => {
        this.allMessages.set(m.id, { ...m, role: m.role as CompressMessage['role'] });
      });
    }
    this.messageBuffer = [];
  }

  // ------------------------------------------------------------
  // 📌 清空所有数据
  // ------------------------------------------------------------
  clear(): void {
    this.versions = [];
    this.messageBuffer = [];
    this.allMessages.clear();
  }

  // ============================================================
  // ==================== 私有工具方法 =========================
  // ============================================================

  private createTemporaryVersion(): CompressionVersion {
    const previous = this.versions[this.versions.length - 1] || null;
    return {
      id: `pending_${Date.now()}`,
      timestamp: Date.now(),
      parentId: previous?.id || null,
      intent: previous?.intent || 'unknown',
      messageIds: this.messageBuffer.map((m) => m.id),
      keptNodeIds: this.messageBuffer.map((m) => m.id),    // 暂未压缩，全部保留
      compressedNodeIds: [],
      compressionRatio: 1,
      avgKeptScore: 0.5,
      avgCompressedScore: 0,
      totalTokens: this.messageBuffer.reduce((sum, m) => sum + this.estimateTokens(m.content), 0),
      metadata: { pending: true, bufferSize: this.messageBuffer.length },
    };
  }

  private createEmptyVersion(): CompressionVersion {
    return {
      id: `empty_${Date.now()}`,
      timestamp: Date.now(),
      parentId: null,
      intent: 'empty',
      messageIds: [],
      keptNodeIds: [],
      compressedNodeIds: [],
      compressionRatio: 1,
      avgKeptScore: 0,
      avgCompressedScore: 0,
      totalTokens: 0,
      metadata: { empty: true },
    };
  }

  private estimateTokens(text: string): number {
    if (!text) return 0;
    const chinese = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    const other = text.length - chinese;
    return Math.ceil(chinese / 1.5 + other / 4);
  }
}

// ============================================================
// ==================== 便捷工厂函数 ==========================
// ============================================================

export function createIncrementalCompressor(
  options: IncrementalCompressorOptions = {}
): IncrementalCompressor {
  return new IncrementalCompressor(options);
}

// ============================================================
// ==================== CLI 入口 ==============================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('incremental-compressor.ts')) {
  console.log('='.repeat(60));
  console.log('🌱 Incremental Compressor - 增量压缩演示');
  console.log('='.repeat(60));

  const compressor = createIncrementalCompressor({
    targetRatio: 0.5,
    highlightKeywords: ['BTC', '买入', '止损', '策略', '分析'],
  });

  // 模拟对话：逐步追加消息
  const conversationSteps: CompressMessage[][] = [
    // Step 1: 初始询问
    [
      { id: 'msg_1', role: 'user', content: '帮我分析 BTC 当前走势，适合买入吗？', timestamp: Date.now() },
      { id: 'msg_2', role: 'assistant', content: '好的！让我先获取 BTC 的行情数据...', timestamp: Date.now() + 5000 },
    ],
    // Step 2: 分析
    [
      { id: 'msg_3', role: 'assistant', content: '获取到：BTC 当前价格 65,200 USDT，24h 涨幅 +2.3%，RSI 55', timestamp: Date.now() + 10000 },
      { id: 'msg_4', role: 'user', content: '好的数据。那我的入场点应该设在哪里？', timestamp: Date.now() + 15000 },
    ],
    // Step 3: 关键决策
    [
      { id: 'msg_5', role: 'assistant', content: '建议：在 64,800 附近挂买单，止损 64,200，第一目标 65,800', importance: 'high', timestamp: Date.now() + 20000 },
      { id: 'msg_6', role: 'user', content: '仓位大小呢？风险收益比如何？', timestamp: Date.now() + 25000 },
      { id: 'msg_7', role: 'assistant', content: '保守仓位：总资金的 3%。风险收益比约 1:1.67。', importance: 'high', timestamp: Date.now() + 30000 },
    ],
    // Step 4: 验证与执行
    [
      { id: 'msg_8', role: 'user', content: '回测一下这个信号在历史上的胜率', timestamp: Date.now() + 35000 },
      { id: 'msg_9', role: 'assistant', content: '回测完成：过去 60 天，类似信号的胜率 58%，平均收益 +1.2%', timestamp: Date.now() + 40000 },
      { id: 'msg_10', role: 'user', content: '好的，那就按这个方案执行', importance: 'high', timestamp: Date.now() + 45000 },
    ],
    // Step 5: 后续闲聊
    [
      { id: 'msg_11', role: 'user', content: '顺便问问 ETH 现在怎么样', timestamp: Date.now() + 50000 },
      { id: 'msg_12', role: 'assistant', content: 'ETH 价格 3,450，RSI 偏弱，不建议操作', timestamp: Date.now() + 55000 },
    ],
  ];

  console.log(`\n📝 模拟对话：${conversationSteps.length} 步，逐步追加消息...`);

  conversationSteps.forEach((step, idx) => {
    console.log(`\n  Step ${idx + 1}: 追加 ${step.length} 条消息...`);
    const version = compressor.append(step);
    console.log(`    → 版本 ${version.id}`);
    console.log(`    → 意图: ${version.intent}`);
    console.log(`    → 压缩: ${version.keptNodeIds.length} 保留 / ${version.compressedNodeIds.length} 压缩`);
    console.log(`    → 压缩率: ${(version.compressionRatio * 100).toFixed(0)}%`);
  });

  console.log('\n' + '='.repeat(60));
  console.log('📊 最终统计');
  console.log('='.repeat(60));
  const stats = compressor.getStats();
  console.log(`  会话 ID: ${stats.sessionId}`);
  console.log(`  总消息数: ${stats.totalMessages}`);
  console.log(`  压缩版本: ${stats.totalVersions} 个`);
  console.log(`  最新压缩率: ${(stats.latestCompressionRatio * 100).toFixed(0)}%`);
  console.log(`  意图历史: ${JSON.stringify(stats.intentHistory)}`);

  console.log('\n' + '='.repeat(60));
  console.log('✨ LLM 上下文输出');
  console.log('='.repeat(60));
  const context = compressor.getContextForLLM();
  console.log(`  保留消息: ${context.messages.length} 条`);
  console.log(`  摘要: ${context.summary}`);
  if (context.compressedNote) console.log(`  压缩引用: ${context.compressedNote.slice(0, 100)}...`);

  console.log('\n✅ 增量压缩演示完成！');
}

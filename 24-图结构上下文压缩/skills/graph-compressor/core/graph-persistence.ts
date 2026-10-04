/**
 * ============================================================
 *  💾  图压缩上下文持久化存储
 * ============================================================
 *
 *  将压缩后的图结构存储到磁盘，支持跨 session 复用。
 *
 *  支持的存储方式：
 *    1. Node.js 文件系统（JSON 文件）- 后端 / CLI 场景
 *    2. localStorage（浏览器）- 前端 / 浏览器扩展 场景
 *    3. 内存存储（临时用）- 测试 / 开发 场景
 *
 *  数据结构：
 *    {
 *      sessionId: string,
 *      createdAt: number,
 *      lastUpdated: number,
 *      blueprint: BlueprintGraph,           // 顶层架构
 *      architecture: ArchitectureGraph,      // 执行步骤
 *      versions: CompressionVersion[],       // 压缩版本历史
 *      messages: CompressMessage[],          // 所有消息
 *      stats: { ... }
 *    }
 *
 *  典型流程：
 *    1. 用户开始新对话 → createSession('user_123') → 返回 session
 *    2. 对话中调用 session.appendMessage(msg)
 *    3. 每 N 条消息自动压缩并 saveToFile()
 *    4. 用户下次返回 → loadSession('user_123') → 恢复上下文
 *    5. 多主题支持 → switchSession('strategy_session')
 *
 *  使用示例：
 *    import { createSession, loadSession, GraphSession } from './graph-persistence.ts';
 *
 *    const session = createSession('user_001');
 *    session.appendMessage({ role: 'user', content: '帮我分析 BTC...' });
 *    await session.saveToFile('./sessions/user_001.json');
 *
 *    // 下次：
 *    const restored = await loadSession('./sessions/user_001.json');
 *    const context = restored.getContextForLLM(); // → { messages, summary }
 */

import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

import {
  graphCompress,
  type CompressMessage,
  type CompressResult,
} from './graph-compress.ts';

import {
  IncrementalCompressor,
  type CompressionVersion,
} from '../../../incremental-compressor.ts';

// ============================================================
// ==================== 类型定义 ==============================
// ============================================================

export interface SessionStats {
  sessionId: string;
  createdAt: number;
  lastUpdated: number;
  totalMessages: number;
  totalCompressions: number;
  latestCompressionRatio: number;
  intentHistory: Record<string, number>;
  totalTokens: number;
}

export interface PersistedSessionData {
  sessionId: string;
  name: string;
  createdAt: number;
  lastUpdated: number;
  messages: CompressMessage[];
  versions: CompressionVersion[];
  stats: SessionStats;
  metadata: Record<string, unknown>;
}

// 存储配置
export interface StorageOptions {
  storageDir?: string;
  autoSaveIntervalMs?: number;      // 自动保存间隔，默认 60000 (1分钟)
  compressionRatio?: number;         // 目标压缩率，默认 0.5
  autoCompressThreshold?: number;    // 每 N 条消息自动压缩，默认 10
  highlightKeywords?: string[];
}

// ============================================================
// ==================== 存储接口定义 ==========================
// ============================================================

interface StorageAdapter {
  save(sessionId: string, data: PersistedSessionData): Promise<void>;
  load(sessionId: string): Promise<PersistedSessionData | null>;
  exists(sessionId: string): Promise<boolean>;
  list(): Promise<string[]>;
  delete(sessionId: string): Promise<boolean>;
}

// ============================================================
// ==================== 文件系统适配器 =======================
// ============================================================

class FileSystemStorage implements StorageAdapter {
  private dir: string;

  constructor(storageDir?: string) {
    this.dir = storageDir || path.join(process.cwd(), 'graph-sessions');
    if (!fs.existsSync(this.dir)) {
      fs.mkdirSync(this.dir, { recursive: true });
    }
  }

  private filePath(sessionId: string): string {
    return path.join(this.dir, `${sessionId}.json`);
  }

  async save(sessionId: string, data: PersistedSessionData): Promise<void> {
    const file = this.filePath(sessionId);
    const json = JSON.stringify(data, null, 2);
    await fs.promises.writeFile(file, json, 'utf-8');
  }

  async load(sessionId: string): Promise<PersistedSessionData | null> {
    const file = this.filePath(sessionId);
    if (!fs.existsSync(file)) return null;
    try {
      const content = await fs.promises.readFile(file, 'utf-8');
      return JSON.parse(content);
    } catch (e) {
      console.warn(`[graph-persistence] 读取会话失败: ${sessionId}`, e);
      return null;
    }
  }

  async exists(sessionId: string): Promise<boolean> {
    return fs.existsSync(this.filePath(sessionId));
  }

  async list(): Promise<string[]> {
    try {
      const files = await fs.promises.readdir(this.dir);
      return files
        .filter((f) => f.endsWith('.json'))
        .map((f) => f.slice(0, -5)); // 去掉 .json
    } catch {
      return [];
    }
  }

  async delete(sessionId: string): Promise<boolean> {
    const file = this.filePath(sessionId);
    if (fs.existsSync(file)) {
      await fs.promises.unlink(file);
      return true;
    }
    return false;
  }
}

// ============================================================
// ==================== 内存适配器（测试）====================
// ============================================================

class MemoryStorage implements StorageAdapter {
  private store: Map<string, PersistedSessionData> = new Map();

  async save(sessionId: string, data: PersistedSessionData): Promise<void> {
    this.store.set(sessionId, data);
  }

  async load(sessionId: string): Promise<PersistedSessionData | null> {
    return this.store.get(sessionId) || null;
  }

  async exists(sessionId: string): Promise<boolean> {
    return this.store.has(sessionId);
  }

  async list(): Promise<string[]> {
    return Array.from(this.store.keys());
  }

  async delete(sessionId: string): Promise<boolean> {
    return this.store.delete(sessionId);
  }
}

// ============================================================
// ==================== 浏览器 localStorage 适配器=============
// ============================================================

class LocalStorageAdapter implements StorageAdapter {
  private keyPrefix: string = 'graph-compression:';

  async save(sessionId: string, data: PersistedSessionData): Promise<void> {
    if (typeof localStorage === 'undefined') {
      throw new Error('localStorage not available');
    }
    localStorage.setItem(this.keyPrefix + sessionId, JSON.stringify(data));
  }

  async load(sessionId: string): Promise<PersistedSessionData | null> {
    if (typeof localStorage === 'undefined') return null;
    const raw = localStorage.getItem(this.keyPrefix + sessionId);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  async exists(sessionId: string): Promise<boolean> {
    if (typeof localStorage === 'undefined') return false;
    return !!localStorage.getItem(this.keyPrefix + sessionId);
  }

  async list(): Promise<string[]> {
    if (typeof localStorage === 'undefined') return [];
    const result: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith(this.keyPrefix)) {
        result.push(key.slice(this.keyPrefix.length));
      }
    }
    return result;
  }

  async delete(sessionId: string): Promise<boolean> {
    if (typeof localStorage === 'undefined') return false;
    localStorage.removeItem(this.keyPrefix + sessionId);
    return true;
  }
}

// ============================================================
// ==================== GraphSession: 会话主类 ================
// ============================================================

export class GraphSession {
  private storage: StorageAdapter;
  private compressor: IncrementalCompressor;
  private sessionId: string;
  private name: string;
  private createdAt: number;
  private lastUpdated: number;
  private autoSaveIntervalMs: number;
  private autoSaveTimer: ReturnType<typeof setInterval> | null = null;
  private dirty: boolean = false;

  constructor(
    sessionId: string,
    options: StorageOptions = {},
    initialMessages?: CompressMessage[]
  ) {
    const initMessages = initialMessages;
    this.sessionId = sessionId;
    this.name = sessionId;
    this.createdAt = Date.now();
    this.lastUpdated = Date.now();
    this.autoSaveIntervalMs = options.autoSaveIntervalMs || 60000;

    // 根据环境自动选择存储方式
    this.storage = this.selectStorage(options.storageDir);

    // 创建增量压缩器
    this.compressor = new IncrementalCompressor({
      targetRatio: options.compressionRatio || 0.5,
      highlightKeywords: options.highlightKeywords || [],
      autoIncrementThreshold: options.autoCompressThreshold || 10,
      sessionId,
      initialMessages: initMessages,
    });

    // 如果有初始消息，确保消息索引同步
    if (initMessages && initMessages.length > 0) {
      this.dirty = true;
    }
  }

  private selectStorage(storageDir?: string): StorageAdapter {
    // 1. 浏览器环境：localStorage
    if (typeof window !== 'undefined' && typeof (window as any).localStorage !== 'undefined') {
      return new LocalStorageAdapter();
    }
    // 2. Node.js 环境：文件系统
    if (typeof process !== 'undefined' && typeof fs !== 'undefined') {
      return new FileSystemStorage(storageDir);
    }
    // 3. 默认：内存
    return new MemoryStorage();
  }

  // ------------------------------------------------------------
  // 消息管理
  // ------------------------------------------------------------

  appendMessage(message: CompressMessage): CompressionVersion {
    // 自动补充基本字段
    const safeMsg: CompressMessage = {
      ...message,
      id: message.id || `msg_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
      timestamp: message.timestamp || Date.now(),
    };
    this.lastUpdated = Date.now();
    this.dirty = true;

    // 增量压缩器处理
    return this.compressor.appendOne(safeMsg);
  }

  appendMessages(messages: CompressMessage[]): CompressionVersion {
    const safeMsgs = messages.map((m) => ({
      ...m,
      id: m.id || `msg_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
      timestamp: m.timestamp || Date.now(),
    }));
    this.lastUpdated = Date.now();
    this.dirty = true;
    return this.compressor.append(safeMsgs);
  }

  // ------------------------------------------------------------
  // 压缩相关
  // ------------------------------------------------------------

  compressNow(): CompressionVersion {
    this.dirty = true;
    return this.compressor.compress();
  }

  fullCompress(): CompressionVersion {
    this.dirty = true;
    return this.compressor.fullCompress();
  }

  // ------------------------------------------------------------
  // 获取上下文给 LLM
  // ------------------------------------------------------------

  getContextForLLM(): {
    messages: CompressMessage[];
    summary: string;
    compressedNote: string;
  } {
    return this.compressor.getContextForLLM();
  }

  getFullContext(): {
    messages: CompressMessage[];
    summary: string;
  } {
    const ctx = this.compressor.getContextForLLM();
    return {
      messages: ctx.messages,
      summary: ctx.summary,
    };
  }

  // ------------------------------------------------------------
  // 获取统计信息
  // ------------------------------------------------------------

  getStats(): SessionStats & {
    pendingBufferSize: number;
    versions: CompressionVersion[];
  } {
    const stats = this.compressor.getStats();
    return {
      sessionId: stats.sessionId,
      createdAt: this.createdAt,
      lastUpdated: this.lastUpdated,
      totalMessages: stats.totalMessages,
      totalCompressions: stats.totalVersions,
      latestCompressionRatio: stats.latestCompressionRatio,
      intentHistory: stats.intentHistory,
      totalTokens: 0, // 由压缩器在下面补充
      pendingBufferSize: stats.pendingBufferSize,
      versions: this.compressor.listVersions(),
    };
  }

  // ------------------------------------------------------------
  // 获取/设置会话名
  // ------------------------------------------------------------

  setName(name: string): void {
    this.name = name;
    this.dirty = true;
  }

  getName(): string {
    return this.name;
  }

  getSessionId(): string {
    return this.sessionId;
  }

  // ------------------------------------------------------------
  // 持久化
  // ------------------------------------------------------------

  async save(): Promise<void> {
    const data = this.buildPersistedData();
    await this.storage.save(this.sessionId, data);
    this.dirty = false;
  }

  async saveToFile(filePath: string): Promise<void> {
    const data = this.buildPersistedData();
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    await fs.promises.writeFile(filePath, JSON.stringify(data, null, 2), 'utf-8');
    this.dirty = false;
  }

  async loadFromFile(filePath: string): Promise<boolean> {
    try {
      const content = await fs.promises.readFile(filePath, 'utf-8');
      const data = JSON.parse(content);
      this.restoreFromData(data);
      return true;
    } catch (e) {
      console.warn(`[graph-session] 加载失败: ${filePath}`, e);
      return false;
    }
  }

  private buildPersistedData(): PersistedSessionData {
    const stats = this.compressor.getStats();
    const exportData = this.compressor.exportSession();
    return {
      sessionId: this.sessionId,
      name: this.name,
      createdAt: this.createdAt,
      lastUpdated: this.lastUpdated,
      messages: exportData.messages.map((m) => ({
        id: m.id,
        role: m.role as CompressMessage['role'],
        content: m.content,
        timestamp: m.timestamp,
      })),
      versions: exportData.versions,
      stats: {
        sessionId: this.sessionId,
        createdAt: this.createdAt,
        lastUpdated: this.lastUpdated,
        totalMessages: stats.totalMessages,
        totalCompressions: stats.totalVersions,
        latestCompressionRatio: stats.latestCompressionRatio,
        intentHistory: stats.intentHistory,
        totalTokens: 0,
      },
      metadata: {
        compressionMode: 'incremental-semantic',
        targetRatio: 0.5,
        version: '1.0.0',
      },
    };
  }

  private restoreFromData(data: PersistedSessionData): void {
    this.sessionId = data.sessionId;
    this.name = data.name;
    this.createdAt = data.createdAt;
    this.lastUpdated = data.lastUpdated;

    // 重新构建压缩器
    this.compressor = new IncrementalCompressor({
      sessionId: data.sessionId,
    });
    this.compressor.importSession(data);
  }

  // ------------------------------------------------------------
  // 自动保存控制
  // ------------------------------------------------------------

  enableAutoSave(): void {
    if (this.autoSaveTimer) return;
    this.autoSaveTimer = setInterval(() => {
      if (this.dirty) {
        this.save().catch((err) => {
          console.warn('[graph-session] 自动保存失败:', err);
        });
      }
    }, this.autoSaveIntervalMs);
  }

  disableAutoSave(): void {
    if (this.autoSaveTimer) {
      clearInterval(this.autoSaveTimer);
      this.autoSaveTimer = null;
    }
  }

  // ------------------------------------------------------------
  // 调试输出
  // ------------------------------------------------------------

  debugPrintSummary(): void {
    const stats = this.getStats();
    const ctx = this.getContextForLLM();
    console.log('='.repeat(60));
    console.log(`📁 会话: ${this.name} (${this.sessionId})`);
    console.log(`   创建时间: ${new Date(this.createdAt).toLocaleString()}`);
    console.log(`   最后更新: ${new Date(this.lastUpdated).toLocaleString()}`);
    console.log(`   消息数: ${stats.totalMessages}`);
    console.log(`   压缩版本: ${stats.totalCompressions}`);
    console.log(`   压缩率: ${(stats.latestCompressionRatio * 100).toFixed(0)}%`);
    console.log(`   LLM 上下文: ${ctx.messages.length} 条消息`);
    console.log('='.repeat(60));
  }
}

// ============================================================
// ==================== 工厂函数 ==============================
// ============================================================

export function createSession(
  sessionId: string,
  options: StorageOptions = {}
): GraphSession {
  return new GraphSession(sessionId, options);
}

export async function loadSession(
  sessionIdOrPath: string,
  options: StorageOptions = {}
): Promise<GraphSession | null> {
  // 1. 如果是文件路径
  if (sessionIdOrPath.endsWith('.json') && typeof fs !== 'undefined') {
    const session = new GraphSession(sessionIdOrPath, options);
    const success = await session.loadFromFile(sessionIdOrPath);
    return success ? session : null;
  }

  // 2. 根据环境创建存储适配器
  const storage: StorageAdapter = (() => {
    if (typeof window !== 'undefined') return new LocalStorageAdapter();
    if (typeof process !== 'undefined') return new FileSystemStorage(options.storageDir);
    return new MemoryStorage();
  })();

  const data = await storage.load(sessionIdOrPath);
  if (!data) return null;

  const session = new GraphSession(sessionIdOrPath, options);
  session['name'] = data.name;
  session['createdAt'] = data.createdAt;
  session['lastUpdated'] = data.lastUpdated;
  if (data.messages && data.messages.length > 0) {
    session.appendMessages(data.messages);
  }
  return session;
}

export async function listSessions(storageDir?: string): Promise<string[]> {
  const storage = (() => {
    if (typeof window !== 'undefined') return new LocalStorageAdapter();
    if (typeof process !== 'undefined') return new FileSystemStorage(storageDir);
    return new MemoryStorage();
  })();
  return storage.list();
}

export async function deleteSession(sessionId: string, storageDir?: string): Promise<boolean> {
  const storage = (() => {
    if (typeof window !== 'undefined') return new LocalStorageAdapter();
    if (typeof process !== 'undefined') return new FileSystemStorage(storageDir);
    return new MemoryStorage();
  })();
  return storage.delete(sessionId);
}

// ============================================================
// ==================== 便捷：对话自动压缩 wrapper ============
// ============================================================

/**
 * 对话级自动压缩 - 适用于：
 *   const dialog = new AutoCompressingDialog({ targetRatio: 0.5 });
 *   dialog.addUserMessage('分析一下 BTC 行情');
 *   dialog.addAssistantMessage('BTC 当前价格 65000 USDT...');
 *   // ...
 *   const context = dialog.getContextForLLM();
 */
export class AutoCompressingDialog {
  private session: GraphSession;
  private compressEveryN: number;
  private messageCount: number;

  constructor(options: {
    sessionId?: string;
    targetRatio?: number;
    compressEveryN?: number;
    highlightKeywords?: string[];
    storageDir?: string;
  } = {}) {
    this.compressEveryN = options.compressEveryN || 10;
    this.messageCount = 0;

    this.session = new GraphSession(
      options.sessionId || `dialog_${Date.now()}`,
      {
        compressionRatio: options.targetRatio || 0.5,
        autoCompressThreshold: 1, // 每条消息都走 buffer 逻辑，由上层控制
        highlightKeywords: options.highlightKeywords || [],
        storageDir: options.storageDir,
      }
    );
  }

  addUserMessage(content: string, importance?: 'high' | 'medium' | 'low'): void {
    this.addMessage({ role: 'user', content, importance });
  }

  addAssistantMessage(content: string, importance?: 'high' | 'medium' | 'low'): void {
    this.addMessage({ role: 'assistant', content, importance });
  }

  addToolResult(content: string, toolName?: string): void {
    this.addMessage({
      role: 'tool_result',
      content,
      toolName,
      importance: 'medium',
    });
  }

  private addMessage(msg: Omit<CompressMessage, 'id' | 'timestamp'>): void {
    this.session.appendMessage({
      id: `msg_${Date.now()}_${this.messageCount}`,
      timestamp: Date.now(),
      ...msg,
    });
    this.messageCount++;

    // 每 N 条消息自动压缩一次
    if (this.messageCount % this.compressEveryN === 0) {
      this.session.compressNow();
    }
  }

  getContextForLLM(): {
    messages: CompressMessage[];
    summary: string;
    compressedNote: string;
  } {
    // 获取上下文前，先确保做一次压缩（如果有缓冲）
    return this.session.getContextForLLM();
  }

  getStats(): SessionStats & { pendingBufferSize: number; versions: CompressionVersion[] } {
    return this.session.getStats();
  }

  async save(): Promise<void> {
    await this.session.save();
  }

  getSessionId(): string {
    return this.session.getSessionId();
  }

  debugSummary(): void {
    this.session.debugPrintSummary();
  }
}

// ============================================================
// ==================== CLI 入口 ==============================
// ============================================================

if (typeof process !== 'undefined' && process.argv && process.argv[1]?.includes('graph-persistence.ts')) {
  console.log('='.repeat(60));
  console.log('💾 Graph Persistence - 持久化演示');
  console.log('='.repeat(60));

  const dialog = new AutoCompressingDialog({
    sessionId: 'demo_trading_dialog',
    targetRatio: 0.5,
    compressEveryN: 5,
    highlightKeywords: ['BTC', '买入', '止损', '策略', '分析', '风险'],
  });

  const messages = [
    { role: 'user' as const, content: '帮我分析 BTC 行情，能买入吗？' },
    { role: 'assistant' as const, content: '好的，让我先获取市场数据...' },
    { role: 'assistant' as const, content: 'BTC 当前价格: 65,200 USDT，RSI: 55，24h 涨幅: +2.3%' },
    { role: 'user' as const, content: '那我的入场点和止损应该设在哪里？' },
    { role: 'assistant' as const, content: '建议：入场 64,800，止损 64,200，第一目标 65,800', importance: 'high' as const },
    { role: 'user' as const, content: '仓位呢？风险收益比如何？' },
    { role: 'assistant' as const, content: '保守仓位：总资金的 3%，风险收益比约 1:1.67', importance: 'high' as const },
    { role: 'user' as const, content: '回测一下这个信号在过去 60 天的表现' },
    { role: 'assistant' as const, content: '回测完成：胜率 58%，平均收益 +1.2%，最大回撤 2.5%' },
    { role: 'user' as const, content: '好的，那就按这个方案执行', importance: 'high' as const },
    { role: 'assistant' as const, content: '✅ 已确认方案，等待 BTC 价格触发入场条件', importance: 'high' as const },
  ];

  messages.forEach((m) => {
    if (m.role === 'user') dialog.addUserMessage(m.content, m.importance);
    else dialog.addAssistantMessage(m.content, m.importance);
  });

  console.log(`\n📝 已添加 ${messages.length} 条消息`);
  console.log(`🔄 每 5 条消息自动压缩一次`);
  console.log();

  dialog.debugSummary();

  console.log('\n--- LLM 上下文（保留的关键消息）---');
  const ctx = dialog.getContextForLLM();
  ctx.messages.forEach((m, i) => {
    const prefix = m.importance === 'high' ? '⭐' : '•';
    const role = m.role.toUpperCase().padEnd(10, ' ');
    console.log(`  ${prefix} [${role}] ${m.content.slice(0, 80)}${m.content.length > 80 ? '...' : ''}`);
  });

  if (ctx.compressedNote) {
    console.log('\n--- 压缩的次要内容（保留引用）---');
    console.log(`  ${ctx.compressedNote}`);
  }

  console.log('\n✅ 持久化演示完成！');
  console.log(`💾 会话已保存，可通过 loadSession('demo_trading_dialog') 恢复`);
}

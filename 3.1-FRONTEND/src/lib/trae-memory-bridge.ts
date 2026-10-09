/**
 * TraeMemoryBridge — Trae Code 记忆桥接
 * ==========================================
 * SPEC-20261009 §1.2 + §10 P0-3
 *
 * 从 Trae Code 的 session_memory_*.jsonl 中提取解题模式四元组，
 * 编码后入库 TDR (Training Data Repository)。
 *
 * 设计原则：
 *   1. Trae 记忆只读：不修改 ~/.trae-cn/memory/ 下任何文件
 *   2. 质量闸门：有 learned 才入库
 *   3. FAIL-OPEN：文件不存在/解析失败 → 跳过，不抛异常
 *   4. 异步入库：不阻塞主链路
 *
 * 位置: 3.1-FRONTEND/src/lib/trae-memory-bridge.ts
 */

import { watch, type FSWatcher } from 'fs';
import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import path from 'path';
import { getCaseBankClient, type StoreInput } from './case-bank-client';
import { getSolutionEncoder } from './solution-encoder';

// ============================================================
// 1. 类型定义
// ============================================================

export interface SessionMemoryEntry {
  intent: string;
  actions: string[];
  outcome: string;
  learned: string[];
  message_summary_time: string;
  message_id: string;
}

export interface ExtractedQuadruple extends StoreInput {}

export interface IngestResult {
  ingested: number;
  skipped: number;
  errors: string[];
}

// ============================================================
// 2. 默认配置
// ============================================================

const DEFAULT_MEMORY_DIR = path.join(
  process.env.HOME || process.env.USERPROFILE || '',
  '.trae-cn',
  'memory',
  'projects',
);

// ============================================================
// 3. TraeMemoryBridge 主类
// ============================================================

export class TraeMemoryBridge {
  readonly readonly: boolean = true;
  private watcher: FSWatcher | null = null;
  private memoryDir: string;
  private caseBankClient: ReturnType<typeof getCaseBankClient>;
  private encoder: ReturnType<typeof getSolutionEncoder>;

  constructor(opts?: { memoryDir?: string }) {
    this.memoryDir = opts?.memoryDir || DEFAULT_MEMORY_DIR;
    this.caseBankClient = getCaseBankClient();
    this.encoder = getSolutionEncoder();
  }

  /**
   * 从 session_memory 条目提取四元组
   * 质量闸门：learned 为空 → 返回 null
   */
  extractQuadruple(entry: SessionMemoryEntry): ExtractedQuadruple | null {
    if (!entry.learned || entry.learned.length === 0) {
      return null; // 质量闸门：有 learned 才入库
    }

    return {
      intent: entry.intent || '',
      actions: entry.actions || [],
      outcome_text: entry.outcome || '',
      learned: entry.learned,
      message_id: entry.message_id || '',
      message_summary_time: entry.message_summary_time || '',
      source: 'trae-session',
    };
  }

  /**
   * 解析单行 JSONL
   * 空行/非法 JSON → 返回 null（不抛异常）
   */
  parseJsonlLine(line: string): SessionMemoryEntry | null {
    const trimmed = line.trim();
    if (!trimmed) return null;
    try {
      const parsed = JSON.parse(trimmed);
      // 基本字段校验
      if (typeof parsed.intent !== 'string') return null;
      if (!Array.isArray(parsed.actions)) return null;
      if (typeof parsed.outcome !== 'string') return null;
      if (!Array.isArray(parsed.learned)) return null;
      return parsed as SessionMemoryEntry;
    } catch {
      return null; // FAIL-OPEN: 非法 JSON 跳过
    }
  }

  /**
   * 解析 JSONL 文件 → 四元组 → TDR 入库
   */
  async ingestFile(filePath: string): Promise<IngestResult> {
    const result: IngestResult = { ingested: 0, skipped: 0, errors: [] };

    let content: string;
    try {
      content = readFileSync(filePath, 'utf-8');
    } catch {
      // 文件不存在 → FAIL-OPEN
      return result;
    }

    const lines = content.split('\n');
    for (const line of lines) {
      const entry = this.parseJsonlLine(line);
      if (!entry) {
        result.skipped++;
        continue;
      }

      const quadruple = this.extractQuadruple(entry);
      if (!quadruple) {
        result.skipped++; // 质量闸门拒绝（learned 为空）
        continue;
      }

      // VQ-VAE 编码
      const encoded = this.encoder.encode({
        intent: quadruple.intent,
        actions: quadruple.actions,
        outcome_text: quadruple.outcome_text,
        learned: quadruple.learned,
      });

      quadruple.codebook_index = encoded.codebook_index;
      quadruple.embedding = encoded.embedding;

      // 入库 TDR
      const storeResult = await this.caseBankClient.store(quadruple);
      if (storeResult.ok) {
        result.ingested++;
      } else {
        result.errors.push(`store_failed: ${storeResult.error || 'unknown'}`);
      }
    }

    return result;
  }

  /**
   * 扫描目录下所有 session_memory_*.jsonl 文件
   */
  async ingestAll(): Promise<IngestResult> {
    const result: IngestResult = { ingested: 0, skipped: 0, errors: [] };

    try {
      const files = this._findJsonlFiles(this.memoryDir);
      for (const file of files) {
        const r = await this.ingestFile(file);
        result.ingested += r.ingested;
        result.skipped += r.skipped;
        result.errors.push(...r.errors);
      }
    } catch {
      // 目录不存在 → FAIL-OPEN
    }

    return result;
  }

  /**
   * 启动文件监听（递归，macOS 原生支持）
   */
  startWatching(dir?: string): void {
    const watchDir = dir || this.memoryDir;
    try {
      if (!existsSync(watchDir)) return; // 路径不存在 → FAIL-OPEN

      this.watcher = watch(watchDir, { recursive: true }, (eventType, filename) => {
        if (!filename) return;
        if (filename.includes('session_memory') && filename.endsWith('.jsonl')) {
          const fullPath = path.join(watchDir, filename);
          this.ingestFile(fullPath).catch(() => { /* FAIL-OPEN */ });
        }
      });
    } catch {
      // 路径不存在或权限不足 → FAIL-OPEN
    }
  }

  /**
   * 停止文件监听
   */
  stopWatching(): void {
    if (this.watcher) {
      this.watcher.close();
      this.watcher = null;
    }
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _findJsonlFiles(dir: string): string[] {
    const results: string[] = [];
    try {
      const entries = readdirSync(dir);
      for (const entry of entries) {
        const fullPath = path.join(dir, entry);
        const stat = statSync(fullPath);
        if (stat.isDirectory()) {
          results.push(...this._findJsonlFiles(fullPath));
        } else if (entry.includes('session_memory') && entry.endsWith('.jsonl')) {
          results.push(fullPath);
        }
      }
    } catch {
      // 目录不存在 → 返回空
    }
    return results;
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: TraeMemoryBridge | null = null;

export function getTraeMemoryBridge(): TraeMemoryBridge {
  if (!_instance) {
    _instance = new TraeMemoryBridge();
  }
  return _instance;
}

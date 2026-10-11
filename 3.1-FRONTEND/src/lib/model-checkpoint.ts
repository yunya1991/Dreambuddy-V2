/**
 * ModelCheckpoint — SPL v0.5 模型状态持久化
 * ==========================================
 * SPEC-v0.5-continual-training §4.5 P1
 *
 * 持久化模型状态 (weights + patterns + step + drift_flag)
 * 用于：
 *   1. 漂移触发训练前快照 → 回滚保障
 *   2. 训练后 checkpoint → 版本管理
 *   3. 系统重启时恢复最近模型
 *
 * 每层独立存储，最多保留 maxCheckpoints 个检查点（FIFO 淘汰最旧）。
 *
 * v0.5.1 更新（2026-10-12）：
 *   - 新增 persistDir 选项，启用 JSON 文件持久化到磁盘
 *   - 解决 Next.js dev 模式热重载导致内存状态丢失的问题
 *   - 启用持久化时，同一 persistDir 的所有实例共享 store（5 层训练循环协同）
 *   - FAIL-OPEN：磁盘操作失败降级为纯内存模式，不阻塞训练流程
 *
 * 位置: 3.1-FRONTEND/src/lib/model-checkpoint.ts
 */

import fs from 'fs';
import path from 'path';

// ============================================================
// 1. 类型定义
// ============================================================

export interface CheckpointMeta {
  id: string;
  layer: string;
  timestamp: number;
  step: number;
  drift_flag: boolean;
}

export interface CheckpointRecord extends CheckpointMeta {
  state: Record<string, unknown>;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_MAX_CHECKPOINTS = 5;
const CHECKPOINT_FILE = 'checkpoints.json';
const PERSIST_VERSION = '1.0';

/**
 * 默认持久化目录：.next/training-checkpoints/
 * 与 notebook 状态文件同目录级别，不污染项目根目录。
 */
// 注意: 不能放在 .next/ 下，因为 next dev 重编译时会清理 .next 目录
export const DEFAULT_PERSIST_DIR = path.join(process.cwd(), '.training-checkpoints');

// ============================================================
// 3. ModelCheckpoint 主类
// ============================================================

export class ModelCheckpoint {
  readonly maxCheckpoints: number;
  private store: Map<string, CheckpointRecord[]>;
  private idCounter = 0;
  private persistDir: string | null;
  private persistFile: string | null;

  // 静态共享 store：同一 persistDir 的所有实例共享，保证 5 层训练循环协同
  // Map<persistDir, Map<layer, CheckpointRecord[]>>
  private static sharedStores: Map<string, Map<string, CheckpointRecord[]>> = new Map();
  // 已从磁盘加载过的目录（避免重复加载）
  private static loadedDirs: Set<string> = new Set();

  constructor(opts?: { maxCheckpoints?: number; persistDir?: string | null }) {
    this.maxCheckpoints = opts?.maxCheckpoints ?? DEFAULT_MAX_CHECKPOINTS;
    this.persistDir = opts?.persistDir ?? null;

    if (this.persistDir) {
      this.persistFile = path.join(this.persistDir, CHECKPOINT_FILE);
      // 同一 persistDir 的实例共享 store
      if (!ModelCheckpoint.sharedStores.has(this.persistDir)) {
        ModelCheckpoint.sharedStores.set(this.persistDir, new Map());
      }
      this.store = ModelCheckpoint.sharedStores.get(this.persistDir)!;
      // 首次加载时从磁盘恢复（模拟服务重启）
      if (!ModelCheckpoint.loadedDirs.has(this.persistDir)) {
        this.loadFromDisk();
        ModelCheckpoint.loadedDirs.add(this.persistDir);
      }
    } else {
      this.persistFile = null;
      // 未启用持久化：实例独立 store（测试隔离）
      this.store = new Map();
    }
  }

  /**
   * 从磁盘加载检查点到内存 store（FAIL-OPEN）
   */
  private loadFromDisk(): void {
    if (!this.persistFile) return;
    try {
      if (!fs.existsSync(this.persistFile)) return;
      const raw = fs.readFileSync(this.persistFile, 'utf-8');
      const parsed = JSON.parse(raw);
      if (parsed.store && typeof parsed.store === 'object') {
        // 合并到共享 store
        for (const [layer, records] of Object.entries(parsed.store as Record<string, CheckpointRecord[]>)) {
          this.store.set(layer, records);
        }
      }
    } catch {
      // FAIL-OPEN: 磁盘损坏或格式错误时不阻塞，使用空 store
    }
  }

  /**
   * 将内存 store 持久化到磁盘（FAIL-OPEN）
   */
  private persistToDisk(): void {
    if (!this.persistDir || !this.persistFile) return;
    try {
      if (!fs.existsSync(this.persistDir)) {
        fs.mkdirSync(this.persistDir, { recursive: true });
      }
      const data = {
        version: PERSIST_VERSION,
        updatedAt: new Date().toISOString(),
        store: Object.fromEntries(this.store),
      };
      // 原子写入：先写临时文件再重命名，避免崩溃导致文件损坏
      const tmpFile = `${this.persistFile}.tmp`;
      fs.writeFileSync(tmpFile, JSON.stringify(data, null, 2), 'utf-8');
      fs.renameSync(tmpFile, this.persistFile);
    } catch {
      // FAIL-OPEN: 写入失败不阻塞，保留内存数据
    }
  }

  /**
   * 生成唯一检查点 ID
   */
  private generateId(): string {
    this.idCounter++;
    return `ckpt-${Date.now()}-${this.idCounter}`;
  }

  /**
   * 保存模型状态检查点
   * 超过 maxCheckpoints 时淘汰最旧
   * 启用持久化时同步写入磁盘
   *
   * state 用 Record<string, any> 以兼容各层 ModelState 接口
   * （SModelState/DSHModelState 等无索引签名，不能直接赋值给 Record<string, unknown>）
   */
  checkpoint(layer: string, state: Record<string, any>): CheckpointMeta {
    const records = this.store.get(layer) ?? [];

    const record: CheckpointRecord = {
      id: this.generateId(),
      layer,
      timestamp: Date.now(),
      step: (state.step as number) ?? 0,
      drift_flag: (state.drift_flag as boolean) ?? false,
      state,
    };

    records.push(record);

    // FIFO 淘汰最旧
    while (records.length > this.maxCheckpoints) {
      records.shift();
    }

    this.store.set(layer, records);

    // 持久化到磁盘（FAIL-OPEN）
    this.persistToDisk();

    // 返回元数据（不含 state）
    const { state: _, ...meta } = record;
    return meta;
  }

  /**
   * 恢复模型状态
   * 不指定 checkpointId 时恢复最新
   */
  restore(layer: string, checkpointId?: string): CheckpointRecord | null {
    const records = this.store.get(layer);
    if (!records || records.length === 0) return null;

    if (checkpointId) {
      return records.find(r => r.id === checkpointId) ?? null;
    }

    // 返回最新（数组末尾）
    return records[records.length - 1];
  }

  /**
   * 列出指定层的所有检查点（按时间降序，最新在前）
   */
  listCheckpoints(layer: string): CheckpointMeta[] {
    const records = this.store.get(layer);
    if (!records || records.length === 0) return [];

    // 降序：最新在前（records 按时间顺序插入，末尾是最新）
    return [...records]
      .map(({ state: _, ...meta }) => meta)
      .reverse();
  }

  /**
   * 清空指定层的所有检查点
   * 启用持久化时同步更新磁盘
   */
  clear(layer: string): void {
    this.store.delete(layer);
    // 持久化到磁盘（FAIL-OPEN）
    this.persistToDisk();
  }
}

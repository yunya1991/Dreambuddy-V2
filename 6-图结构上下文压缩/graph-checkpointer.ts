/**
 * ============================================================
 * ⏱️  图执行检查点管理器 (Graph Checkpointer)
 * ============================================================
 *
 * 位置: 6-图结构上下文压缩/graph-checkpointer.ts
 *
 * Phase 1 核心模块：为 A 层执行提供断点持久化能力
 *
 * 功能：
 * 1. 每个节点执行后自动保存 checkpoint
 * 2. 支持回滚到任意节点重新执行
 * 3. 支持列出所有历史检查点
 *
 * 存储格式兼容现有 GraphSession 体系
 */

import * as fs from 'fs';
import * as path from 'path';

import type {
  SerializedGraphState,
  GraphStateSnapshot,
} from './graph-state';
import type { NodeId, ArchitectureGraph, BlueprintGraph } from './models';

// ============================================================
// 存储格式
// ============================================================

export interface CheckpointStore {
  /** 检查点 ID */
  id: string;

  /** 执行 ID（关联到某次执行） */
  executionId: string;

  /** 检查点列表 */
  checkpoints: CheckpointRecord[];

  /** 创建时间 */
  createdAt: number;

  /** 最后更新时间 */
  lastUpdated: number;
}

export interface CheckpointRecord {
  /** 快照 ID */
  snapshotId: string;

  /** 对应的节点 ID */
  nodeId: NodeId;

  /** 快照时间 */
  timestamp: number;

  /** 节点名称 */
  nodeName: string;

  /** Token 消耗 */
  tokenUsed: number;

  /** 置信度 */
  confidence: number;

  /** 状态数据 */
  state: SerializedGraphState;
}

// ============================================================
// 存储配置
// ============================================================

export interface CheckpointStorageConfig {
  /** 存储目录 */
  storageDir?: string;

  /** 是否自动保存 */
  autoSave?: boolean;

  /** 最大保存点数（超出则删除最旧的） */
  maxCheckpoints?: number;
}

// ============================================================
// 检查点管理器
// ============================================================

export class GraphCheckpointer {
  private config: CheckpointStorageConfig;
  private executionId: string;
  private store: CheckpointStore;
  private architecture: ArchitectureGraph;
  private blueprint: BlueprintGraph;
  private filePath: string;

  constructor(
    executionId: string,
    architecture: ArchitectureGraph,
    blueprint: BlueprintGraph,
    config?: CheckpointStorageConfig
  ) {
    this.executionId = executionId;
    this.architecture = architecture;
    this.blueprint = blueprint;
    this.config = {
      storageDir: path.join(process.cwd(), 'graph-checkpoints'),
      autoSave: true,
      maxCheckpoints: 50,
      ...config,
    };

    // 初始化存储
    this.ensureStorageDir();

    // 尝试加载已有数据
    this.filePath = path.join(this.config.storageDir!, `${executionId}.json`);
    this.store = this.loadOrCreateStore();
  }

  /**
   * 确保存储目录存在
   */
  private ensureStorageDir(): void {
    if (!fs.existsSync(this.config.storageDir)) {
      fs.mkdirSync(this.config.storageDir!, { recursive: true });
    }
  }

  /**
   * 加载或创建存储
   */
  private loadOrCreateStore(): CheckpointStore {
    if (fs.existsSync(this.filePath)) {
      try {
        const data = fs.readFileSync(this.filePath, 'utf-8');
        return JSON.parse(data) as CheckpointStore;
      } catch {
        // 文件损坏，返回新的
      }
    }

    return {
      id: `store_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      executionId: this.executionId,
      checkpoints: [],
      createdAt: Date.now(),
      lastUpdated: Date.now(),
    };
  }

  /**
   * 保存检查点
   */
  saveCheckpoint(snapshot: GraphStateSnapshot): void {
    const node = this.architecture.nodes.get(snapshot.nodeId);

    const record: CheckpointRecord = {
      snapshotId: snapshot.id,
      nodeId: snapshot.nodeId,
      timestamp: snapshot.timestamp,
      nodeName: node?.name ?? snapshot.nodeId,
      tokenUsed: snapshot.state.tokenUsed,
      confidence: snapshot.state.confidence,
      state: snapshot.state,
    };

    this.store.checkpoints.push(record);
    this.store.lastUpdated = Date.now();

    // 清理旧检查点
    if (
      this.config.maxCheckpoints &&
      this.store.checkpoints.length > this.config.maxCheckpoints
    ) {
      this.store.checkpoints = this.store.checkpoints.slice(
        -this.config.maxCheckpoints
      );
    }

    if (this.config.autoSave) {
      this.persist();
    }
  }

  /**
   * 持久化到磁盘
   */
  persist(): void {
    fs.writeFileSync(this.filePath, JSON.stringify(this.store, null, 2));
  }

  /**
   * 回滚到指定节点
   *
   * 语义：回到该节点执行完成后的状态
   * - 如果该节点有保存的快照，返回该节点最新的快照
   * - 否则返回该节点之前最新的快照
   */
  revertToNode(nodeId: NodeId): SerializedGraphState | null {
    // 先检查该节点自己是否有检查点
    const selfCheckpoint = this.getLatestCheckpointForNode(nodeId);
    if (selfCheckpoint) {
      return selfCheckpoint.state;
    }

    // 没有的话，找该节点之前最新的检查点
    const checkpoint = this.findLatestCheckpointBeforeNode(nodeId);
    if (!checkpoint) {
      return null;
    }
    return checkpoint.state;
  }

  /**
   * 找到指定节点之前的最新检查点
   */
  private findLatestCheckpointBeforeNode(nodeId: NodeId): CheckpointRecord | null {
    const nodeIds = Array.from(this.architecture.nodes.keys());
    const targetIndex = nodeIds.indexOf(nodeId);

    if (targetIndex <= 0) {
      return null;
    }

    // 获取该节点之前的所有检查点
    const validNodeIds = nodeIds.slice(0, targetIndex);
    const checkpointsBefore = this.store.checkpoints.filter((cp) =>
      validNodeIds.includes(cp.nodeId)
    );

    if (checkpointsBefore.length === 0) {
      return null;
    }

    // 返回最新的
    return checkpointsBefore[checkpointsBefore.length - 1];
  }

  /**
   * 获取最新检查点
   */
  getLatestCheckpoint(): CheckpointRecord | null {
    if (this.store.checkpoints.length === 0) {
      return null;
    }
    return this.store.checkpoints[this.store.checkpoints.length - 1];
  }

  /**
   * 获取指定节点的最新检查点
   */
  getLatestCheckpointForNode(nodeId: NodeId): CheckpointRecord | null {
    const checkpoints = this.store.checkpoints.filter(
      (cp) => cp.nodeId === nodeId
    );
    if (checkpoints.length === 0) {
      return null;
    }
    return checkpoints[checkpoints.length - 1];
  }

  /**
   * 获取所有检查点
   */
  listCheckpoints(): CheckpointRecord[] {
    return [...this.store.checkpoints];
  }

  /**
   * 获取指定节点之后的检查点（用于重跑）
   */
  getCheckpointsAfterNode(nodeId: NodeId): CheckpointRecord[] {
    const nodeIds = Array.from(this.architecture.nodes.keys());
    const targetIndex = nodeIds.indexOf(nodeId);

    if (targetIndex < 0) {
      return [];
    }

    const nodesAfter = new Set(nodeIds.slice(targetIndex + 1));

    return this.store.checkpoints.filter((cp) => nodesAfter.has(cp.nodeId));
  }

  /**
   * 清除指定节点之后的所有检查点
   */
  clearCheckpointsAfterNode(nodeId: NodeId): void {
    const nodeIds = Array.from(this.architecture.nodes.keys());
    const targetIndex = nodeIds.indexOf(nodeId);

    if (targetIndex < 0) {
      return;
    }

    const nodesToRemove = new Set(nodeIds.slice(targetIndex + 1));

    this.store.checkpoints = this.store.checkpoints.filter(
      (cp) => !nodesToRemove.has(cp.nodeId)
    );
    this.store.lastUpdated = Date.now();

    if (this.config.autoSave) {
      this.persist();
    }
  }

  /**
   * 获取检查点总数
   */
  getCheckpointCount(): number {
    return this.store.checkpoints.length;
  }

  /**
   * 获取执行摘要
   */
  getExecutionSummary(): {
    executionId: string;
    totalCheckpoints: number;
    firstCheckpoint: number;
    lastCheckpoint: number;
    latestConfidence: number;
    latestTokenUsed: number;
  } {
    const latest = this.getLatestCheckpoint();

    return {
      executionId: this.executionId,
      totalCheckpoints: this.store.checkpoints.length,
      firstCheckpoint: this.store.checkpoints[0]?.timestamp ?? 0,
      lastCheckpoint: this.store.checkpoints[this.store.checkpoints.length - 1]?.timestamp ?? 0,
      latestConfidence: latest?.confidence ?? 0,
      latestTokenUsed: latest?.tokenUsed ?? 0,
    };
  }

  /**
   * 删除检查点存储
   */
  delete(): void {
    if (fs.existsSync(this.filePath)) {
      fs.unlinkSync(this.filePath);
    }
  }

  /**
   * 获取当前存储的文件路径
   */
  getFilePath(): string {
    return this.filePath;
  }

  /**
   * 获取节点执行顺序
   */
  getExecutionOrder(): NodeId[] {
    return Array.from(this.architecture.nodes.keys());
  }
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建检查点管理器
 */
export function createCheckpointer(
  executionId: string,
  architecture: ArchitectureGraph,
  blueprint: BlueprintGraph,
  config?: CheckpointStorageConfig
): GraphCheckpointer {
  return new GraphCheckpointer(executionId, architecture, blueprint, config);
}

/**
 * 列出所有检查点文件
 */
export function listCheckpointFiles(storageDir?: string): string[] {
  const dir = storageDir || path.join(process.cwd(), 'graph-checkpoints');

  if (!fs.existsSync(dir)) {
    return [];
  }

  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => path.join(dir, f));
}

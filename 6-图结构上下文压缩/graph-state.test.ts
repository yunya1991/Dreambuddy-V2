#!/usr/bin/env npx tsx
/**
 * Graph State + Checkpoint 单元测试
 *
 * 验证内容：
 * 1. GraphStateManager 基础功能
 * 2. Checkpoint 保存与恢复
 * 3. 节点状态流转
 * 4. Token 预算控制
 */

import * as fs from 'fs';
import * as path from 'path';

import {
  GraphStateManager,
  createSnapshot,
  deserializeNodeResults,
  canContinue,
  type GraphState,
  type SerializedGraphState,
} from './graph-state';
import {
  GraphCheckpointer,
  createCheckpointer,
} from './graph-checkpointer';
import type {
  ArchitectureGraph,
  BlueprintGraph,
  ANode,
  BNode,
} from './models';

// ============================================================
// 测试工具
// ============================================================

function cleanupAllTestStorages() {
  // 清理所有测试相关的存储目录
  for (let i = 1; i <= 10; i++) {
    const dir = `/tmp/graph-checkpoints-test${i === 1 ? '' : i}`;
    if (fs.existsSync(dir)) {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }
}

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (error) {
    console.log(`❌ ${name}`);
    console.log(`   错误: ${error instanceof Error ? error.message : String(error)}`);
    failed++;
  }
}

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

function assertEqual(actual: any, expected: any, message: string) {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

// ============================================================
// 测试数据构建
// ============================================================

function createTestArchitecture(): ArchitectureGraph {
  const nodes = new Map<string, ANode>();

  const steps: ANode[] = [
    { id: 'S1', type: 'step', name: 'S1 调研', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } },
    { id: 'S2', type: 'step', name: 'S2 分析', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S1'] },
    { id: 'S3', type: 'step', name: 'S3 设计', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S2'] },
  ];

  steps.forEach((s) => nodes.set(s.id, s));

  return {
    id: 'arch_test',
    blueprintId: 'bp_test',
    nodes,
    edges: [],
    entryPoint: 'S1',
    createdAt: Date.now(),
  };
}

function createTestBlueprint(): BlueprintGraph {
  const nodes = new Map<string, BNode>();

  nodes.set('root', {
    id: 'root',
    type: 'module',
    name: '测试流程',
    description: '测试用流程',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
    children: ['S1', 'S2', 'S3'],
  });

  return {
    id: 'bp_test',
    name: '测试蓝图',
    version: '1.0.0',
    nodes,
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };
}

// ============================================================
// 测试组 1: GraphStateManager 基础
// ============================================================

console.log('\n🧪 测试组 1: GraphStateManager 基础功能');
console.log('=' .repeat(50));

test('创建 StateManager 并获取初始状态', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  const state = manager.getState();
  assert(state.currentNodeId === 'S1', '初始节点应该是 S1');
  assert(state.tokenUsed === 0, '初始 Token 消耗应该是 0');
  assert(state.confidence === 0, '初始置信度应该是 0');
});

test('记录节点开始执行', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  const result = manager.getNodeResult('S1');

  assert(result !== undefined, '应该有 S1 的结果');
  assert(result!.status === 'running', '状态应该是 running');
  assert(result!.startedAt > 0, '应该有开始时间');
});

test('记录节点执行完成', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', {
    tokenCost: 100,
    latencyMs: 500,
    confidence: 0.8,
    outputs: { result: 'test_output' },
  });

  const result = manager.getNodeResult('S1');
  assert(result!.status === 'completed', '状态应该是 completed');
  assert(result!.tokenCost === 100, 'Token 消耗应该是 100');
  assert(result!.confidence === 0.8, '置信度应该是 0.8');
});

test('推进到下一个节点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', {
    tokenCost: 100,
    latencyMs: 500,
    confidence: 0.8,
    outputs: {},
  });
  manager.advanceTo('S2');

  const state = manager.getState();
  assert(state.currentNodeId === 'S2', '当前节点应该是 S2');
});

test('获取下一个可执行节点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  // S1 没有依赖，应该可以直接执行
  const next = manager.getNextExecutableNodes();
  assert(next.includes('S1'), 'S1 应该是可执行的');

  // S1 完成后，S2 应该是可执行的
  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  manager.advanceTo('S2');

  const nextAfter = manager.getNextExecutableNodes();
  assert(nextAfter.includes('S2'), 'S2 应该是可执行的');
});

test('检查所有节点是否完成', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  assert(!manager.isComplete(), '初始状态不应该已完成');

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  manager.advanceTo('S2');

  assert(!manager.isComplete(), 'S1 完成后不应该已完全');

  manager.recordNodeStart('S2');
  manager.recordNodeComplete('S2', { tokenCost: 200, latencyMs: 600, confidence: 0.85, outputs: {} });
  manager.advanceTo('S3');

  manager.recordNodeStart('S3');
  manager.recordNodeComplete('S3', { tokenCost: 150, latencyMs: 400, confidence: 0.9, outputs: {} });

  assert(manager.isComplete(), '所有节点完成后应该已完全');
});

test('获取执行摘要', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });

  const summary = manager.getExecutionSummary();
  assert(summary.totalNodes === 3, '总节点数应该是 3');
  assert(summary.completedNodes === 1, '已完成节点数应该是 1');
  assert(summary.tokenUsed === 100, 'Token 消耗应该是 100');
  assert(summary.totalLatencyMs === 500, '总延迟应该是 500');
});

// ============================================================
// 测试组 2: 序列化与恢复
// ============================================================

console.log('\n🧪 测试组 2: 序列化与恢复');
console.log('=' .repeat(50));

test('创建快照并从快照恢复', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });

  // 创建快照
  const snapshot = manager.createSnapshot('S1');

  assert(snapshot.id.startsWith('snap_'), '快照 ID 应该以 snap_ 开头');
  assert(snapshot.nodeId === 'S1', '快照节点应该是 S1');
  assert(snapshot.state.tokenUsed === 100, '快照中的 Token 消耗应该是 100');

  // 修改当前状态
  manager.advanceTo('S2');
  manager.recordNodeStart('S2');

  // 从快照恢复
  manager.restoreFromSnapshot(snapshot.state);

  const state = manager.getState();
  assert(state.currentNodeId === 'S1', '恢复后当前节点应该是 S1');
  assert(state.tokenUsed === 100, '恢复后 Token 消耗应该是 100');
});

test('序列化状态', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });

  const serialized = manager.getSerializedState();
  assert(Array.isArray(serialized.nodeResults), 'nodeResults 应该被序列化为数组');
  assert(serialized.currentNodeId === 'S1', 'currentNodeId 应该正确序列化');
});

test('从序列化的 CheckpointRecord 恢复', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });

  const serialized = manager.getSerializedState();

  // 模拟 JSON 序列化/反序列化
  const jsonStr = JSON.stringify(serialized);
  const parsed = JSON.parse(jsonStr) as SerializedGraphState;

  // 恢复
  manager.restoreFromSnapshot(parsed);

  const state = manager.getState();
  assert(state.currentNodeId === 'S1', '恢复后当前节点应该是 S1');
  assert(state.tokenUsed === 100, '恢复后 Token 消耗应该是 100');
});

// ============================================================
// 测试组 3: GraphCheckpointer
// ============================================================

// 每个 Checkpointer 测试前清理所有旧数据
cleanupAllTestStorages();

console.log('\n🧪 测试组 3: GraphCheckpointer');
console.log('=' .repeat(50));

test('创建 Checkpointer 并保存检查点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const checkpointer = createCheckpointer('exec_test', arch, bp, {
    storageDir: '/tmp/graph-checkpoints-test',
    autoSave: true,
  });

  const stateManager = new GraphStateManager({ architecture: arch, blueprint: bp });
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });

  const snapshot = stateManager.createSnapshot('S1');
  checkpointer.saveCheckpoint(snapshot);

  assert(checkpointer.getCheckpointCount() === 1, '应该有 1 个检查点');
});

test('获取最新检查点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const checkpointer = createCheckpointer('exec_test2', arch, bp, {
    storageDir: '/tmp/graph-checkpoints-test2',
    autoSave: true,
  });

  const stateManager = new GraphStateManager({ architecture: arch, blueprint: bp });

  // S1 完成
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S1'));

  // S2 完成
  stateManager.advanceTo('S2');
  stateManager.recordNodeStart('S2');
  stateManager.recordNodeComplete('S2', { tokenCost: 200, latencyMs: 600, confidence: 0.85, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S2'));

  const latest = checkpointer.getLatestCheckpoint();
  assert(latest !== null, '应该有最新检查点');
  assert(latest!.nodeId === 'S2', '最新检查点应该是 S2');
  assert(latest!.tokenUsed === 300, 'Token 消耗应该是 300（S1+S2）');
});

test('回滚到指定节点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const checkpointer = createCheckpointer('exec_test3', arch, bp, {
    storageDir: '/tmp/graph-checkpoints-test3',
    autoSave: true,
  });

  const stateManager = new GraphStateManager({ architecture: arch, blueprint: bp });

  // S1 完成
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S1'));

  // S2 完成
  stateManager.advanceTo('S2');
  stateManager.recordNodeStart('S2');
  stateManager.recordNodeComplete('S2', { tokenCost: 200, latencyMs: 600, confidence: 0.85, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S2'));

  // 回滚到 S1
  const restoredState = checkpointer.revertToNode('S1');
  assert(restoredState !== null, '应该能回滚到 S1');
  assert(restoredState!.currentNodeId === 'S1', '回滚后当前节点应该是 S1');
  assert(restoredState!.tokenUsed === 100, '回滚后 Token 消耗应该是 100');
});

test('清除指定节点之后的检查点', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const checkpointer = createCheckpointer('exec_test4', arch, bp, {
    storageDir: '/tmp/graph-checkpoints-test4',
    autoSave: true,
  });

  const stateManager = new GraphStateManager({ architecture: arch, blueprint: bp });

  // S1 完成
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S1'));

  // S2 完成
  stateManager.advanceTo('S2');
  stateManager.recordNodeStart('S2');
  stateManager.recordNodeComplete('S2', { tokenCost: 200, latencyMs: 600, confidence: 0.85, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S2'));

  // 清除 S2 之后的检查点（S2 之后没有节点了，所以清除的是空的）
  checkpointer.clearCheckpointsAfterNode('S2');

  // 清除 S1 之后的检查点（会清除 S2）
  checkpointer.clearCheckpointsAfterNode('S1');

  assert(checkpointer.getCheckpointCount() === 1, '清除后应该有 1 个检查点');
});

test('获取执行摘要', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const checkpointer = createCheckpointer('exec_test5', arch, bp, {
    storageDir: '/tmp/graph-checkpoints-test5',
    autoSave: true,
  });

  const stateManager = new GraphStateManager({ architecture: arch, blueprint: bp });
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', { tokenCost: 100, latencyMs: 500, confidence: 0.8, outputs: {} });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S1'));

  const summary = checkpointer.getExecutionSummary();
  assert(summary.totalCheckpoints === 1, '检查点总数应该是 1');
  assert(summary.latestConfidence === 0.8, '最新置信度应该是 0.8');
  assert(summary.latestTokenUsed === 100, '最新 Token 消耗应该是 100');
});

// ============================================================
// 测试组 4: Token 预算控制
// ============================================================

console.log('\n🧪 测试组 4: Token 预算控制');
console.log('=' .repeat(50));

test('Token 超预算检查', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({
    architecture: arch,
    blueprint: bp,
    maxTokenBudget: 200,
  });

  assert(!manager.isOverBudget(), '初始不应该超预算');

  manager.recordNodeStart('S1');
  manager.recordNodeComplete('S1', { tokenCost: 150, latencyMs: 500, confidence: 0.8, outputs: {} });

  assert(!manager.isOverBudget(), '150 Token 不应该超预算');

  manager.advanceTo('S2');
  manager.recordNodeStart('S2');
  manager.recordNodeComplete('S2', { tokenCost: 100, latencyMs: 600, confidence: 0.85, outputs: {} });

  assert(manager.isOverBudget(), '250 Token 应该超预算');
});

// ============================================================
// 测试组 5: HITL 开关
// ============================================================

console.log('\n🧪 测试组 5: HITL 开关');
console.log('=' .repeat(50));

test('HITL 默认关闭', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  assert(!manager.getState().metadata.hitlEnabled, 'HITL 应该默认关闭');
});

test('启用/禁用 HITL', () => {
  const arch = createTestArchitecture();
  const bp = createTestBlueprint();
  const manager = new GraphStateManager({ architecture: arch, blueprint: bp });

  manager.setHitlEnabled(true);
  assert(manager.getState().metadata.hitlEnabled, 'HITL 应该已启用');

  manager.setHitlEnabled(false);
  assert(!manager.getState().metadata.hitlEnabled, 'HITL 应该已禁用');
});

// ============================================================
// 测试结果汇总
// ============================================================

console.log('\n' + '=' .repeat(50));
console.log(`📊 测试结果: ${passed} 通过, ${failed} 失败`);
console.log('=' .repeat(50));

process.exit(failed > 0 ? 1 : 0);

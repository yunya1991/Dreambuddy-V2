#!/usr/bin/env npx tsx
/**
 * Phase 1 集成验证测试
 *
 * 模拟场景：S1 → S2 → S3 多步骤执行流程
 * - S1 完成，保存检查点
 * - S2 完成，保存检查点
 * - 模拟中断，恢复到 S2
 * - 验证状态正确回滚
 */

import * as fs from 'fs';
import * as path from 'path';

import { GraphStateManager } from './graph-state';
import { GraphCheckpointer } from './graph-checkpointer';
import type { ArchitectureGraph, BlueprintGraph, ANode, BNode } from './models';

// ============================================================
// 测试工具
// ============================================================

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

// ============================================================
// 测试数据
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
    id: 'arch_integration',
    blueprintId: 'bp_integration',
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
    name: '集成测试流程',
    description: '集成测试用流程',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
    children: ['S1', 'S2', 'S3'],
  });

  return {
    id: 'bp_integration',
    name: '集成测试蓝图',
    version: '1.0.0',
    nodes,
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };
}

// ============================================================
// 清理函数
// ============================================================

function cleanupIntegrationTest() {
  const dir = '/tmp/graph-integration-test';
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

// ============================================================
// 集成测试
// ============================================================

console.log('\n🚀 Phase 1 集成验证测试');
console.log('=' .repeat(50));

cleanupIntegrationTest();

// 创建共享的架构和蓝图
const arch = createTestArchitecture();
const bp = createTestBlueprint();
const executionId = `integration_${Date.now()}`;

// 创建 StateManager 和 Checkpointer
const stateManager = new GraphStateManager({
  architecture: arch,
  blueprint: bp,
});

const checkpointer = new GraphCheckpointer(executionId, arch, bp, {
  storageDir: '/tmp/graph-integration-test',
  autoSave: true,
});

console.log('\n📋 测试场景：S1 → S2 → S3 执行流程，中断后恢复到 S2\n');

test('Step 1: 执行 S1 并保存检查点', () => {
  stateManager.recordNodeStart('S1');
  stateManager.recordNodeComplete('S1', {
    tokenCost: 100,
    latencyMs: 500,
    confidence: 0.8,
    outputSummary: 'S1 调研完成',
    outputs: { data: 'S1_result' },
  });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S1'));

  const summary = stateManager.getExecutionSummary();
  assert(summary.completedNodes === 1, '已完成节点应为 1');
  assert(stateManager.getState().currentNodeId === 'S1', '当前节点应为 S1');
  console.log(`   S1 完成，Token: ${summary.tokenUsed}, 置信度: ${stateManager.getState().confidence}`);
});

test('Step 2: 执行 S2 并保存检查点', () => {
  stateManager.advanceTo('S2');
  stateManager.recordNodeStart('S2');
  stateManager.recordNodeComplete('S2', {
    tokenCost: 200,
    latencyMs: 600,
    confidence: 0.85,
    outputSummary: 'S2 分析完成',
    outputs: { data: 'S2_result' },
  });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S2'));

  const summary = stateManager.getExecutionSummary();
  assert(summary.completedNodes === 2, '已完成节点应为 2');
  assert(stateManager.getState().currentNodeId === 'S2', '当前节点应为 S2');
  console.log(`   S2 完成，Token: ${summary.tokenUsed}, 置信度: ${stateManager.getState().confidence}`);
});

test('Step 3: 执行 S3 并保存检查点', () => {
  stateManager.advanceTo('S3');
  stateManager.recordNodeStart('S3');
  stateManager.recordNodeComplete('S3', {
    tokenCost: 150,
    latencyMs: 400,
    confidence: 0.9,
    outputSummary: 'S3 设计完成',
    outputs: { data: 'S3_result' },
  });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S3'));

  const summary = stateManager.getExecutionSummary();
  assert(summary.completedNodes === 3, '已完成节点应为 3');
  assert(stateManager.getState().currentNodeId === 'S3', '当前节点应为 S3');
  console.log(`   S3 完成，Token: ${summary.tokenUsed}, 置信度: ${stateManager.getState().confidence}`);
});

test('Step 4: 检查点总数验证', () => {
  const count = checkpointer.getCheckpointCount();
  assert(count === 3, `检查点总数应为 3，实际为 ${count}`);
  console.log(`   检查点数: ${count}`);
});

test('Step 5: 恢复到 S2 状态', () => {
  // 恢复到 S2 完成后状态
  const restoredState = checkpointer.revertToNode('S2');
  assert(restoredState !== null, '应该能恢复到 S2');

  // 从快照恢复
  stateManager.restoreFromSnapshot(restoredState);

  const state = stateManager.getState();
  assert(state.currentNodeId === 'S2', `恢复后当前节点应为 S2，实际为 ${state.currentNodeId}`);
  assert(state.tokenUsed === 300, `恢复后 Token 应为 300，实际为 ${state.tokenUsed}`);
  assert(state.confidence === 0.85, `恢复后置信度应为 0.85，实际为 ${state.confidence}`);

  const summary = stateManager.getExecutionSummary();
  assert(summary.completedNodes === 2, `恢复后已完成节点应为 2，实际为 ${summary.completedNodes}`);

  console.log(`   已恢复到 S2 状态`);
  console.log(`   当前节点: ${state.currentNodeId}`);
  console.log(`   Token: ${state.tokenUsed}`);
  console.log(`   置信度: ${state.confidence}`);
});

test('Step 6: 清除 S2 之后的检查点', () => {
  checkpointer.clearCheckpointsAfterNode('S2');

  const count = checkpointer.getCheckpointCount();
  assert(count === 2, `清除后检查点应为 2，实际为 ${count}`);
  console.log(`   清除后检查点数: ${count}`);
});

test('Step 7: 继续执行（从 S3 重新开始）', () => {
  // 从 S2 状态继续执行 S3
  stateManager.advanceTo('S3');
  stateManager.recordNodeStart('S3');
  stateManager.recordNodeComplete('S3', {
    tokenCost: 150,
    latencyMs: 400,
    confidence: 0.9,
    outputSummary: 'S3 重新执行完成',
    outputs: { data: 'S3_result_v2' },
  });
  checkpointer.saveCheckpoint(stateManager.createSnapshot('S3'));

  const summary = stateManager.getExecutionSummary();
  assert(summary.completedNodes === 3, '重新执行后已完成节点应为 3');
  assert(summary.tokenUsed === 450, '重新执行后 Token 应为 450（S1:100 + S2:200 + S3:150）');

  // 验证 S3 结果是新版本
  const s3Result = stateManager.getNodeResult('S3');
  assert(s3Result?.outputSummary === 'S3 重新执行完成', 'S3 结果应该是新版本');

  console.log(`   S3 重新执行完成`);
  console.log(`   Token 总计: ${summary.tokenUsed}`);
  console.log(`   最终置信度: ${summary.confidence}`);
});

test('Step 8: 验证最终状态完整性', () => {
  const summary = stateManager.getExecutionSummary();

  assert(summary.totalNodes === 3, '总节点数应为 3');
  assert(summary.completedNodes === 3, '已完成节点应为 3');
  assert(summary.failedNodes === 0, '失败节点应为 0');
  assert(summary.tokenUsed === 450, 'Token 总计应为 450');
  assert(summary.finalConfidence === 0.9, '最终置信度应为 0.9');
  assert(stateManager.isComplete(), '流程应该已完成');

  console.log(`   最终状态验证通过`);
  console.log(`   总节点: ${summary.totalNodes}`);
  console.log(`   已完成: ${summary.completedNodes}`);
  console.log(`   Token: ${summary.tokenUsed}`);
  console.log(`   置信度: ${summary.finalConfidence}`);
});

test('Step 9: 获取执行历史', () => {
  const checkpoints = checkpointer.listCheckpoints();
  assert(checkpoints.length === 3, '检查点历史应有 3 条');

  // 验证检查点顺序
  assert(checkpoints[0].nodeId === 'S1', '第 1 个检查点应为 S1');
  assert(checkpoints[1].nodeId === 'S2', '第 2 个检查点应为 S2');
  assert(checkpoints[2].nodeId === 'S3', '第 3 个检查点应为 S3');

  console.log(`   检查点历史:`);
  checkpoints.forEach((cp, i) => {
    console.log(`     ${i + 1}. ${cp.nodeName} - Token: ${cp.tokenUsed}, 置信度: ${cp.confidence}`);
  });
});

// ============================================================
// 测试结果
// ============================================================

console.log('\n' + '=' .repeat(50));
console.log(`📊 Phase 1 集成验证结果: ${passed} 通过, ${failed} 失败`);
console.log('=' .repeat(50));

// 清理
cleanupIntegrationTest();

process.exit(failed > 0 ? 1 : 0);

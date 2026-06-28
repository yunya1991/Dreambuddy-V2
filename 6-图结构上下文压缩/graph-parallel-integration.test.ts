#!/usr/bin/env npx tsx
/**
 * Phase 3 集成验证测试 - 多链并行分析
 *
 * 场景：S1(调研) → [C1, F1, F2] 并行分析 → S2(综合) → S3(输出)
 *
 * 验证：
 * 1. 并行组正确识别和执行
 * 2. 依赖关系正确处理
 * 3. 结果正确汇总
 * 4. Checkpoint 正确记录
 */

import * as fs from 'fs';
import { ParallelGraphExecutor } from './graph-parallel-executor';
import { createParallelNode } from './graph-parallel';
import type { ArchitectureGraph, BlueprintGraph, ANode, BNode } from './models';

// ============================================================
// 测试工具
// ============================================================

let passed = 0;
let failed = 0;
let totalTests = 0;

function test(name: string, fn: () => Promise<void> | void) {
  totalTests++;
  Promise.resolve()
    .then(() => fn())
    .then(() => {
      console.log(`✅ ${name}`);
      passed++;
    })
    .catch((error) => {
      console.log(`❌ ${name}`);
      console.log(`   错误: ${error instanceof Error ? error.message : String(error)}`);
      failed++;
    })
    .then(() => {
      if (passed + failed === totalTests) {
        printResults();
      }
    });
}

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

function printResults() {
  console.log('\n' + '='.repeat(50));
  console.log(`📊 Phase 3 集成验证结果: ${passed} 通过, ${failed} 失败`);
  console.log('='.repeat(50));
  process.exit(failed > 0 ? 1 : 0);
}

// ============================================================
// 测试数据
// ============================================================

const TEST_STORAGE = '/tmp/graph-parallel-integration-test';

function cleanup() {
  if (fs.existsSync(TEST_STORAGE)) {
    fs.rmSync(TEST_STORAGE, { recursive: true, force: true });
  }
}

/**
 * 创建包含并行组的架构图
 *
 * 流程：
 * S1(调研)
 *   ↓
 * [C1, F1, F2] 并行 (analysis 组)
 *   ↓
 * S2(综合分析)
 *   ↓
 * S3(输出)
 */
function createArchitecture(): ArchitectureGraph {
  const nodes = new Map<string, ANode>();

  // S1 - 调研
  nodes.set('S1', {
    id: 'S1',
    type: 'step',
    name: 'S1 调研',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  });

  // C1 - 技术面（并行组）
  nodes.set('C1', createParallelNode(
    {
      id: 'C1',
      type: 'step',
      name: 'C1 技术面分析',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  // F1 - 新闻面（并行组）
  nodes.set('F1', createParallelNode(
    {
      id: 'F1',
      type: 'step',
      name: 'F1 新闻面分析',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  // F2 - 资金流（并行组）
  nodes.set('F2', createParallelNode(
    {
      id: 'F2',
      type: 'step',
      name: 'F2 资金流分析',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  // S2 - 综合分析
  nodes.set('S2', {
    id: 'S2',
    type: 'step',
    name: 'S2 综合分析',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
    requires: ['C1', 'F1', 'F2'],
  });

  // S3 - 输出
  nodes.set('S3', {
    id: 'S3',
    type: 'step',
    name: 'S3 输出',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
    requires: ['S2'],
  });

  return {
    id: 'arch_parallel_test',
    blueprintId: 'bp_parallel_test',
    nodes,
    edges: [],
    entryPoint: 'S1',
    createdAt: Date.now(),
  };
}

function createBlueprint(): BlueprintGraph {
  const nodes = new Map<string, BNode>();

  nodes.set('root', {
    id: 'root',
    type: 'module',
    name: '并行分析测试流程',
    description: '用于测试并行链路的流程',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
    children: ['S1', 'C1', 'F1', 'F2', 'S2', 'S3'],
  });

  return {
    id: 'bp_parallel_test',
    name: '并行测试蓝图',
    version: '1.0.0',
    nodes,
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };
}

// ============================================================
// 集成测试
// ============================================================

console.log('\n🚀 Phase 3 并行链路集成验证测试');
console.log('='.repeat(50));

cleanup();

const arch = createArchitecture();
const bp = createBlueprint();

console.log('\n📋 测试场景：S1 → [C1, F1, F2 并行] → S2 → S3\n');

test('场景1: 完整并行流程执行', async () => {
  const executor = new ParallelGraphExecutor({
    architecture: arch,
    blueprint: bp,
    checkpointConfig: {
      storageDir: TEST_STORAGE,
      autoSave: true,
    },
  });

  // 注册节点处理器
  const makeHandler = (name: string, cost: number, delay: number) => async () => ({
    outputSummary: `${name} 完成`,
    tokenCost: cost,
    latencyMs: delay,
    confidence: 0.8,
    outputs: { source: name },
  });

  executor.registerNodeHandler('S1', makeHandler('S1 调研', 100, 100));
  executor.registerNodeHandler('C1', makeHandler('C1 技术面', 150, 200));
  executor.registerNodeHandler('F1', makeHandler('F1 新闻面', 120, 180));
  executor.registerNodeHandler('F2', makeHandler('F2 资金流', 130, 150));
  executor.registerNodeHandler('S2', makeHandler('S2 综合', 200, 300));
  executor.registerNodeHandler('S3', makeHandler('S3 输出', 50, 50));

  const result = await executor.execute();

  assert(result.success === true, '执行应该成功');
  assert(result.completedNodes === 6, `应该完成 6 个节点，实际 ${result.completedNodes}`);
  assert(result.parallelGroups === 1, `应该有 1 个并行组，实际 ${result.parallelGroups}`);

  // 计算总 Token
  const expectedTokens = 100 + 150 + 120 + 130 + 200 + 50; // 750
  assert(result.tokenUsed === expectedTokens, `Token 应该是 ${expectedTokens}，实际 ${result.tokenUsed}`);

  // 并行组应该被正确识别
  const groups = executor.getParallelGroups();
  assert(groups.size === 1, '应该识别 1 个并行组');
  assert(groups.get('analysis')!.length === 3, 'analysis 组应该有 3 个节点');

  console.log(`   完成节点: ${result.completedNodes}/${result.totalNodes}`);
  console.log(`   并行组: ${result.parallelGroups}`);
  console.log(`   Token: ${result.tokenUsed}`);
  console.log(`   置信度: ${result.finalConfidence}`);
});

test('场景2: 并行组正确识别', async () => {
  const executor = new ParallelGraphExecutor({
    architecture: arch,
    blueprint: bp,
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_groups',
      autoSave: false,
    },
  });

  const groups = executor.getParallelGroups();

  assert(groups.has('analysis'), '应该有 analysis 组');
  assert(groups.get('analysis')!.includes('C1'), '应该包含 C1');
  assert(groups.get('analysis')!.includes('F1'), '应该包含 F1');
  assert(groups.get('analysis')!.includes('F2'), '应该包含 F2');

  // 节点到组的映射
  assert(executor.getNodeGroup('C1') === 'analysis', 'C1 应该在 analysis 组');
  assert(executor.getNodeGroup('S1') === null, 'S1 不应该在任何组');

  console.log(`   并行组数: ${groups.size}`);
  console.log(`   analysis 组节点数: ${groups.get('analysis')!.length}`);
});

test('场景3: 并行执行结果可获取', async () => {
  const storageDir = TEST_STORAGE + '_results';
  if (fs.existsSync(storageDir)) {
    fs.rmSync(storageDir, { recursive: true, force: true });
  }

  const executor = new ParallelGraphExecutor({
    architecture: arch,
    blueprint: bp,
    checkpointConfig: { storageDir, autoSave: true },
  });

  const makeHandler = (name: string) => async () => ({
    outputSummary: `${name} 完成`,
    tokenCost: 100,
    latencyMs: 100,
    confidence: 0.8,
    outputs: { source: name },
  });

  for (const id of ['S1', 'C1', 'F1', 'F2', 'S2', 'S3']) {
    executor.registerNodeHandler(id, makeHandler(id));
  }

  await executor.execute();

  const stateManager = executor.getStateManager();

  // 检查并行节点的结果
  const c1Result = stateManager.getNodeResult('C1');
  const f1Result = stateManager.getNodeResult('F1');
  const f2Result = stateManager.getNodeResult('F2');

  assert(c1Result?.status === 'completed', 'C1 应该已完成');
  assert(f1Result?.status === 'completed', 'F1 应该已完成');
  assert(f2Result?.status === 'completed', 'F2 应该已完成');

  assert(c1Result?.outputs.source === 'C1', 'C1 的 source 应该是 C1');
  assert(f1Result?.outputs.source === 'F1', 'F1 的 source 应该是 F1');
  assert(f2Result?.outputs.source === 'F2', 'F2 的 source 应该是 F2');

  console.log(`   C1 状态: ${c1Result?.status}`);
  console.log(`   F1 状态: ${f1Result?.status}`);
  console.log(`   F2 状态: ${f2Result?.status}`);
});

test('场景4: Checkpoint 正确记录', async () => {
  const storageDir = TEST_STORAGE + '_checkpoints';
  if (fs.existsSync(storageDir)) {
    fs.rmSync(storageDir, { recursive: true, force: true });
  }

  const executor = new ParallelGraphExecutor({
    architecture: arch,
    blueprint: bp,
    checkpointConfig: { storageDir, autoSave: true },
  });

  const makeHandler = (name: string) => async () => ({
    outputSummary: `${name} 完成`,
    tokenCost: 100,
    latencyMs: 100,
    confidence: 0.8,
    outputs: {},
  });

  for (const id of ['S1', 'C1', 'F1', 'F2', 'S2', 'S3']) {
    executor.registerNodeHandler(id, makeHandler(id));
  }

  await executor.execute();

  const checkpointer = executor.getCheckpointer();
  const count = checkpointer.getCheckpointCount();

  // 应该有：S1 + C1(代表) + S2 + S3 = 4 个检查点
  // （并行组只记录代表节点一个检查点）
  assert(count >= 4, `应该至少有 4 个检查点，实际 ${count}`);

  const checkpoints = checkpointer.listCheckpoints();
  console.log(`   检查点总数: ${count}`);
  checkpoints.forEach((cp, i) => {
    console.log(`     ${i + 1}. ${cp.nodeName} - Token: ${cp.tokenUsed}`);
  });
});

test('场景5: 无并行节点的普通流程也能正常执行', async () => {
  // 创建一个没有并行节点的简单架构
  const simpleNodes = new Map<string, ANode>();
  simpleNodes.set('A', { id: 'A', type: 'step', name: 'A', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } });
  simpleNodes.set('B', { id: 'B', type: 'step', name: 'B', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['A'] });
  simpleNodes.set('C', { id: 'C', type: 'step', name: 'C', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['B'] });

  const simpleArch: ArchitectureGraph = {
    id: 'simple_arch',
    blueprintId: 'bp_simple',
    nodes: simpleNodes,
    edges: [],
    entryPoint: 'A',
    createdAt: Date.now(),
  };

  const simpleBp: BlueprintGraph = {
    id: 'bp_simple',
    name: 'simple',
    version: '1.0.0',
    nodes: new Map(),
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };

  const executor = new ParallelGraphExecutor({
    architecture: simpleArch,
    blueprint: simpleBp,
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_simple',
      autoSave: false,
    },
  });

  for (const id of ['A', 'B', 'C']) {
    executor.registerNodeHandler(id, async () => ({
      outputSummary: `${id} done`,
      tokenCost: 50,
      latencyMs: 50,
      confidence: 0.8,
      outputs: {},
    }));
  }

  const result = await executor.execute();

  assert(result.success === true, '应该成功');
  assert(result.completedNodes === 3, `应该完成 3 个节点，实际 ${result.completedNodes}`);
  assert(result.parallelGroups === 0, `应该有 0 个并行组，实际 ${result.parallelGroups}`);

  console.log(`   普通流程节点完成: ${result.completedNodes}/${result.totalNodes}`);
  console.log(`   并行组数: ${result.parallelGroups}`);
});

test('场景6: 多个并行组', async () => {
  // 创建有两个并行组的架构
  const multiNodes = new Map<string, ANode>();

  multiNodes.set('S1', { id: 'S1', type: 'step', name: 'S1', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } });

  // 并行组 1: 多源数据采集
  multiNodes.set('D1', createParallelNode(
    { id: 'D1', type: 'step', name: 'D1', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S1'] },
    { parallelGroup: 'data_collection' }
  ));
  multiNodes.set('D2', createParallelNode(
    { id: 'D2', type: 'step', name: 'D2', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S1'] },
    { parallelGroup: 'data_collection' }
  ));

  // 并行组 2: 多角度分析
  multiNodes.set('A1', createParallelNode(
    { id: 'A1', type: 'step', name: 'A1', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['D1', 'D2'] },
    { parallelGroup: 'analysis_multi' }
  ));
  multiNodes.set('A2', createParallelNode(
    { id: 'A2', type: 'step', name: 'A2', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['D1', 'D2'] },
    { parallelGroup: 'analysis_multi' }
  ));
  multiNodes.set('A3', createParallelNode(
    { id: 'A3', type: 'step', name: 'A3', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['D1', 'D2'] },
    { parallelGroup: 'analysis_multi' }
  ));

  multiNodes.set('S2', { id: 'S2', type: 'step', name: 'S2', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['A1', 'A2', 'A3'] });

  const multiArch: ArchitectureGraph = {
    id: 'multi_arch',
    blueprintId: 'bp_multi',
    nodes: multiNodes,
    edges: [],
    entryPoint: 'S1',
    createdAt: Date.now(),
  };

  const multiBp: BlueprintGraph = {
    id: 'bp_multi',
    name: 'multi',
    version: '1.0.0',
    nodes: new Map(),
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };

  const executor = new ParallelGraphExecutor({
    architecture: multiArch,
    blueprint: multiBp,
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_multi',
      autoSave: false,
    },
  });

  for (const id of ['S1', 'D1', 'D2', 'A1', 'A2', 'A3', 'S2']) {
    executor.registerNodeHandler(id, async () => ({
      outputSummary: `${id} done`,
      tokenCost: 100,
      latencyMs: 100,
      confidence: 0.8,
      outputs: {},
    }));
  }

  const result = await executor.execute();

  assert(result.success === true, '应该成功');
  assert(result.completedNodes === 7, `应该完成 7 个节点，实际 ${result.completedNodes}`);
  assert(result.parallelGroups === 2, `应该有 2 个并行组，实际 ${result.parallelGroups}`);

  const groups = executor.getParallelGroups();
  assert(groups.size === 2, `应该识别 2 个并行组，实际 ${groups.size}`);

  console.log(`   多并行组节点完成: ${result.completedNodes}/${result.totalNodes}`);
  console.log(`   并行组数: ${result.parallelGroups}`);
  console.log(`   识别的组: ${Array.from(groups.keys()).join(', ')}`);
});

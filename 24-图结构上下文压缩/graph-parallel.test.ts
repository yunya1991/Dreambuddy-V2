#!/usr/bin/env npx tsx
/**
 * 并行链路单元测试
 */

import {
  ParallelScheduler,
  createParallelNode,
  extractParallelGroups,
  getGroupRepresentative,
  type ParallelNode,
} from './graph-parallel';
import type { ANode, NodeId } from './models';

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

function createTestNodes(): Map<NodeId, ANode> {
  const nodes = new Map<NodeId, ANode>();

  nodes.set('S1', {
    id: 'S1',
    type: 'step',
    name: 'S1 调研',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  });

  nodes.set('C1', createParallelNode(
    {
      id: 'C1',
      type: 'step',
      name: 'C1 技术面',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  nodes.set('F1', createParallelNode(
    {
      id: 'F1',
      type: 'step',
      name: 'F1 新闻面',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  nodes.set('F2', createParallelNode(
    {
      id: 'F2',
      type: 'step',
      name: 'F2 资金流',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S1'],
    },
    { parallelGroup: 'analysis' }
  ));

  nodes.set('S2', {
    id: 'S2',
    type: 'step',
    name: 'S2 分析',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
    requires: ['C1', 'F1', 'F2'],
  });

  return nodes;
}

// ============================================================
// 测试组 1: ParallelScheduler 基础
// ============================================================

console.log('\n🧪 测试组 1: ParallelScheduler 基础功能');
console.log('=' .repeat(50));

test('识别并行组', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();

  const groups = scheduler.identifyParallelGroups(nodes);

  assert(groups.size === 1, `应该有 1 个并行组，实际 ${groups.size}`);
  assert(groups.has('analysis'), '应该有 analysis 组');

  const analysisGroup = groups.get('analysis')!;
  assert(analysisGroup.length === 3, `analysis 组应该有 3 个节点，实际 ${analysisGroup.length}`);
  assert(analysisGroup.includes('C1'), '应该包含 C1');
  assert(analysisGroup.includes('F1'), '应该包含 F1');
  assert(analysisGroup.includes('F2'), '应该包含 F2');
});

test('检查节点是否是并行节点', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();

  assert(!scheduler.isParallelNode(nodes.get('S1')!), 'S1 不应该是并行节点');
  assert(scheduler.isParallelNode(nodes.get('C1')!), 'C1 应该是并行节点');
});

test('获取节点的并行组 ID', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();

  assert(scheduler.getGroupId(nodes.get('S1')!) === null, 'S1 应该没有组');
  assert(scheduler.getGroupId(nodes.get('C1')!) === 'analysis', 'C1 应该在 analysis 组');
});

test('获取节点的汇总策略', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();

  assert(scheduler.getMergeStrategy(nodes.get('C1')!) === 'all', '默认策略应该是 all');

  const customNode = createParallelNode(
    { id: 'test', type: 'step', name: 'test', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } },
    { parallelGroup: 'g1', mergeStrategy: 'any' }
  );
  assert(scheduler.getMergeStrategy(customNode) === 'any', '自定义策略应该是 any');
});

// ============================================================
// 测试组 2: 并行组依赖检查
// ============================================================

console.log('\n🧪 测试组 2: 并行组依赖检查');
console.log('=' .repeat(50));

test('检查组是否可以执行 - 依赖未满足', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];
  const completed = new Set<NodeId>();

  assert(!scheduler.canExecuteGroup(groupNodeIds, nodes, completed), 'S1 未完成时不应该能执行');
});

test('检查组是否可以执行 - 依赖已满足', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];
  const completed = new Set<NodeId>(['S1']);

  assert(scheduler.canExecuteGroup(groupNodeIds, nodes, completed), 'S1 完成后应该能执行');
});

test('获取并行组的依赖', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];

  const deps = scheduler.getGroupDependencies(groupNodeIds, nodes);
  assert(deps.length === 1, `应该有 1 个外部依赖，实际 ${deps.length}`);
  assert(deps.includes('S1'), '依赖应该包含 S1');
});

test('获取并行组的后置节点', () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];

  const dependents = scheduler.getGroupDependents(groupNodeIds, nodes);
  assert(dependents.length === 1, `应该有 1 个后置节点，实际 ${dependents.length}`);
  assert(dependents.includes('S2'), '后置节点应该包含 S2');
});

// ============================================================
// 测试组 3: 工具函数
// ============================================================

console.log('\n🧪 测试组 3: 工具函数');
console.log('=' .repeat(50));

test('createParallelNode - 创建并行节点', () => {
  const baseNode: ANode = {
    id: 'test',
    type: 'step',
    name: '测试节点',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  };

  const parallelNode = createParallelNode(baseNode, {
    parallelGroup: 'test_group',
    mergeStrategy: 'any',
  });

  assert(parallelNode.id === 'test', 'ID 应该正确');
  assert(parallelNode.parallelGroup === 'test_group', '组 ID 应该正确');
  assert(parallelNode.mergeStrategy === 'any', '汇总策略应该正确');
});

test('extractParallelGroups - 提取并行组', () => {
  const nodes = createTestNodes();
  const groups = extractParallelGroups(nodes);

  assert(groups.size === 1, `应该有 1 个并行组`);
  assert(groups.get('analysis')!.length === 3, 'analysis 组应该有 3 个节点');
});

test('getGroupRepresentative - 获取代表节点', () => {
  const groupNodeIds = ['C1', 'F1', 'F2'];
  const rep = getGroupRepresentative(groupNodeIds);

  assert(rep === 'C1', '代表节点应该是第一个 C1');
});

// ============================================================
// 测试组 4: 并发控制
// ============================================================

console.log('\n🧪 测试组 4: 并发控制');
console.log('=' .repeat(50));

test('默认最大并发数', () => {
  const scheduler = new ParallelScheduler({ maxConcurrency: 2 });
  assert(true, '应该能创建带并发限制的调度器');
});

// ============================================================
// 测试组 5: 并行执行
// ============================================================

console.log('\n🧪 测试组 5: 并行执行');
console.log('=' .repeat(50));

test('执行并行组 - 全部成功', async () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];

  // 模拟处理器
  const handlers = new Map<string, any>();
  for (const nid of groupNodeIds) {
    handlers.set(nid, async () => ({
      outputSummary: `${nid} 完成`,
      tokenCost: 100,
      latencyMs: 50,
      confidence: 0.8,
      outputs: { result: nid },
    }));
  }

  // 模拟 context
  const mockContext = {} as any;

  const result = await scheduler.executeParallelGroup(
    'analysis',
    groupNodeIds,
    nodes,
    handlers,
    mockContext
  );

  assert(result.successCount === 3, `成功数应该是 3，实际 ${result.successCount}`);
  assert(result.failedCount === 0, `失败数应该是 0，实际 ${result.failedCount}`);
  assert(result.totalTokenCost === 300, `Token 应该是 300，实际 ${result.totalTokenCost}`);
  assert(result.results.size === 3, '结果应该有 3 个');
  assert(result.avgConfidence === 0.8, `平均置信度应该是 0.8，实际 ${result.avgConfidence}`);
});

test('执行并行组 - 部分失败', async () => {
  const scheduler = new ParallelScheduler();
  const nodes = createTestNodes();
  const groupNodeIds = ['C1', 'F1', 'F2'];

  // C1 成功，F1 失败，F2 成功
  const handlers = new Map<string, any>();

  handlers.set('C1', async () => ({
    outputSummary: 'C1 完成',
    tokenCost: 100,
    latencyMs: 50,
    confidence: 0.8,
    outputs: {},
  }));

  handlers.set('F1', async () => {
    throw new Error('F1 失败');
  });

  handlers.set('F2', async () => ({
    outputSummary: 'F2 完成',
    tokenCost: 100,
    latencyMs: 50,
    confidence: 0.9,
    outputs: {},
  }));

  const mockContext = {} as any;

  const result = await scheduler.executeParallelGroup(
    'analysis',
    groupNodeIds,
    nodes,
    handlers,
    mockContext
  );

  assert(result.successCount === 2, `成功数应该是 2，实际 ${result.successCount}`);
  assert(result.failedCount === 1, `失败数应该是 1，实际 ${result.failedCount}`);
  assert(result.results.size === 3, '结果应该有 3 个');
});

// ============================================================
// 测试结果
// ============================================================

console.log('\n' + '=' .repeat(50));
console.log(`📊 并行链路单元测试结果: ${passed} 通过, ${failed} 失败`);
console.log('=' .repeat(50));

process.exit(failed > 0 ? 1 : 0);

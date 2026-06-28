#!/usr/bin/env npx tsx
/**
 * HITL 人机协作单元测试
 */

import {
  HITLManager,
  getHITLNodes,
  sortByRisk,
  createHITLNode,
  type HITLNode,
  type InterruptContext,
} from './graph-hitl';
import { GraphStateManager } from './graph-state';
import type { ANode, ArchitectureGraph, BlueprintGraph } from './models';

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

function createTestNode(): ANode {
  return {
    id: 'S4',
    type: 'step',
    name: 'S4 验证',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  };
}

function createHITLTestNode(config: Partial<HITLNode> = {}): HITLNode {
  return {
    id: 'S4',
    type: 'step',
    name: 'S4 验证',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
    interruptBefore: true,
    riskLevel: 'high',
    interruptLabel: '即将执行验证步骤',
    ...config,
  };
}

function createTestState() {
  const arch: ArchitectureGraph = {
    id: 'test_arch',
    blueprintId: 'test_bp',
    nodes: new Map([
      ['S1', { id: 'S1', type: 'step', name: 'S1', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } }],
      ['S2', { id: 'S2', type: 'step', name: 'S2', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S1'] }],
      ['S3', { id: 'S3', type: 'step', name: 'S3', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' }, requires: ['S2'] }],
    ]),
    edges: [],
    entryPoint: 'S1',
    createdAt: Date.now(),
  };

  const bp: BlueprintGraph = {
    id: 'test_bp',
    name: 'test',
    version: '1.0.0',
    nodes: new Map(),
    edges: [],
    rootId: 'root',
    createdAt: Date.now(),
  };

  return new GraphStateManager({ architecture: arch, blueprint: bp });
}

// ============================================================
// 测试组 1: HITLManager 基础
// ============================================================

console.log('\n🧪 测试组 1: HITLManager 基础功能');
console.log('=' .repeat(50));

test('HITL 默认禁用', () => {
  const manager = new HITLManager();
  assert(!manager.isEnabled(), '默认应该禁用');
});

test('启用/禁用 HITL', () => {
  const manager = new HITLManager();
  manager.setEnabled(true);
  assert(manager.isEnabled(), '启用后应该为 true');
  manager.setEnabled(false);
  assert(!manager.isEnabled(), '禁用后应该为 false');
});

test('禁用时 shouldInterrupt 总是返回 false', () => {
  const manager = new HITLManager({ enabled: false });
  const node = createHITLTestNode();
  assert(!manager.shouldInterrupt(node), '禁用时不应该中断');
});

test('启用时 interruptBefore=false 不中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createTestNode(); // 没有 interruptBefore
  assert(!manager.shouldInterrupt(node), '没有标记的节点不应该中断');
});

test('启用时 interruptBefore=true 中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  assert(manager.shouldInterrupt(node), '标记的节点应该中断');
});

test('低风险节点启用 autoApproveLowRisk 时不中断', () => {
  const manager = new HITLManager({ enabled: true, autoApproveLowRisk: true });
  const node = createHITLTestNode({ riskLevel: 'low' });
  assert(!manager.shouldInterrupt(node), '低风险自动通过不应该中断');
});

test('中风险节点启用 autoApproveLowRisk 时仍然中断', () => {
  const manager = new HITLManager({ enabled: true, autoApproveLowRisk: true });
  const node = createHITLTestNode({ riskLevel: 'medium' });
  assert(manager.shouldInterrupt(node), '中风险应该中断');
});

// ============================================================
// 测试组 2: 中断创建与解决
// ============================================================

console.log('\n🧪 测试组 2: 中断创建与解决');
console.log('=' .repeat(50));

test('创建中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();
  const state = stateManager.getState();

  const interrupt = manager.createInterrupt(node, state);
  assert(interrupt.interruptId.startsWith('int_'), '中断 ID 应该以 int_ 开头');
  assert(interrupt.nodeId === 'S4', '节点 ID 应该正确');
  assert(interrupt.riskLevel === 'high', '风险等级应该正确');
  assert(interrupt.label === '即将执行验证步骤', '标签应该正确');
  assert(interrupt.interruptedAt > 0, '应该有中断时间');
});

test('获取活跃中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  assert(!manager.hasActiveInterrupt(), '初始不应该有活跃中断');

  manager.createInterrupt(node, stateManager.getState());
  assert(manager.hasActiveInterrupt(), '创建后应该有活跃中断');
  assert(manager.getActiveInterrupt() !== null, 'getActiveInterrupt 应该返回中断');
});

test('解决中断 - approve', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  const result = manager.resolveInterrupt(interrupt.interruptId, 'approve');

  assert(result.decision === 'approve', '决策应该是 approve');
  assert(result.decidedAt > 0, '应该有决策时间');
  assert(!manager.hasActiveInterrupt(), '解决后不应该有活跃中断');
});

test('解决中断 - reject', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  const result = manager.resolveInterrupt(interrupt.interruptId, 'reject');

  assert(result.decision === 'reject', '决策应该是 reject');
});

test('解决中断 - edit', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  const result = manager.resolveInterrupt(interrupt.interruptId, 'edit', {
    modifiedInput: { param: 'new_value' },
    note: '修改了参数',
  });

  assert(result.decision === 'edit', '决策应该是 edit');
  assert(result.modifiedInput?.param === 'new_value', '修改的输入应该正确');
  assert(result.note === '修改了参数', '备注应该正确');
});

test('获取决策结果', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  manager.resolveInterrupt(interrupt.interruptId, 'approve');

  const decision = manager.getDecision(interrupt.interruptId);
  assert(decision !== undefined, '应该能获取决策');
  assert(decision!.decision === 'approve', '决策应该正确');
});

// ============================================================
// 测试组 3: 中断历史与统计
// ============================================================

console.log('\n🧪 测试组 3: 中断历史与统计');
console.log('=' .repeat(50));

test('获取中断历史', () => {
  const manager = new HITLManager({ enabled: true });
  const stateManager = createTestState();

  const n1 = createHITLTestNode({ id: 'S1', name: 'S1' });
  const n2 = createHITLTestNode({ id: 'S2', name: 'S2' });

  const i1 = manager.createInterrupt(n1, stateManager.getState());
  manager.resolveInterrupt(i1.interruptId, 'approve');

  const i2 = manager.createInterrupt(n2, stateManager.getState());

  const history = manager.getInterruptHistory();
  assert(history.length === 2, '应该有 2 条中断历史');
  assert(history[0].interrupt.nodeId === 'S1', '第 1 条应该是 S1');
  assert(history[0].decision?.decision === 'approve', '第 1 条有决策');
  assert(history[1].interrupt.nodeId === 'S2', '第 2 条应该是 S2');
  assert(history[1].decision === undefined, '第 2 条没有决策');
});

test('统计信息', () => {
  const manager = new HITLManager({ enabled: true });
  const stateManager = createTestState();

  const n1 = createHITLTestNode({ id: 'S1' });
  const n2 = createHITLTestNode({ id: 'S2' });
  const n3 = createHITLTestNode({ id: 'S3' });

  const i1 = manager.createInterrupt(n1, stateManager.getState());
  manager.resolveInterrupt(i1.interruptId, 'approve');

  const i2 = manager.createInterrupt(n2, stateManager.getState());
  manager.resolveInterrupt(i2.interruptId, 'reject');

  manager.createInterrupt(n3, stateManager.getState()); // pending

  const stats = manager.getStats();
  assert(stats.totalInterrupts === 3, '总中断数应为 3');
  assert(stats.approved === 1, '通过数应为 1');
  assert(stats.rejected === 1, '拒绝数应为 1');
  assert(stats.edited === 0, '编辑数应为 0');
  assert(stats.pending === 1, '待处理数应为 1');
});

// ============================================================
// 测试组 4: 辅助函数
// ============================================================

console.log('\n🧪 测试组 4: 辅助函数');
console.log('=' .repeat(50));

test('getHITLNodes - 提取 HITL 节点', () => {
  const nodes = new Map<string, ANode>();
  nodes.set('S1', { id: 'S1', type: 'step', name: 'S1', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } });
  nodes.set('S2', createHITLTestNode({ id: 'S2', name: 'S2' }));
  nodes.set('S3', { id: 'S3', type: 'step', name: 'S3', parentNodeId: 'root', metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' } });
  nodes.set('S4', createHITLTestNode({ id: 'S4', name: 'S4' }));

  const hitlNodes = getHITLNodes(nodes);
  assert(hitlNodes.length === 2, '应该有 2 个 HITL 节点');
  assert(hitlNodes[0].id === 'S2', '第一个应该是 S2');
  assert(hitlNodes[1].id === 'S4', '第二个应该是 S4');
});

test('sortByRisk - 按风险排序', () => {
  const nodes: HITLNode[] = [
    createHITLTestNode({ id: 'low', riskLevel: 'low' }),
    createHITLTestNode({ id: 'high', riskLevel: 'high' }),
    createHITLTestNode({ id: 'medium', riskLevel: 'medium' }),
  ];

  const sorted = sortByRisk(nodes);
  assert(sorted[0].riskLevel === 'high', '第一个应该是 high');
  assert(sorted[1].riskLevel === 'medium', '第二个应该是 medium');
  assert(sorted[2].riskLevel === 'low', '第三个应该是 low');
});

test('createHITLNode - 创建 HITL 节点', () => {
  const baseNode: ANode = {
    id: 'S5',
    type: 'step',
    name: 'S5',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  };

  const hitlNode = createHITLNode(baseNode, {
    interruptBefore: true,
    riskLevel: 'high',
    interruptLabel: '即将下单',
  });

  assert(hitlNode.id === 'S5', 'ID 应该正确');
  assert(hitlNode.interruptBefore === true, 'interruptBefore 应该正确');
  assert(hitlNode.riskLevel === 'high', '风险等级应该正确');
  assert(hitlNode.interruptLabel === '即将下单', '标签应该正确');
});

// ============================================================
// 测试组 5: 超时检查
// ============================================================

console.log('\n🧪 测试组 5: 超时检查');
console.log('=' .repeat(50));

test('未超时的中断', () => {
  const manager = new HITLManager({ enabled: true, defaultTimeoutMs: 10000 });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  assert(!manager.isInterruptExpired(interrupt), '刚创建的中断不应该超时');
});

test('无超时设置的中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  const interrupt = manager.createInterrupt(node, stateManager.getState());
  assert(interrupt.timeoutMs !== undefined, '应该有超时设置');
});

test('清除所有中断', () => {
  const manager = new HITLManager({ enabled: true });
  const node = createHITLTestNode();
  const stateManager = createTestState();

  manager.createInterrupt(node, stateManager.getState());
  assert(manager.hasActiveInterrupt(), '创建后应该有活跃中断');

  manager.clearAll();
  assert(!manager.hasActiveInterrupt(), '清除后不应该有活跃中断');
  assert(manager.getStats().totalInterrupts === 0, '清除后历史应该为空');
});

// ============================================================
// 测试结果
// ============================================================

console.log('\n' + '=' .repeat(50));
console.log(`📊 HITL 单元测试结果: ${passed} 通过, ${failed} 失败`);
console.log('=' .repeat(50));

process.exit(failed > 0 ? 1 : 0);

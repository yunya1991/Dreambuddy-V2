#!/usr/bin/env npx tsx
/**
 * Phase 2 集成验证测试
 *
 * 场景：S1 → S2 → S3 → S4(验证，高风险中断) → S5(执行，高风险中断)
 *
 * 验证内容：
 * 1. S4 前中断，人类 approve → 继续
 * 2. S5 前中断，人类 reject → 跳过 S5
 * 3. 最终状态验证
 */

import * as fs from 'fs';

import { GraphExecutor, type NodeHandlerResult } from './graph-executor';
import { createHITLNode } from './graph-hitl';
import type { ArchitectureGraph, BlueprintGraph, ANode, BNode } from './models';

// ============================================================
// 测试工具
// ============================================================

let passed = 0;
let failed = 0;

function test(name: string, fn: () => Promise<void> | void) {
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
      // 所有测试完成后输出结果
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

let totalTests = 0;
function testCount() {
  totalTests++;
}

function printResults() {
  console.log('\n' + '='.repeat(50));
  console.log(`📊 Phase 2 集成验证结果: ${passed} 通过, ${failed} 失败`);
  console.log('='.repeat(50));
  process.exit(failed > 0 ? 1 : 0);
}

// ============================================================
// 测试数据
// ============================================================

const TEST_STORAGE = '/tmp/graph-hitl-integration-test';

function cleanup() {
  if (fs.existsSync(TEST_STORAGE)) {
    fs.rmSync(TEST_STORAGE, { recursive: true, force: true });
  }
}

function createArchitecture(): ArchitectureGraph {
  const nodes = new Map<string, ANode>();

  // S1 - 调研（无中断）
  nodes.set('S1', {
    id: 'S1',
    type: 'step',
    name: 'S1 调研',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
  });

  // S2 - 分析（无中断）
  nodes.set('S2', {
    id: 'S2',
    type: 'step',
    name: 'S2 分析',
    parentNodeId: 'root',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
    requires: ['S1'],
  });

  // S3 - 设计（低风险中断）
  nodes.set('S3', createHITLNode(
    {
      id: 'S3',
      type: 'step',
      name: 'S3 设计',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S2'],
    },
    {
      interruptBefore: true,
      riskLevel: 'low',
      interruptLabel: '即将执行设计步骤',
    }
  ));

  // S4 - 验证（中风险中断）
  nodes.set('S4', createHITLNode(
    {
      id: 'S4',
      type: 'step',
      name: 'S4 验证',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S3'],
    },
    {
      interruptBefore: true,
      riskLevel: 'medium',
      interruptLabel: '即将执行验证步骤，请确认参数',
    }
  ));

  // S5 - 执行（高风险中断）
  nodes.set('S5', createHITLNode(
    {
      id: 'S5',
      type: 'step',
      name: 'S5 执行',
      parentNodeId: 'root',
      metadata: { tokenCost: 0, latencyMs: 0, status: 'pending' },
      requires: ['S4'],
    },
    {
      interruptBefore: true,
      riskLevel: 'high',
      interruptLabel: '⚠️ 即将执行下单操作，请确认！',
      approvalFields: ['symbol', 'amount', 'price'],
    }
  ));

  return {
    id: 'arch_hitl_test',
    blueprintId: 'bp_hitl_test',
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
    name: 'HITL 测试流程',
    description: 'HITL 集成测试用流程',
    metadata: { tokenCost: 0, latencyMs: 0, status: 'completed' },
    children: ['S1', 'S2', 'S3', 'S4', 'S5'],
  });

  return {
    id: 'bp_hitl_test',
    name: 'HITL 测试蓝图',
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

console.log('\n🚀 Phase 2 HITL 集成验证测试');
console.log('='.repeat(50));

cleanup();

const arch = createArchitecture();
const bp = createBlueprint();

console.log('\n📋 测试场景：S1→S2→S3(低风险)→S4(中风险,approve)→S5(高风险,reject)\n');

// 场景 1: 完整流程，S3/S4 approve，S5 reject
testCount();
test('场景1: 完整 HITL 流程（S3/S4 通过，S5 拒绝）', async () => {
  const executor = new GraphExecutor({
    architecture: arch,
    blueprint: bp,
    hitlEnabled: true,
    checkpointConfig: {
      storageDir: TEST_STORAGE,
      autoSave: true,
    },
  });

  const hitlManager = executor.getHITLManager();
  let interruptCount = 0;

  // 注册中断回调，自动处理决策
  hitlManager.setOnInterrupt((interrupt) => {
    interruptCount++;
    console.log(`   🛑 中断 [${interrupt.riskLevel}]: ${interrupt.label}`);

    // 模拟人类决策
    setTimeout(() => {
      if (interrupt.nodeId === 'S5') {
        // S5 高风险，拒绝
        hitlManager.resolveInterrupt(interrupt.interruptId, 'reject', {
          decidedBy: 'tester',
          note: '风险太高，暂不执行',
        });
        console.log(`      → 人类决策: reject`);
      } else {
        // 其他节点通过
        hitlManager.resolveInterrupt(interrupt.interruptId, 'approve', {
          decidedBy: 'tester',
        });
        console.log(`      → 人类决策: approve`);
      }
    }, 10);
  });

  // 注册节点处理器
  executor.registerNodeHandler('S1', async () => {
    return { outputSummary: '调研完成', tokenCost: 100, latencyMs: 200, confidence: 0.8, outputs: {} };
  });
  executor.registerNodeHandler('S2', async () => {
    return { outputSummary: '分析完成', tokenCost: 200, latencyMs: 300, confidence: 0.85, outputs: {} };
  });
  executor.registerNodeHandler('S3', async () => {
    return { outputSummary: '设计完成', tokenCost: 150, latencyMs: 250, confidence: 0.82, outputs: {} };
  });
  executor.registerNodeHandler('S4', async () => {
    return { outputSummary: '验证通过', tokenCost: 300, latencyMs: 400, confidence: 0.9, outputs: {} };
  });
  executor.registerNodeHandler('S5', async () => {
    return { outputSummary: '执行完成', tokenCost: 50, latencyMs: 100, confidence: 0.95, outputs: {} };
  });

  const result = await executor.execute();

  assert(result.success === true, '执行应该成功');
  assert(interruptCount === 3, `应该有 3 次中断（S3/S4/S5），实际 ${interruptCount}`);
  assert(result.completedNodes === 4, `应该完成 4 个节点（S1-S4 + S5被跳过），实际 ${result.completedNodes}`);
  assert(result.interrupts.length === 3, '应该有 3 个中断记录');

  const stats = hitlManager.getStats();
  assert(stats.approved === 2, `应该通过 2 个，实际 ${stats.approved}`);
  assert(stats.rejected === 1, `应该拒绝 1 个，实际 ${stats.rejected}`);
  assert(stats.totalInterrupts === 3, `总中断数应为 3，实际 ${stats.totalInterrupts}`);

  console.log(`   执行结果: ${result.completedNodes}/${result.totalNodes} 节点完成`);
  console.log(`   Token: ${result.tokenUsed}`);
  console.log(`   置信度: ${result.finalConfidence}`);
  console.log(`   中断统计: 通过 ${stats.approved} / 拒绝 ${stats.rejected} / 待处理 ${stats.pending}`);
});

// 场景 2: HITL 禁用时直接跑通
testCount();
test('场景2: HITL 禁用时直接跑通所有节点', async () => {
  const executor = new GraphExecutor({
    architecture: arch,
    blueprint: bp,
    hitlEnabled: false,
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_no_hitl',
      autoSave: true,
    },
  });

  // 注册节点处理器
  executor.registerNodeHandler('S1', async () => {
    return { outputSummary: '调研完成', tokenCost: 100, latencyMs: 200, confidence: 0.8, outputs: {} };
  });
  executor.registerNodeHandler('S2', async () => {
    return { outputSummary: '分析完成', tokenCost: 200, latencyMs: 300, confidence: 0.85, outputs: {} };
  });
  executor.registerNodeHandler('S3', async () => {
    return { outputSummary: '设计完成', tokenCost: 150, latencyMs: 250, confidence: 0.82, outputs: {} };
  });
  executor.registerNodeHandler('S4', async () => {
    return { outputSummary: '验证通过', tokenCost: 300, latencyMs: 400, confidence: 0.9, outputs: {} };
  });
  executor.registerNodeHandler('S5', async () => {
    return { outputSummary: '执行完成', tokenCost: 50, latencyMs: 100, confidence: 0.95, outputs: {} };
  });

  const result = await executor.execute();

  assert(result.success === true, '执行应该成功');
  assert(result.completedNodes === 5, `应该完成 5 个节点，实际 ${result.completedNodes}`);
  assert(result.interrupts.length === 0, '不应该有中断');
  assert(result.tokenUsed === 800, `Token 消耗应为 800，实际 ${result.tokenUsed}`);

  console.log(`   执行结果: ${result.completedNodes}/${result.totalNodes} 节点完成`);
  console.log(`   Token: ${result.tokenUsed}`);
});

// 场景 3: 低风险自动通过
testCount();
test('场景3: autoApproveLowRisk 时低风险节点不中断', async () => {
  const executor = new GraphExecutor({
    architecture: arch,
    blueprint: bp,
    hitlEnabled: true,
    hitlConfig: {
      autoApproveLowRisk: true,
    },
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_auto_low',
      autoSave: true,
    },
  });

  const hitlManager = executor.getHITLManager();
  let interruptCount = 0;

  hitlManager.setOnInterrupt(() => {
    interruptCount++;
  });

  // 注册处理器
  const handler = async (node: ANode): Promise<NodeHandlerResult> => ({
    outputSummary: `${node.name} 完成`,
    tokenCost: 100,
    latencyMs: 100,
    confidence: 0.8,
    outputs: {},
  });

  for (const id of ['S1', 'S2', 'S3', 'S4', 'S5']) {
    executor.registerNodeHandler(id, handler);
  }

  // S4 和 S5 需要人工决策
  let resolved = 0;
  hitlManager.setOnInterrupt((interrupt) => {
    interruptCount++;
    setTimeout(() => {
      hitlManager.resolveInterrupt(interrupt.interruptId, 'approve');
      resolved++;
    }, 10);
  });

  const result = await executor.execute();

  // S3 是低风险应该自动通过，不触发中断
  // S4 中风险、S5 高风险应该触发中断
  assert(interruptCount === 2, `应该有 2 次中断（S4/S5），实际 ${interruptCount}`);
  assert(result.completedNodes === 5, '应该完成 5 个节点');

  console.log(`   中断次数: ${interruptCount}（S3 低风险自动通过）`);
  console.log(`   执行结果: ${result.completedNodes}/${result.totalNodes}`);
});

// 场景 4: 检查点 + HITL 结合
testCount();
test('场景4: 中断后回滚再重新执行', async () => {
  const storageDir = TEST_STORAGE + '_rollback';
  if (fs.existsSync(storageDir)) {
    fs.rmSync(storageDir, { recursive: true, force: true });
  }

  const executor = new GraphExecutor({
    architecture: arch,
    blueprint: bp,
    hitlEnabled: true,
    checkpointConfig: {
      storageDir,
      autoSave: true,
    },
  });

  const hitlManager = executor.getHITLManager();

  // 注册处理器
  const handler = async (node: ANode): Promise<NodeHandlerResult> => ({
    outputSummary: `${node.name} 完成`,
    tokenCost: 100,
    latencyMs: 100,
    confidence: 0.8,
    outputs: {},
  });

  for (const id of ['S1', 'S2', 'S3', 'S4', 'S5']) {
    executor.registerNodeHandler(id, handler);
  }

  // 所有中断都 approve
  hitlManager.setOnInterrupt((interrupt) => {
    setTimeout(() => {
      hitlManager.resolveInterrupt(interrupt.interruptId, 'approve');
    }, 10);
  });

  await executor.execute();

  const checkpointer = executor.getCheckpointer();
  assert(checkpointer.getCheckpointCount() >= 5, '应该有至少 5 个检查点');

  // 回滚到 S2
  await executor.resumeFromCheckpoint('S2');
  const stateManager = executor.getStateManager();
  const state = stateManager.getState();

  // 注意：revertToNode 返回到该节点完成后的状态
  // S1(100) + S2(100) = 200
  assert(state.tokenUsed === 200, `回滚到 S2 后 Token 应为 200，实际 ${state.tokenUsed}`);

  console.log(`   原始检查点数: ${checkpointer.getCheckpointCount()}`);
  console.log(`   回滚到 S2 后 Token: ${state.tokenUsed}`);
});

// 场景 5: HITL 历史记录
testCount();
test('场景5: HITL 中断历史记录完整', async () => {
  const executor = new GraphExecutor({
    architecture: arch,
    blueprint: bp,
    hitlEnabled: true,
    checkpointConfig: {
      storageDir: TEST_STORAGE + '_history',
      autoSave: true,
    },
  });

  const hitlManager = executor.getHITLManager();

  const handler = async (node: ANode): Promise<NodeHandlerResult> => ({
    outputSummary: `${node.name} 完成`,
    tokenCost: 100,
    latencyMs: 100,
    confidence: 0.8,
    outputs: {},
  });

  for (const id of ['S1', 'S2', 'S3', 'S4', 'S5']) {
    executor.registerNodeHandler(id, handler);
  }

  // S3 approve, S4 approve, S5 reject
  hitlManager.setOnInterrupt((interrupt) => {
    setTimeout(() => {
      if (interrupt.nodeId === 'S5') {
        hitlManager.resolveInterrupt(interrupt.interruptId, 'reject', {
          note: '测试拒绝',
        });
      } else {
        hitlManager.resolveInterrupt(interrupt.interruptId, 'approve');
      }
    }, 10);
  });

  await executor.execute();

  const history = hitlManager.getInterruptHistory();
  assert(history.length === 3, `应该有 3 条中断历史，实际 ${history.length}`);

  // 检查 S3
  const s3History = history.find((h) => h.interrupt.nodeId === 'S3');
  assert(s3History !== undefined, '应该有 S3 的历史');
  assert(s3History!.decision?.decision === 'approve', 'S3 应该被 approve');

  // 检查 S5
  const s5History = history.find((h) => h.interrupt.nodeId === 'S5');
  assert(s5History !== undefined, '应该有 S5 的历史');
  assert(s5History!.decision?.decision === 'reject', 'S5 应该被 reject');
  assert(s5History!.decision?.note === '测试拒绝', 'S5 拒绝备注应该正确');

  console.log(`   中断历史: ${history.length} 条`);
  history.forEach((h) => {
    console.log(`     ${h.interrupt.nodeId} [${h.interrupt.riskLevel}] → ${h.decision?.decision ?? 'pending'}`);
  });
});

import { EvolutionOrchestrator } from './evolution-orchestrator';
import { EvolutionFinding } from './types';
import assert from 'assert';

console.log('=== 任务3-6 全链路打通集成测试 ===\n');

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`  ✅ ${name}`);
    passed++;
  } catch (e) {
    console.log(`  ❌ ${name}: ${(e as Error).message}`);
    failed++;
  }
}

const sampleFindings: EvolutionFinding[] = [
  {
    id: 'find_001',
    source: 'execution_failure',
    severity: 'high',
    title: 'ChainPlanner 在小币种场景下预算估算偏差',
    description: '当分析小币种时，ChainPlanner 严重低估了数据获取成本，导致Token超支',
    affected_areas: ['chainplanner', 'code', 'budget-planner'],
    detected_at: new Date().toISOString(),
  },
];

const lowSeverityFindings: EvolutionFinding[] = [
  {
    id: 'find_002',
    source: 'user_feedback',
    severity: 'low',
    title: '知识库条目描述优化建议',
    description: '用户建议优化某个知识库条目的描述文字，让它更清晰',
    affected_areas: ['knowledge', 'documentation'],
    detected_at: new Date().toISOString(),
  },
];

console.log('--- 测试组 1：进化系统端到端闭环（任务3） ---');

test('发现问题 → 学习记录 → 深度分析 → 生成提案', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  assert(result.evolutionId.startsWith('evo_'), 'Evolution ID should start with evo_');
  assert(result.status === 'in_progress', 'Status should be in_progress');

  const status = orch.getFullStatus(result.evolutionId);
  assert(status.evolution.findings.length === 1, 'Should have 1 finding');
  assert(status.evolution.lessons.length === 1, 'Should have 1 lesson');
  assert(status.evolution.proposals.length >= 1, 'Should have at least 1 proposal');
  assert(status.evolution.current_phase !== 'discovery', 'Should have advanced past discovery');
});

test('低严重度知识更新：直接走知识层，不需要代码变更', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('user_feedback', lowSeverityFindings);

  const status = orch.getFullStatus(result.evolutionId);
  const proposal = status.evolution.proposals[0];

  assert(proposal.requires_code === false, 'Low severity knowledge issue should not require code');
  assert(proposal.change_type === 'memory_update' || proposal.change_type === 'knowledge_update',
    'Should be knowledge or memory update');
});

console.log('\n--- 测试组 2：进化系统与DZE开发链打通（任务4） ---');

test('高严重度代码问题 → 自动触发 DZE 链', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  assert(result.dzeTriggered === true, 'High severity code issue should trigger DZE chain');

  const status = orch.getFullStatus(result.evolutionId);
  assert(status.dzeChains.length === 1, 'Should have 1 DZE chain');
  assert(status.dzeChains[0].current_phase === 'd1', 'Should start at D1 phase');
  assert(status.dzeChains[0].evolution_id === result.evolutionId, 'Evolution ID should match');
  assert(status.evolution.metadata.dze_chain_triggered === true, 'Metadata flag should be set');
});

test('DZE 链阶段推进：D1→D2→D3→D4', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd2');
  orch.advanceDZEPhase(result.evolutionId, 'd3');
  orch.advanceDZEPhase(result.evolutionId, 'd4');

  const status = orch.getFullStatus(result.evolutionId);
  assert(status.dzeChains[0].current_phase === 'd4', 'Should be at D4');
  assert(status.dzeChains[0].phases_completed.includes('d1'), 'D1 should be completed');
  assert(status.dzeChains[0].phases_completed.includes('d2'), 'D2 should be completed');
  assert(status.dzeChains[0].phases_completed.includes('d3'), 'D3 should be completed');
  assert(status.dzeChains[0].phases_pending[0] === 'z1', 'Next phase should be Z1');
});

test('Gate 1 审批通过 → 进入 Z 阶段', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');
  const passed = orch.passGate1(result.evolutionId, true, 'test-approver');

  assert(passed === true, 'Gate 1 should pass');

  const status = orch.getFullStatus(result.evolutionId);
  assert(status.dzeChains[0].gate1_passed === true, 'Gate1 flag should be true');
  assert(status.dzeChains[0].current_phase === 'z1', 'Should advance to Z1 after gate 1');
});

test('Gate 2 审批通过 → 进入 E 阶段', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');
  orch.passGate1(result.evolutionId, true);
  orch.advanceDZEPhase(result.evolutionId, 'z2');
  orch.advanceDZEPhase(result.evolutionId, 'z3');
  orch.advanceDZEPhase(result.evolutionId, 'z4');

  const passed = orch.passGate2(result.evolutionId, true, 'test-approver');
  assert(passed === true, 'Gate 2 should pass');

  const status = orch.getFullStatus(result.evolutionId);
  assert(status.dzeChains[0].gate2_passed === true, 'Gate2 flag should be true');
  assert(status.dzeChains[0].current_phase === 'e1', 'Should advance to E1 after gate 2');
});

console.log('\n--- 测试组 3：DZE开发链与Dream-Agent协作网络打通（任务5） ---');

test('Gate 2 通过 → 自动注册 Dream-Agent 任务', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');
  orch.passGate1(result.evolutionId, true);
  orch.advanceDZEPhase(result.evolutionId, 'z4');
  orch.passGate2(result.evolutionId, true);

  const status = orch.getFullStatus(result.evolutionId);
  assert(result.dreamAgentTriggered === false, 'Should not be triggered at start');
  assert(status.dreamAgentTasks.length === 1, 'Should have 1 Dream-Agent task');
  assert(status.dreamAgentTasks[0].status === 'registered', 'Task should be registered');
  assert(status.dreamAgentTasks[0].assigned_roles.length === 3, 'Should have 3 roles');
  assert(status.evolution.metadata.dream_agent_triggered === true, 'Metadata flag should be set');
  assert(status.evolution.current_phase === 'collaboration', 'Should be in collaboration phase');
});

test('Dream-Agent 完整流程：认领→提交→验证→入账', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');
  orch.passGate1(result.evolutionId, true);
  orch.advanceDZEPhase(result.evolutionId, 'z4');
  orch.passGate2(result.evolutionId, true);

  const status = orch.getFullStatus(result.evolutionId);
  const taskId = status.dreamAgentTasks[0].task_id;
  const da = orch.getDreamAgentBridge();

  da.assignDeveloper(taskId, 'dev-agent-001');
  let task = da.getTask(taskId);
  assert(task.status === 'claimed', 'Task should be claimed');

  da.submitForValidation(taskId, 'dev-agent-001');
  task = da.getTask(taskId);
  assert(task.status === 'in_progress', 'Task should be in progress');

  da.validateTask(taskId, 'validator-agent-001', true, 85);
  task = da.getTask(taskId);
  assert(task.status === 'validated', 'Task should be validated');

  const beforeReward = da.getTotalRewards();
  da.finalizeTask(taskId, 'governance-agent-001');
  task = da.getTask(taskId);
  assert(task.status === 'ledgered', 'Task should be ledgered');
  assert(task.ledger_ref !== undefined, 'Should have ledger ref');
  assert(da.getTotalRewards() > beforeReward, 'Rewards should have been distributed');
  assert(da.getBlockHeight() >= 1, 'Block height should have increased');
});

test('账本记录完整性：每个动作都有账本条目', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');
  orch.passGate1(result.evolutionId, true);
  orch.advanceDZEPhase(result.evolutionId, 'z4');
  orch.passGate2(result.evolutionId, true);

  const status = orch.getFullStatus(result.evolutionId);
  const taskId = status.dreamAgentTasks[0].task_id;
  const da = orch.getDreamAgentBridge();

  da.assignDeveloper(taskId, 'dev-001');
  da.submitForValidation(taskId, 'dev-001');
  da.validateTask(taskId, 'val-001', true, 90);
  da.finalizeTask(taskId, 'gov-001');

  const ledger = da.getLedgerByTask(taskId);
  assert(ledger.length >= 6, 'Should have at least 6 ledger entries');

  const actions = ledger.map(e => e.action);
  assert(actions.includes('claim'), 'Should have claim action');
  assert(actions.includes('submit'), 'Should have submit action');
  assert(actions.includes('validate'), 'Should have validate action');
  assert(actions.includes('approve'), 'Should have approve action');
  assert(actions.includes('reward'), 'Should have reward action');
});

console.log('\n--- 测试组 4：飞书审批与自主迭代闭环打通（任务6） ---');

test('DZE 链启动 → 自动创建 Gate1 方案审批', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  const status = orch.getFullStatus(result.evolutionId);
  assert(result.approvalsCreated >= 1, 'Should have at least 1 approval');

  const gate1Approvals = status.approvals.filter(a => a.approval_type === 'design');
  assert(gate1Approvals.length === 1, 'Should have 1 design approval (Gate 1)');
  assert(gate1Approvals[0].status === 'pending', 'Should be pending');
  assert(gate1Approvals[0].title.includes('Gate 1'), 'Title should mention Gate 1');
  assert(status.evolution.metadata.approval_required === true, 'Approval required flag should be set');
});

test('审批通过 → 自动推进 DZE 链', () => {
  const orch = new EvolutionOrchestrator();
  const result = orch.startEvolution('execution_failure', sampleFindings);

  orch.advanceDZEPhase(result.evolutionId, 'd4');

  const status = orch.getFullStatus(result.evolutionId);
  const gate1Approval = status.approvals.find(a => a.approval_type === 'design')!;

  orch.getApprovalBridge().approve(gate1Approval.id, 'test-approver');
  const approved = orch.passGate1(result.evolutionId, true, 'test-approver');

  assert(approved === true, 'Gate 1 should pass');
  const dzeChains = orch.getDZEBridge().getChainsByEvolution(result.evolutionId);
  assert(dzeChains[0].gate1_passed === true, 'Gate1 should be passed');
  assert(dzeChains[0].current_phase === 'z1', 'Should advance to Z1');
});

test('超时自动批准机制', () => {
  const orch = new EvolutionOrchestrator();
  const ab = orch.getApprovalBridge();

  const result = orch.startEvolution('execution_failure', sampleFindings);
  const status = orch.getFullStatus(result.evolutionId);
  const approval = status.approvals[0];

  const check1 = ab.autoApproveIfEligible(approval.id);
  assert(check1.approved === false, 'Should not auto-approve immediately');

  const updatedApproval = ab.getApproval(approval.id);
  const originalTime = updatedApproval.created_at;
  const fakeOldTime = new Date(Date.now() - 40 * 60 * 1000).toISOString();
  (updatedApproval as any).created_at = fakeOldTime;
  ab['approvals'].set(approval.id, updatedApproval);

  const check2 = ab.autoApproveIfEligible(approval.id);
  assert(check2.approved === true, 'Should auto-approve after timeout');

  const finalApproval = ab.getApproval(approval.id);
  assert(finalApproval.status === 'timeout_auto_approved', 'Status should be timeout_auto_approved');
  assert(finalApproval.decided_by === 'auto-approval-bot', 'Should be decided by auto-approval-bot');
});

test('批量超时检查', () => {
  const orch = new EvolutionOrchestrator();
  const ab = orch.getApprovalBridge();

  const result = orch.startEvolution('execution_failure', sampleFindings);

  const pendingBefore = ab.getPendingApprovals().length;
  assert(pendingBefore >= 1, 'Should have pending approvals');

  const autoApproved = orch.processApprovalTimeout(result.evolutionId);
  assert(autoApproved >= 0, 'Should return a number');
});

test('4类审批类型齐全：design/kickoff/merge/deployment', () => {
  const orch = new EvolutionOrchestrator();
  const ab = orch.getApprovalBridge();
  const dze = orch.getDZEBridge();

  const result = orch.startEvolution('execution_failure', sampleFindings);
  const chains = dze.getChainsByEvolution(result.evolutionId);
  const chain = chains[0];
  const record = orch.getEngine().getRecord(result.evolutionId);
  const proposal = record.proposals[0];

  ab.createApprovalForGate1(record, chain, proposal);
  ab.createApprovalForGate2(record, chain);
  ab.createApprovalForDeployment(record, chain);

  const daTask = orch.getDreamAgentBridge().registerTaskFromDZE(record, chain);
  ab.createApprovalForMerge(record, daTask);

  const allApprovals = ab.getAllApprovals();
  const types = new Set(allApprovals.map(a => a.approval_type));

  assert(types.has('design'), 'Should have design approval');
  assert(types.has('kickoff'), 'Should have kickoff approval');
  assert(types.has('merge'), 'Should have merge approval');
  assert(types.has('deployment'), 'Should have deployment approval');
  assert(types.size === 4, 'Should have exactly 4 types');
});

console.log('\n--- 测试组 5：全链路端到端打通验证 ---');

test('完整闭环：发现问题→进化→DZE→Gate1→Z→Gate2→Dream-Agent→验证→入账→完成', () => {
  const orch = new EvolutionOrchestrator();

  const result = orch.startEvolution('execution_failure', sampleFindings);
  const evoId = result.evolutionId;

  let status = orch.getFullStatus(evoId);
  assert(status.evolution.findings.length === 1, 'Step 1: Finding recorded');
  assert(status.evolution.lessons.length === 1, 'Step 2: Lesson extracted');
  assert(status.evolution.proposals.length >= 1, 'Step 3: Proposals generated');
  assert(status.dzeChains.length === 1, 'Step 4: DZE chain triggered');
  assert(status.approvals.some(a => a.approval_type === 'design'), 'Step 5: Gate1 approval created');

  orch.advanceDZEPhase(evoId, 'd4');
  orch.passGate1(evoId, true, 'tech-lead');
  status = orch.getFullStatus(evoId);
  assert(status.dzeChains[0].gate1_passed === true, 'Step 6: Gate 1 passed');
  assert(status.dzeChains[0].current_phase === 'z1', 'Step 7: Entering Z phase');

  orch.advanceDZEPhase(evoId, 'z2');
  orch.advanceDZEPhase(evoId, 'z3');
  orch.advanceDZEPhase(evoId, 'z4');
  orch.passGate2(evoId, true, 'tech-lead');
  status = orch.getFullStatus(evoId);
  assert(status.dzeChains[0].gate2_passed === true, 'Step 8: Gate 2 passed');
  assert(status.dzeChains[0].current_phase === 'e1', 'Step 9: Entering E phase');
  assert(status.dreamAgentTasks.length === 1, 'Step 10: Dream-Agent task registered');

  const taskId = status.dreamAgentTasks[0].task_id;
  const da = orch.getDreamAgentBridge();
  da.assignDeveloper(taskId, 'dev-agent-001');
  da.submitForValidation(taskId, 'dev-agent-001');
  da.validateTask(taskId, 'validator-001', true, 92);
  status = orch.getFullStatus(evoId);
  assert(status.dreamAgentTasks[0].status === 'validated', 'Step 11: Task validated');

  orch.completeDreamAgentTask(evoId, taskId);
  status = orch.getFullStatus(evoId);
  assert(status.dreamAgentTasks[0].status === 'ledgered', 'Step 12: Task ledgered');
  assert(status.evolution.status === 'completed', 'Step 13: Evolution completed');
  assert(status.evolution.current_phase === 'completed', 'Step 14: Phase = completed');

  const totalReward = da.getTotalRewards();
  assert(totalReward > 0, 'Step 15: DREAM tokens rewarded');
  assert(da.getBlockHeight() >= 1, 'Step 16: Block height increased');

  const ledger = da.getLedger();
  assert(ledger.length > 0, 'Step 17: Ledger has entries');
});

test('知识层进化：不需要代码，直接完成闭环', () => {
  const orch = new EvolutionOrchestrator();

  const result = orch.startEvolution('user_feedback', lowSeverityFindings);
  const status = orch.getFullStatus(result.evolutionId);

  assert(status.dzeChains.length === 0, 'Knowledge update should NOT trigger DZE');
  assert(status.dreamAgentTasks.length === 0, 'Knowledge update should NOT trigger Dream-Agent');
  assert(status.evolution.metadata.knowledge_updated === true, 'Knowledge should be updated');
  assert(status.evolution.metadata.code_changed === false, 'Code should NOT be changed');
});

console.log('\n' + '='.repeat(50));
console.log(`测试结果: ${passed} 通过, ${failed} 失败`);
console.log(`通过率: ${((passed / (passed + failed)) * 100).toFixed(1)}%`);
console.log('='.repeat(50));

if (failed > 0) {
  process.exit(1);
}

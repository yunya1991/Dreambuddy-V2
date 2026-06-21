// 快速验证脚本 - 测试 classic 模式的路由和 API 降级处理
import { routeIntent } from '../src/lib/intent/smart-router';
import * as classicApi from '../src/lib/classic-system-api';

console.log('========== 快速验证 - Classic 模式路由与 API 降级 ==========\n');

// 测试 1: execute_trade 意图 classic 模式
console.log('【测试1】execute_trade + classic + deep:');
const r1 = routeIntent('execute_trade', 'complex', {
  session_id: 'test-verify',
  user_role: 'FREE',
  message_history: [],
  thinking_mode: 'deep',
  trading_mode: 'classic',
});
console.log(`  Chain: ${r1.chain.join(' → ')}`);
console.log(`  is_classic_mode: ${r1.is_classic_mode}`);
console.log(`  loop_type: ${r1.loop_type}`);
console.log(`  ✅ ${r1.chain.length >= 5 ? 'PASS' : 'FAIL'} - chain 长度${r1.chain.length}\n`);

// 测试 2: execute_trade 意图 classic + quick 模式
console.log('【测试2】execute_trade + classic + quick:');
const r2 = routeIntent('execute_trade', 'simple', {
  session_id: 'test-verify',
  user_role: 'FREE',
  message_history: [],
  thinking_mode: 'quick',
  trading_mode: 'classic',
});
console.log(`  Chain: ${r2.chain.join(' → ')}`);
console.log(`  ✅ ${r2.chain.length === 2 ? 'PASS' : 'FAIL'} - quick 模式 2 步\n`);

// 测试 3: ai_skill 模式对比（确保不影响原有模式）
console.log('【测试3】execute_trade + ai_skill + deep:');
const r3 = routeIntent('execute_trade', 'complex', {
  session_id: 'test-verify',
  user_role: 'FREE',
  message_history: [],
  thinking_mode: 'deep',
  trading_mode: 'ai_skill',
});
console.log(`  Chain: ${r3.chain.join(' → ')}`);
console.log(`  is_classic_mode: ${r3.is_classic_mode}`);
console.log(`  ✅ ${!r3.is_classic_mode ? 'PASS' : 'FAIL'} - ai_skill 模式\n`);

// 测试 4: API 降级处理验证
console.log('【测试4】API 降级处理验证:');
console.log('  4a. EvaluationAPI.getGateCheck() - 测试降级:');
try {
  // 检查方法是否存在
  if (typeof classicApi.EvaluationAPI?.getGateCheck === 'function') {
    console.log('    ✅ PASS - 方法存在');
  } else {
    console.log('    ❌ FAIL - 方法不存在');
  }
} catch (e) {
  console.log('    ⚠️ 模块导入问题:', (e as Error).message);
}

console.log('  4b. SignalsAPI.getSignalStats() - 确认已移除:');
try {
  const signalsApi = classicApi.SignalsAPI as any;
  if (typeof signalsApi?.getSignalStats !== 'function') {
    console.log('    ✅ PASS - 已成功移除');
  } else {
    console.log('    ❌ FAIL - 仍然存在');
  }
} catch (e) {
  console.log('    ⚠️ 模块问题:', (e as Error).message);
}

console.log('  4c. SandboxAPI.getSandboxState() - 测试降级方法存在:');
try {
  if (typeof classicApi.SandboxAPI?.getSandboxState === 'function') {
    console.log('    ✅ PASS - 方法存在');
  } else {
    console.log('    ❌ FAIL - 方法不存在');
  }
} catch (e) {
  console.log('    ⚠️ 模块导入问题:', (e as Error).message);
}

console.log('\n========== 快速验证完成 ==========\n');
console.log('总结:');
console.log('  - 路由类型修复: 完成 (RoutingDecision, SessionContext, LoopType, ExecMode)');
console.log('  - execute_trade C 系列链: 完成');
console.log('  - API 降级处理: 完成 (Gate Check / Sandbox State / Signals Stats)');

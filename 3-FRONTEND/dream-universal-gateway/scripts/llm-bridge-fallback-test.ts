/**
 * llm-bridge 多凭证 402/401 自动降级测试
 *
 * 验证 callLLM 降级逻辑：
 *   场景1: 凭证A 402(余额不足) → 自动降级到凭证B 200
 *   场景2: 凭证A 401(认证失败) → 降级
 *   场景3: 凭证A 500(服务端错误) → 不降级，直接抛出
 *   场景4: 所有凭证(含 .env fallback)都 402 → 抛出最后错误
 *   场景5: 凭证A 直接成功 → 不降级（仅1次调用）
 *
 * 跑法：cd 3-FRONTEND/dream-universal-gateway && npx tsx scripts/llm-bridge-fallback-test.ts
 * 隔离：使用现有 User uid=Ue3DB8tM49Y（无 LLM 配置），每场景后清理
 */
import 'dotenv/config';
import { prisma } from '@/lib/prisma';
import { encrypt } from '@/lib/encryption';
import { callLLM } from '@/lib/orchestration/llm-bridge';

const TEST_UID = 'Ue3DB8tM49Y';

// ============ mock fetch ============
interface MockRule { match: string; status: number; body?: unknown }
let fetchLog: Array<{ key: string; status: number }> = [];
let mockRules: MockRule[] = [];
let forceStatus: number | null = null;
const realFetch = globalThis.fetch;

globalThis.fetch = (async (_url: unknown, init: unknown) => {
  const headers = ((init as { headers?: Record<string, string> })?.headers) || {};
  const auth = String(headers.Authorization || headers['x-api-key'] || '');
  const key = auth.replace(/^Bearer\s+/, '');
  let status = 200;
  let body: unknown = { choices: [{ message: { content: 'OK::' + key } }], usage: { total_tokens: 10 } };
  if (forceStatus !== null) {
    status = forceStatus;
    body = { error: { message: 'forced-' + forceStatus } };
  } else {
    for (const r of mockRules) {
      if (key.includes(r.match)) {
        status = r.status;
        body = r.body !== undefined ? r.body : (status === 200 ? body : { error: { message: 'mock-' + status } });
        break;
      }
    }
  }
  fetchLog.push({ key, status });
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}) as typeof fetch;

// ============ 测试配置 ============
async function makeConfig(provider: string, apiKey: string, model: string, createdAt: Date, label: string) {
  const enc = encrypt(JSON.stringify({ apiKey, model }));
  return prisma.apiConfig.create({
    data: {
      uid: TEST_UID,
      category: 'LLM',
      provider,
      label,
      encryptedData: enc.encryptedData,
      iv: enc.iv,
      authTag: enc.authTag,
      isVerified: true,
      baseUrl: provider === 'dashscope' ? 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1' : null,
      createdAt,
    },
  });
}

async function cleanup() {
  await prisma.apiConfig.deleteMany({ where: { uid: TEST_UID, category: 'LLM' } });
}

function resetMock() {
  fetchLog = [];
  mockRules = [];
  forceStatus = null;
}

// ============ 断言 ============
let passed = 0, failed = 0;
function assert(cond: boolean, msg: string) {
  if (cond) { passed++; console.log('   ✅ ' + msg); }
  else { failed++; console.log('   ❌ ' + msg); }
}

async function main() {
  console.log('='.repeat(60));
  console.log('llm-bridge 多凭证 402/401 自动降级测试');
  console.log('='.repeat(60));
  await cleanup();
  const now = Date.now();

  // ---- 场景1: 402 降级 ----
  console.log('\n[场景1] 凭证A 402(余额不足) → 自动降级到凭证B 200');
  resetMock();
  await makeConfig('deepseek', 'sk-AAA-402', 'deepseek-chat', new Date(now), 'test-A-402');
  await makeConfig('dashscope', 'sk-BBB-good', 'qwen3.8-max', new Date(now - 1000), 'test-B-good');
  mockRules = [
    { match: 'sk-AAA-402', status: 402 },
    { match: 'sk-BBB-good', status: 200 },
  ];
  const r1 = await callLLM({ prompt: 'hi' }, TEST_UID);
  assert(fetchLog.length === 2, `fetch 调用 2 次（实际 ${fetchLog.length}）`);
  assert(fetchLog[0]?.status === 402, '第1次 = 402');
  assert(fetchLog[1]?.status === 200, '第2次降级后 = 200');
  assert(r1.content.includes('sk-BBB-good'), `最终用凭证B成功（content=${r1.content}）`);
  await cleanup();

  // ---- 场景2: 401 降级 ----
  console.log('\n[场景2] 凭证A 401(认证失败) → 降级');
  resetMock();
  await makeConfig('deepseek', 'sk-AAA-401', 'deepseek-chat', new Date(now), 'test-A-401');
  await makeConfig('dashscope', 'sk-BBB-ok2', 'qwen3.8-max', new Date(now - 1000), 'test-B-ok2');
  mockRules = [
    { match: 'sk-AAA-401', status: 401 },
    { match: 'sk-BBB-ok2', status: 200 },
  ];
  const r2 = await callLLM({ prompt: 'hi' }, TEST_UID);
  assert(fetchLog.length === 2, `401 触发降级，fetch 2 次（实际 ${fetchLog.length}）`);
  assert(r2.content.includes('sk-BBB-ok2'), '降级到凭证B成功');
  await cleanup();

  // ---- 场景3: 500 不降级 ----
  console.log('\n[场景3] 凭证A 500(服务端错误) → 不降级，直接抛出');
  resetMock();
  await makeConfig('deepseek', 'sk-AAA-500', 'deepseek-chat', new Date(now), 'test-A-500');
  await makeConfig('dashscope', 'sk-BBB-ok3', 'qwen3.8-max', new Date(now - 1000), 'test-B-ok3');
  mockRules = [
    { match: 'sk-AAA-500', status: 500 },
    { match: 'sk-BBB-ok3', status: 200 },
  ];
  let threw3 = false, msg3 = '';
  try { await callLLM({ prompt: 'hi' }, TEST_UID); }
  catch (e) { threw3 = true; msg3 = e instanceof Error ? e.message : String(e); }
  assert(threw3, '500 直接抛出（未降级）');
  assert(msg3.includes('500'), `错误含 500: ${msg3.slice(0, 70)}`);
  assert(fetchLog.length === 1, `只调用 1 次（实际 ${fetchLog.length}）`);
  await cleanup();

  // ---- 场景4: 全部 402（含 fallback）→ 抛最后错误 ----
  console.log('\n[场景4] 所有凭证(含 .env fallback)都 402 → 抛出最后错误');
  resetMock();
  await makeConfig('deepseek', 'sk-ALL-402a', 'deepseek-chat', new Date(now), 'all-402a');
  await makeConfig('dashscope', 'sk-ALL-402b', 'qwen3.8-max', new Date(now - 1000), 'all-402b');
  forceStatus = 402; // 所有调用强制 402
  let threw4 = false, msg4 = '';
  try { await callLLM({ prompt: 'hi' }, TEST_UID); }
  catch (e) { threw4 = true; msg4 = e instanceof Error ? e.message : String(e); }
  assert(threw4, '全部失败后抛出');
  assert(msg4.includes('402'), `错误含 402: ${msg4.slice(0, 70)}`);
  console.log(`   ℹ️  fetch 共调用 ${fetchLog.length} 次（2 测试凭证 + .env fallback 兜底）`);
  assert(fetchLog.length >= 2, `尝试了所有凭证（${fetchLog.length} 次）`);
  await cleanup();

  // ---- 场景5: 第一成功不降级 ----
  console.log('\n[场景5] 凭证A 直接成功 → 不降级（仅1次调用）');
  resetMock();
  await makeConfig('dashscope', 'sk-FIRST-ok', 'qwen3.8-max', new Date(now), 'first-ok');
  mockRules = [{ match: 'sk-FIRST-ok', status: 200 }];
  const r5 = await callLLM({ prompt: 'hi' }, TEST_UID);
  assert(fetchLog.length === 1, `第一成功，仅调用 1 次（实际 ${fetchLog.length}）`);
  assert(r5.content.includes('sk-FIRST-ok'), '用凭证A成功');
  await cleanup();

  // ---- 汇总 ----
  console.log('\n' + '='.repeat(60));
  console.log(`测试结果: ${passed} 通过, ${failed} 失败`);
  console.log('='.repeat(60));

  globalThis.fetch = realFetch;
  await prisma.$disconnect();
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(async e => {
  console.error('FATAL', e);
  try { await cleanup(); } catch { /* ignore */ }
  globalThis.fetch = realFetch;
  await prisma.$disconnect();
  process.exit(1);
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const http = require('node:http');
const { createApp } = require('../src/app');
const { SqliteOrderRepository } = require('../src/store');
const { auditSkill } = require('../src/audit');
const { normalizeCogstewardInput, buildCogstewardReport } = require('../src/cogsteward');
const { base64UrlEncode, base64UrlDecode } = require('../src/alipay');

const VALID_SKILL_MD = `---
name: demo-audit-skill
slug: demo-audit-skill
displayName: 示例技能
version: 1.0.0
description: 当用户需要验证体检链路时使用本示例技能，覆盖结构、示例与限制。
summary: 用于测试的示例技能
license: MIT
---

# 示例技能

这是一个用于测试体检服务的示例技能文档，正文长度需要超过两百个字符才能通过长度检查。
它描述触发条件、输入输出、执行步骤与错误处理，确保 Agent 能按步骤执行。
当用户请求示例能力时使用本技能；不使用于无关场景。
错误处理：遇到缺失参数时先向用户确认，再执行。

## 使用

按示例命令运行。

## 示例

\`\`\`bash
python3 scripts/demo.py
\`\`\`

## 限制

仅用于测试。

## FAQ

Q: 为什么需要这份文档？
A: 用于验证体检链路。
`;

function buildConfig() {
  const { privateKey } = crypto.generateKeyPairSync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: { type: 'pkcs1', format: 'pem' },
    privateKeyEncoding: { type: 'pkcs1', format: 'pem' }
  });
  return {
    port: 0,
    resourceId: '/api/audit',
    price: '0.99',
    currency: 'CNY',
    goodsName: 'Skill 上架体检报告',
    sellerName: 'DreamBuddy',
    payWindowMinutes: 30,
    appId: '2021000000000000',
    sellerId: '2088000000000000',
    serviceId: 'api_mock_service_id',
    gateway: 'https://openapi-sandbox.dl.alipaydev.com/gateway.do',
    privateKey,
    alipayPublicKey: '',
    sandboxExact: true,
    cogsteward: {
      resourceId: '/api/cogsteward',
      price: '0.99',
      goodsName: '认知管家·工作区体检报告',
      serviceId: 'api_mock_service_id'
    }
  };
}

function createFakeAlipay(repository, overrides = {}) {
  const calls = { verify: 0, confirm: 0 };
  return {
    calls,
    async verifyPayment({ tradeNo }) {
      calls.verify += 1;
      const pending = repository.db.prepare('SELECT * FROM orders ORDER BY id DESC LIMIT 1').get();
      return {
        code: '10000',
        msg: 'Success',
        active: true,
        tradeNo,
        outTradeNo: pending ? pending.out_trade_no : '',
        amount: pending ? pending.amount : '0.99',
        resourceId: pending ? pending.resource_id : '/api/audit',
        ...overrides
      };
    },
    async confirmFulfillment() {
      calls.confirm += 1;
      return { ok: true };
    }
  };
}

async function startTestServer(overrides) {
  const config = overrides?.config || buildConfig();
  const repository = new SqliteOrderRepository(':memory:');
  const alipay = overrides?.alipay ? overrides.alipay(repository) : createFakeAlipay(repository);
  const app = createApp({ config, repository, alipay });
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const base = `http://127.0.0.1:${server.address().port}`;
  return { server, base, repository, alipay, config };
}

function buildProof(tradeNo) {
  return base64UrlEncode(
    JSON.stringify({
      protocol: { payment_proof: 'proof-demo-0001', trade_no: tradeNo },
      method: { client_session: 'session-demo' }
    })
  );
}

test('未付款返回 402 与 Payment-Needed 账单，且已持久化订单', async () => {
  const { server, base, repository } = await startTestServer();
  try {
    const res = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    assert.strictEqual(res.status, 402);
    const header = res.headers.get('payment-needed');
    assert.ok(header, '缺少 Payment-Needed 响应头');
    const bill = JSON.parse(base64UrlDecode(header));
    assert.strictEqual(bill.protocol.amount, '0.99');
    assert.strictEqual(bill.protocol.currency, 'CNY');
    assert.strictEqual(bill.protocol.resource_id, '/api/audit');
    assert.ok(bill.protocol.seller_signature);
    assert.strictEqual(bill.protocol.seller_sign_type, 'RSA2');
    assert.strictEqual(bill.method.service_id, 'api_mock_service_id');
    assert.ok(/\+08:00$/.test(bill.protocol.pay_before), 'pay_before 必须带 +08:00 时区');

    const order = repository.findByOutTradeNo(bill.protocol.out_trade_no);
    assert.ok(order, '订单未持久化');
    assert.strictEqual(order.amount, '0.99');
    assert.strictEqual(order.orderStatus, 'PENDING_PAYMENT');
  } finally {
    server.close();
  }
});

test('有效 Payment-Proof 交付报告并幂等履约', async () => {
  const { server, base, repository, alipay } = await startTestServer();
  try {
    const first = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    const outTradeNo = JSON.parse(base64UrlDecode(first.headers.get('payment-needed'))).protocol.out_trade_no;
    const tradeNo = '2026111922001400000000000001';

    const paid = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    assert.strictEqual(paid.status, 200);
    const payload = await paid.json();
    assert.strictEqual(payload.resource_id, '/api/audit');
    assert.strictEqual(payload.out_trade_no, outTradeNo);
    assert.strictEqual(payload.fulfillment_confirmed, true);
    assert.strictEqual(payload.content.verdict, 'pass');
    const validation = JSON.parse(base64UrlDecode(paid.headers.get('payment-validation')));
    assert.strictEqual(validation.validated, true);
    assert.strictEqual(validation.trade_no, tradeNo);

    const again = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    assert.strictEqual(again.status, 200);
    const againPayload = await again.json();
    assert.strictEqual(againPayload.already_fulfilled, true);
    assert.strictEqual(againPayload.content.verdict, 'pass');
    assert.strictEqual(alipay.calls.confirm, 1, '同一订单不得重复履约确认');
    assert.strictEqual(repository.stats().fulfilled, 1);
  } finally {
    server.close();
  }
});

test('金额不一致时拒绝交付并重新下发 402', async () => {
  const { server, base } = await startTestServer({
    alipay: (repo) => createFakeAlipay(repo, { amount: '9.99' })
  });
  try {
    await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    const res = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof('2026111922001400000000000002') },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    assert.strictEqual(res.status, 402);
    assert.ok(res.headers.get('payment-needed'));
  } finally {
    server.close();
  }
});

test('无法解析的 Payment-Proof 返回 402', async () => {
  const { server, base } = await startTestServer();
  try {
    const res = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': 'not-a-valid-proof' },
      body: JSON.stringify({ skill_md: VALID_SKILL_MD })
    });
    assert.strictEqual(res.status, 402);
  } finally {
    server.close();
  }
});

test('体检：合法文档通过，缺 slug 失败，付费意图缺 402 协议失败', () => {
  assert.strictEqual(auditSkill({ skill_md: VALID_SKILL_MD }).verdict, 'pass');

  const noSlug = auditSkill({ skill_md: VALID_SKILL_MD.replace('slug: demo-audit-skill\n', '') });
  assert.strictEqual(noSlug.verdict, 'fail');
  assert.ok(noSlug.checks.some((c) => c.id === 'FM001' && c.status === 'fail'));

  const paidWithoutBackend = auditSkill({
    skill_md: VALID_SKILL_MD.replace('示例技能', '付费技能').replace('摘要', '付费'),
    target: 'pay'
  });
  assert.strictEqual(paidWithoutBackend.verdict, 'fail');
  assert.ok(paidWithoutBackend.checks.some((c) => c.id === 'PAY001' && c.status === 'fail'));
});

test('体检：敏感文件与密钥泄露判失败', () => {
  const report = auditSkill({
    skill_md: `${VALID_SKILL_MD}\n连接串 skh_0123456789abcdef0123456789abcdef\n`,
    files: [{ path: '.env', size: 10 }, { path: 'SKILL.md', size: 1024 }]
  });
  assert.strictEqual(report.verdict, 'fail');
  assert.ok(report.checks.some((c) => c.id === 'SEC001' && c.status === 'fail'));
  assert.ok(report.checks.some((c) => c.id === 'SEC003' && c.status === 'fail'));
});

const COGSTEWARD_BODY = {
  metrics: {
    broken_links: 6,
    orphan_files: 25,
    index_drift: 0,
    skill_conflicts: 1,
    stale_sessions: 0,
    pending_backlog: 60
  },
  inventory: { documents: 120, skills: 40, sessions: 30 },
  mode: 'dev'
};

test('认知管家：未付款返回 402 账单，金额 0.99 且 resource_id 正确', async () => {
  const { server, base, repository } = await startTestServer();
  try {
    const res = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(COGSTEWARD_BODY)
    });
    assert.strictEqual(res.status, 402);
    const payload = await res.json();
    assert.strictEqual(payload.amount, '0.99');
    assert.strictEqual(payload.resource_id, '/api/cogsteward');
    const bill = JSON.parse(base64UrlDecode(res.headers.get('payment-needed')));
    assert.strictEqual(bill.protocol.resource_id, '/api/cogsteward');
    assert.strictEqual(bill.protocol.amount, '0.99');
    assert.ok(repository.findByOutTradeNo(payload.out_trade_no));
  } finally {
    server.close();
  }
});

test('认知管家：付款后交付报告并可幂等重放', async () => {
  const { server, base, repository } = await startTestServer();
  try {
    const first = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(COGSTEWARD_BODY)
    });
    const outTradeNo = (await first.json()).out_trade_no;
    const tradeNo = '2026112022001400000000000011';

    const paid = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body: JSON.stringify(COGSTEWARD_BODY)
    });
    assert.strictEqual(paid.status, 200);
    const body = await paid.json();
    assert.strictEqual(body.resource_id, '/api/cogsteward');
    assert.strictEqual(body.out_trade_no, outTradeNo);
    assert.strictEqual(body.fulfillment_confirmed, true);
    assert.strictEqual(body.content.command, 'cogsteward-report');
    assert.match(body.content.grade, /^[ABCD]$/);
    assert.strictEqual(body.content.findings[0].id, 'broken_links', 'P0 断链应排在首位');
    assert.strictEqual(body.content.ratios.broken_link_rate.value, 5);

    const again = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body: JSON.stringify(COGSTEWARD_BODY)
    });
    const againBody = await again.json();
    assert.strictEqual(againBody.already_fulfilled, true);
    assert.strictEqual(repository.stats().fulfilled, 1);
  } finally {
    server.close();
  }
});

test('认知管家：缺可评估数据或字段类型非法返回 400', async () => {
  const { server, base } = await startTestServer();
  try {
    const empty = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'dev' })
    });
    assert.strictEqual(empty.status, 400);

    const badType = await fetch(`${base}/api/cogsteward`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ metrics: { broken_links: -1 } })
    });
    assert.strictEqual(badType.status, 400);
  } finally {
    server.close();
  }
});

test('认知管家：干净工作区判 A，含异常时按优先级给出建议', () => {
  const clean = buildCogstewardReport(
    normalizeCogstewardInput({ metrics: { broken_links: 0, orphan_files: 0, index_drift: 0, skill_conflicts: 0 } })
  );
  assert.strictEqual(clean.grade, 'A');
  assert.strictEqual(clean.health, 'good');
  assert.strictEqual(clean.findings.length, 0);

  const messy = buildCogstewardReport(normalizeCogstewardInput(COGSTEWARD_BODY));
  assert.strictEqual(messy.health, 'poor');
  assert.strictEqual(messy.findings.length, 3);
  assert.strictEqual(messy.findings[0].priority, 'P0');
  assert.ok(messy.score < 80);

  const noDenominator = buildCogstewardReport(normalizeCogstewardInput({ metrics: { broken_links: 0 } }));
  assert.strictEqual(noDenominator.ratios.broken_link_rate, null);
});

test('认知管家：九项指标含代码-文档三项，按优先级排序', () => {
  const input = normalizeCogstewardInput({
    metrics: {
      broken_links: 0,
      orphan_files: 0,
      index_drift: 0,
      skill_conflicts: 0,
      stale_sessions: 0,
      pending_backlog: 0,
      anchor_out_of_range: 2,
      code_without_doc: 6,
      doc_drift: 4
    },
    inventory: { documents: 120, skills: 40 }
  });
  const report = buildCogstewardReport(input);
  assert.strictEqual(report.benchmarks.length, 9);
  assert.strictEqual(report.health, 'poor');
  assert.strictEqual(report.total_findings, 3);
  assert.strictEqual(report.findings[0].id, 'code_without_doc');
  assert.strictEqual(report.findings[0].priority, 'P0');
  assert.strictEqual(report.ratios.anchor_error_rate.value, 1.67);
  assert.strictEqual(report.score, 80);
});

test('认知管家：新增指标拒绝负数', () => {
  const input = normalizeCogstewardInput({ metrics: { anchor_out_of_range: -1 } });
  assert.ok(input.error && input.error.includes('anchor_out_of_range'));
});

test('数据服务：付款后交付上游真实结构并幂等', async () => {
  const upstream = http.createServer((req, res) => {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify({ rows: [{ series: 'DGS10', latest: 5.1 }], data_date: '2026-11-17' }));
  });
  const upstreamPort = await new Promise((resolve) => {
    upstream.listen(0, '127.0.0.1', () => resolve(upstream.address().port));
  });

  const config = buildConfig();
  config.data = {
    resourceId: '/api/data',
    price: '2.99',
    goodsName: '数据服务·单次取数',
    serviceId: 'api_mock_service_id',
    partnerBase: `http://127.0.0.1:${upstreamPort}`,
    partnerToken: 'test-token',
    timeoutMs: 5000
  };
  const { server, base } = await startTestServer({ config });
  try {
    const body = JSON.stringify({ skill: 'market-data-hub', cmd: 'macro', params: { series: 'DGS10' } });
    const first = await fetch(`${base}/api/data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body
    });
    assert.strictEqual(first.status, 402);
    const bill = JSON.parse(base64UrlDecode(first.headers.get('payment-needed')));
    assert.strictEqual(bill.protocol.amount, '2.99');
    assert.strictEqual(bill.protocol.resource_id, '/api/data');

    const tradeNo = '2026112022001400000000000021';
    const paid = await fetch(`${base}/api/data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body
    });
    assert.strictEqual(paid.status, 200);
    const payload = await paid.json();
    assert.strictEqual(payload.resource_id, '/api/data');
    assert.strictEqual(payload.content.rows[0].series, 'DGS10');
    assert.strictEqual(payload.fulfillment_confirmed, true);

    const again = await fetch(`${base}/api/data`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': buildProof(tradeNo) },
      body
    });
    assert.strictEqual((await again.json()).already_fulfilled, true);
  } finally {
    server.close();
    upstream.close();
  }
});

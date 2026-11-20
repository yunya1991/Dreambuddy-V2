'use strict';

const test = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const { createRateLimiter } = require('../src/ratelimit');
const { createApp } = require('../src/app');
const { SqliteOrderRepository } = require('../src/store');

function mockReq(proof) {
  const headers = { 'x-real-ip': '203.0.113.9' };
  if (proof) headers['payment-proof'] = proof;
  return {
    headers,
    socket: { remoteAddress: '203.0.113.9' },
    get(name) {
      return headers[String(name).toLowerCase()];
    }
  };
}

function mockRes() {
  return {
    statusCode: 200,
    headers: {},
    body: null,
    set(key, value) {
      this.headers[key.toLowerCase()] = value;
      return this;
    },
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    }
  };
}

test('匿名滑动窗口：第 21 次 429，带凭证放行，窗口过后恢复', () => {
  let nowMs = Date.parse('2026-11-20T03:00:00.000Z');
  const limiter = createRateLimiter({ max: 20, windowMs: 60 * 60 * 1000, now: () => nowMs });

  for (let i = 0; i < 20; i += 1) {
    let nexted = false;
    limiter(mockReq(), mockRes(), () => {
      nexted = true;
    });
    assert.strictEqual(nexted, true, `第 ${i + 1} 次应放行`);
  }

  const blocked = mockRes();
  let nexted = false;
  limiter(mockReq(), blocked, () => {
    nexted = true;
  });
  assert.strictEqual(nexted, false);
  assert.strictEqual(blocked.statusCode, 429);
  assert.strictEqual(blocked.body.code, 'RATE_LIMITED');
  assert.strictEqual(blocked.body.retry_after, 3600);
  assert.strictEqual(blocked.headers['retry-after'], '3600');

  let bypassed = false;
  limiter(mockReq('proof'), mockRes(), () => {
    bypassed = true;
  });
  assert.strictEqual(bypassed, true);

  nowMs += 60 * 60 * 1000 + 1000;
  let recovered = false;
  limiter(mockReq(), mockRes(), () => {
    recovered = true;
  });
  assert.strictEqual(recovered, true);
});

test('公开接口第 21 次匿名调用返回 429，带 Payment-Proof 直接进入业务', async () => {
  const repo = new SqliteOrderRepository(':memory:');
  const { privateKey } = crypto.generateKeyPairSync('rsa', {
    modulusLength: 2048,
    publicKeyEncoding: { type: 'pkcs1', format: 'pem' },
    privateKeyEncoding: { type: 'pkcs1', format: 'pem' }
  });
  const config = {
    resourceId: '/api/audit',
    price: '0.99',
    currency: 'CNY',
    goodsName: '体检',
    serviceId: 'api_mock_service_id',
    gateway: 'https://openapi-sandbox.dl.alipaydev.com/gateway.do',
    privateKey,
    rateLimit: { max: 20, windowMs: 60 * 60 * 1000 }
  };
  const app = createApp({ config, repository: repo, alipay: {} });
  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  const base = `http://127.0.0.1:${server.address().port}`;

  try {
    const body = JSON.stringify({ skill_md: '---\nname: demo\n---\n# 用法\n运行 `echo hi`。' });
    for (let i = 0; i < 20; i += 1) {
      const res = await fetch(`${base}/api/audit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body
      });
      await res.arrayBuffer();
      assert.strictEqual(res.status, 402, `第 ${i + 1} 次应进入 402 账单`);
    }

    const blocked = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body
    });
    assert.strictEqual(blocked.status, 429);
    assert.strictEqual((await blocked.json()).code, 'RATE_LIMITED');
    assert.ok(blocked.headers.get('retry-after'));

    const withProof = await fetch(`${base}/api/audit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Payment-Proof': 'invalid-proof' },
      body
    });
    await withProof.arrayBuffer();
    assert.strictEqual(withProof.status, 402);
  } finally {
    server.closeAllConnections();
    server.close();
    repo.close();
  }
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createTrialHandler, trimReport, clientIp, normalizeIp, hashIp } = require('../src/trial');
const { SqliteOrderRepository } = require('../src/store');
const { dayKey, retryAfterSeconds } = require('../src/time');

const SALT = 'test-salt-0123456789';

function mockResponse() {
  const res = {
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
  return res;
}

function mockRequest(body, { realIp = '10.0.0.1', xff = '' } = {}) {
  const headers = { 'x-real-ip': realIp };
  if (xff) headers['x-forwarded-for'] = xff;
  return { body, headers, socket: { remoteAddress: realIp } };
}

const VALID_SKILL_MD = ['---', 'name: demo-skill', 'description: 演示用技能，用于验证体检链路是否可用。', 'version: 1.0.0', '---', '', '# 用法', '', '运行 `python3 scripts/demo.py`。'].join('\n');

function makeStore() {
  return new SqliteOrderRepository(':memory:');
}

function makeHandler(store, overrides = {}) {
  return createTrialHandler({
    dailyQuota: 5,
    globalDaily: 200,
    ipSalt: SALT,
    store,
    ...overrides
  });
}

test('额度内返回报告与剩余次数', () => {
  const store = makeStore();
  const handler = makeHandler(store, { dailyQuota: 2 });
  const res = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }), res);

  assert.strictEqual(res.statusCode, 200);
  assert.strictEqual(res.body.trial, true);
  assert.strictEqual(res.body.remaining, 1);
  assert.strictEqual(res.body.report.rules_version, 3);
  assert.strictEqual(typeof res.body.report.score, 'number');
  assert.ok(Array.isArray(res.body.report.checks));
  store.close();
});

test('超出额度返回 429，含 remaining/retry_after/Retry-After', () => {
  const store = makeStore();
  const now = () => Date.parse('2026-11-20T15:59:30.000Z');
  const handler = makeHandler(store, { dailyQuota: 1, now });

  const first = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }), first);
  assert.strictEqual(first.statusCode, 200);

  const second = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }), second);
  assert.strictEqual(second.statusCode, 429);
  assert.strictEqual(second.body.code, 'TRIAL_QUOTA_EXCEEDED');
  assert.strictEqual(second.body.remaining, 0);
  assert.strictEqual(second.body.daily_quota, 1);
  assert.strictEqual(second.body.retry_after, 30);
  assert.strictEqual(second.headers['retry-after'], '30');
  assert.notStrictEqual(dayKey(now()), dayKey(now() + second.body.retry_after * 1000));
  store.close();
});

test('伪造 X-Forwarded-For 不增加额度，第 6 次仍 429', () => {
  const store = makeStore();
  const handler = makeHandler(store, { dailyQuota: 5 });
  for (let i = 0; i < 5; i += 1) {
    const res = mockResponse();
    handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.1.0.1', xff: `203.0.113.${i}` }), res);
    assert.strictEqual(res.statusCode, 200);
  }
  const sixth = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.1.0.1', xff: '198.51.100.9' }), sixth);
  assert.strictEqual(sixth.statusCode, 429);
  store.close();
});

test('额度写入 SQLite，重启后不恢复', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'trial-store-'));
  const dbPath = path.join(dir, 'orders.db');

  const firstStore = new SqliteOrderRepository(dbPath);
  const first = makeHandler(firstStore, { dailyQuota: 1 });
  const used = mockResponse();
  first(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.2.0.1' }), used);
  assert.strictEqual(used.statusCode, 200);
  firstStore.close();

  const secondStore = new SqliteOrderRepository(dbPath);
  const restarted = makeHandler(secondStore, { dailyQuota: 1 });
  const blocked = mockResponse();
  restarted(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.2.0.1' }), blocked);
  assert.strictEqual(blocked.statusCode, 429);
  secondStore.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

test('UTC+8 跨日：UTC 15:59 与 16:00 分属不同 dayKey', () => {
  const store = makeStore();
  let current = Date.parse('2026-11-20T15:59:00.000Z');
  const handler = makeHandler(store, { dailyQuota: 1, now: () => current });

  const before = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.3.0.1' }), before);
  assert.strictEqual(before.statusCode, 200);

  const sameDay = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.3.0.1' }), sameDay);
  assert.strictEqual(sameDay.statusCode, 429);

  current = Date.parse('2026-11-20T16:00:00.000Z');
  const nextDay = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.3.0.1' }), nextDay);
  assert.strictEqual(nextDay.statusCode, 200);
  assert.strictEqual(dayKey(current), '2026-11-21');
  store.close();
});

test('不同 IP 额度互相独立', () => {
  const store = makeStore();
  const handler = makeHandler(store, { dailyQuota: 1 });
  const first = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.4.0.1' }), first);
  const other = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.4.0.2' }), other);
  assert.strictEqual(other.statusCode, 200);
  store.close();
});

test('全局上限触发后其他 IP 也被拦，并写 trial_global_cap 事件', () => {
  const store = makeStore();
  const events = [];
  const handler = makeHandler(store, {
    dailyQuota: 5,
    globalDaily: 2,
    onEvent: (event) => events.push(event)
  });

  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.5.0.1' }), mockResponse());
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.5.0.2' }), mockResponse());
  const third = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.5.0.3' }), third);

  assert.strictEqual(third.statusCode, 429);
  assert.strictEqual(third.body.scope, 'global');
  assert.ok(events.includes('trial_global_cap'));
  store.close();
});

test('缺少 skill_md 返回 400 且不消耗额度', () => {
  const store = makeStore();
  const handler = makeHandler(store, { dailyQuota: 1 });
  const bad = mockResponse();
  handler(mockRequest({}, { realIp: '10.6.0.1' }), bad);
  assert.strictEqual(bad.statusCode, 400);
  assert.strictEqual(bad.body.code, 'INVALID_REQUEST');

  const ok = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '10.6.0.1' }), ok);
  assert.strictEqual(ok.statusCode, 200);
  store.close();
});

test('IPv6 按 /64 归并，同一网段共享额度', () => {
  assert.strictEqual(normalizeIp('2001:db8:1:2:aaaa::1'), '2001:db8:1:2::/64');
  assert.strictEqual(normalizeIp('2001:db8:1:2:bbbb::9'), '2001:db8:1:2::/64');
  assert.strictEqual(normalizeIp('::ffff:203.0.113.7'), '203.0.113.7');
  assert.strictEqual(
    hashIp(normalizeIp('2001:db8:1:2:aaaa::1'), SALT),
    hashIp(normalizeIp('2001:db8:1:2:bbbb::9'), SALT)
  );

  const store = makeStore();
  const handler = makeHandler(store, { dailyQuota: 1 });
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '2001:db8:1:2:aaaa::1' }), mockResponse());
  const blocked = mockResponse();
  handler(mockRequest({ skill_md: VALID_SKILL_MD }, { realIp: '2001:db8:1:2:bbbb::9' }), blocked);
  assert.strictEqual(blocked.statusCode, 429);
  store.close();
});

test('clientIp 只读取 X-Real-IP', () => {
  assert.strictEqual(clientIp({ headers: { 'x-real-ip': '203.0.113.5', 'x-forwarded-for': '1.1.1.1' }, socket: {} }), '203.0.113.5');
  assert.strictEqual(clientIp({ headers: { 'x-forwarded-for': '1.1.1.1' }, socket: { remoteAddress: '127.0.0.1' } }), '127.0.0.1');
});

test('retry_after 与下一个 UTC+8 零点一致', () => {
  const now = Date.parse('2026-11-20T15:00:00.000Z');
  const retry = retryAfterSeconds(now);
  assert.strictEqual(retry, 3600);
  assert.strictEqual(dayKey(now), '2026-11-20');
  assert.strictEqual(dayKey(now + retry * 1000), '2026-11-21');
});

test('裁剪报告最多保留 6 条检查项并隐藏完整报告提示', () => {
  const report = {
    service: 'demo',
    verdict: 'needs_work',
    score: 80,
    counts: { error: 0, warning: 4, total: 20 },
    checks: Array.from({ length: 20 }, (_, i) => ({
      id: `C${i}`,
      title: `check-${i}`,
      status: i < 4 ? 'warn' : 'pass',
      detail: 'detail'
    })),
    next_actions: ['a', 'b', 'c', 'd'],
    disclaimer: 'x',
    audited_at: '2026-01-01T00:00:00.000Z'
  };
  const trimmed = trimReport(report);
  assert.strictEqual(trimmed.checks.length, 6);
  assert.strictEqual(trimmed.checks[0].status, 'warn');
  assert.strictEqual(trimmed.hidden_checks, 14);
  assert.strictEqual(trimmed.next_actions.length, 3);
});

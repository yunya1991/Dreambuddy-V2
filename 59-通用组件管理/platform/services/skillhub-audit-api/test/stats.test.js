'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { SqliteOrderRepository } = require('../src/store');
const { createStatsService } = require('../src/stats');
const { createAdminApp } = require('../src/admin');
const { createApp } = require('../src/app');

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => resolve(server));
  });
}

test('stats 结构完整，30 秒缓存内复用同一结果', () => {
  const repo = new SqliteOrderRepository(':memory:');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'stats-'));
  const eventsFile = path.join(dir, 'events.jsonl');
  fs.writeFileSync(
    eventsFile,
    [
      { event: 'page_view', page: '/', ref_host: '', ts: '2026-11-20T02:00:00.000Z', rules_version: 3, rules_changed: '' },
      { event: 'trial_submit', page: '/trial.html', ref_host: '', ts: '2026-11-20T02:01:00.000Z', rules_version: 3, rules_changed: '' },
      { event: 'trial_success', page: '/trial.html', ref_host: '', ts: '2026-11-20T02:02:00.000Z', rules_version: 3, rules_changed: '' }
    ].map((entry) => JSON.stringify(entry)).join('\n') + '\n'
  );
  repo.consumeTrial({ ipHash: 'a'.repeat(32), day: '2026-11-20', dailyQuota: 5, globalDaily: 2 });
  repo.consumeTrial({ ipHash: 'b'.repeat(32), day: '2026-11-20', dailyQuota: 5, globalDaily: 2 });

  let nowMs = Date.parse('2026-11-20T03:00:00.000Z');
  const service = createStatsService({
    repository: repo,
    eventsFile,
    trialGlobalDaily: 2,
    paidVersions: () => ({ 3: 2 }),
    now: () => nowMs
  });

  const stats = service.getStats();
  assert.strictEqual(stats.trial.today, 2);
  assert.strictEqual(stats.trial.limit, 2);
  assert.strictEqual(stats.trial.unique_ips, 2);
  assert.strictEqual(stats.trial.global_cap_hit, true);
  assert.strictEqual(stats.events.page_view, 1);
  assert.strictEqual(stats.events.trial_submit, 1);
  assert.strictEqual(stats.orders.total, 0);
  assert.deepStrictEqual(stats.reports_by_rules_version, { 3: 3 });
  assert.strictEqual(stats.build.rules_version, 3);
  assert.strictEqual(stats.build.score_formula_version, 'v2');
  assert.strictEqual(stats.limits.rate_limit_mode, 'memory');

  assert.strictEqual(service.getStats(), stats);
  nowMs += 31 * 1000;
  assert.notStrictEqual(service.getStats(), stats);

  repo.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

test('8789 管理接口无 token 401，有 token 返回 stats 与 health', async () => {
  const repo = new SqliteOrderRepository(':memory:');
  const getStats = () => ({ trial: { today: 1 }, limits: { rate_limit_mode: 'memory' } });
  const admin = createAdminApp({
    config: { admin: { token: 'secret-token' }, price: '0.99', currency: 'CNY' },
    getStats
  });
  const server = await listen(admin);
  const base = `http://127.0.0.1:${server.address().port}`;

  try {
    assert.strictEqual((await fetch(`${base}/api/stats`)).status, 401);
    assert.strictEqual((await fetch(`${base}/api/stats`, { headers: { 'X-Admin-Token': 'wrong' } })).status, 401);

    const stats = await fetch(`${base}/api/stats`, { headers: { 'X-Admin-Token': 'secret-token' } });
    assert.strictEqual(stats.status, 200);
    assert.strictEqual((await stats.json()).trial.today, 1);

    const health = await fetch(`${base}/health`, { headers: { 'X-Admin-Token': 'secret-token' } });
    assert.strictEqual(health.status, 200);
    const payload = await health.json();
    assert.strictEqual(payload.rules_version, 3);
    assert.strictEqual(payload.rate_limit_mode, 'memory');
    assert.strictEqual(payload.orders, undefined);
  } finally {
    server.closeAllConnections();
    server.close();
    repo.close();
  }
});

test('公开服务 8788 不提供 /api/stats', async () => {
  const repo = new SqliteOrderRepository(':memory:');
  const config = {
    resourceId: '/api/audit',
    price: '0.99',
    currency: 'CNY',
    goodsName: '体检',
    serviceId: 'api_mock_service_id',
    rateLimit: { max: 20, windowMs: 60 * 60 * 1000 }
  };
  const app = createApp({ config, repository: repo, alipay: {} });
  const server = await listen(app);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    const res = await fetch(`${base}/api/stats`);
    assert.strictEqual(res.status, 404);

    const health = await fetch(`${base}/health`);
    const payload = await health.json();
    assert.strictEqual(payload.rules_version, 3);
    assert.strictEqual(payload.score_formula_version, 'v2');
    assert.strictEqual(payload.rate_limit_mode, 'memory');
    assert.strictEqual(payload.orders, undefined);
  } finally {
    server.closeAllConnections();
    server.close();
    repo.close();
  }
});

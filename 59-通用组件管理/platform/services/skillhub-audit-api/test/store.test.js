'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { SqliteOrderRepository } = require('../src/store');
const { runCleanup } = require('../src/cleanup');
const { dayKey } = require('../src/time');

function addOrder(repo, { outTradeNo, createdAt, orderStatus = 'PENDING_PAYMENT', fulfillStatus = 'UNFULFILLED' }) {
  repo.db
    .prepare(
      `INSERT INTO orders (out_trade_no, amount, currency, resource_id, goods_name, pay_before,
                           order_status, fulfill_status, created_at, updated_at)
       VALUES (?, '0.99', 'CNY', '/api/audit', '体检', '2026-11-21T00:00:00+08:00', ?, ?, ?, ?)`
    )
    .run(outTradeNo, orderStatus, fulfillStatus, createdAt, createdAt);
}

test('trial_usage 原子自增并按 IP/全局额度拦截', () => {
  const repo = new SqliteOrderRepository(':memory:');
  const day = '2026-11-20';

  const first = repo.consumeTrial({ ipHash: 'a'.repeat(32), day, dailyQuota: 2, globalDaily: 3 });
  assert.strictEqual(first.allowed, true);
  assert.strictEqual(first.remaining, 1);

  const second = repo.consumeTrial({ ipHash: 'a'.repeat(32), day, dailyQuota: 2, globalDaily: 3 });
  assert.strictEqual(second.allowed, true);
  assert.strictEqual(second.remaining, 0);

  const blocked = repo.consumeTrial({ ipHash: 'a'.repeat(32), day, dailyQuota: 2, globalDaily: 3 });
  assert.strictEqual(blocked.allowed, false);
  assert.strictEqual(blocked.reason, 'ip');

  const other = repo.consumeTrial({ ipHash: 'b'.repeat(32), day, dailyQuota: 2, globalDaily: 3 });
  assert.strictEqual(other.allowed, true);

  const globalBlocked = repo.consumeTrial({ ipHash: 'c'.repeat(32), day, dailyQuota: 2, globalDaily: 3 });
  assert.strictEqual(globalBlocked.allowed, false);
  assert.strictEqual(globalBlocked.reason, 'global');

  const usage = repo.trialUsageForDay(day);
  assert.strictEqual(usage.total, 3);
  assert.strictEqual(usage.uniqueIps, 2);
  repo.close();
});

test('releaseTrial 归还额度', () => {
  const repo = new SqliteOrderRepository(':memory:');
  repo.consumeTrial({ ipHash: 'd'.repeat(32), day: '2026-11-20', dailyQuota: 1, globalDaily: 10 });
  repo.releaseTrial('d'.repeat(32), '2026-11-20');
  const again = repo.consumeTrial({ ipHash: 'd'.repeat(32), day: '2026-11-20', dailyQuota: 1, globalDaily: 10 });
  assert.strictEqual(again.allowed, true);
  repo.close();
});

test('清理 30 天前额度，保留最近记录', () => {
  const repo = new SqliteOrderRepository(':memory:');
  repo.consumeTrial({ ipHash: 'e'.repeat(32), day: '2026-10-01', dailyQuota: 5, globalDaily: 100 });
  repo.consumeTrial({ ipHash: 'e'.repeat(32), day: '2026-11-19', dailyQuota: 5, globalDaily: 100 });

  const removed = repo.purgeTrialUsageBefore('2026-10-21');
  assert.strictEqual(removed, 1);
  assert.strictEqual(repo.trialUsageForDay('2026-10-01').total, 0);
  assert.strictEqual(repo.trialUsageForDay('2026-11-19').total, 1);
  repo.close();
});

test('8 天前未支付订单被清理，已履约订单保留', () => {
  const repo = new SqliteOrderRepository(':memory:');
  const now = Date.parse('2026-11-20T12:00:00.000Z');
  const old = new Date(now - 8 * 24 * 60 * 60 * 1000).toISOString();

  addOrder(repo, { outTradeNo: 'OLD_PENDING', createdAt: old });
  addOrder(repo, { outTradeNo: 'OLD_FULFILLED', createdAt: old, orderStatus: 'PAID', fulfillStatus: 'FULFILLED' });
  addOrder(repo, { outTradeNo: 'NEW_PENDING', createdAt: new Date(now - 60 * 1000).toISOString() });

  const removed = repo.purgeStalePendingOrders(new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString());
  assert.strictEqual(removed, 1);
  assert.strictEqual(repo.findByOutTradeNo('OLD_PENDING'), null);
  assert.ok(repo.findByOutTradeNo('OLD_FULFILLED'));
  assert.ok(repo.findByOutTradeNo('NEW_PENDING'));

  const stats = repo.orderStats(new Date(now));
  assert.strictEqual(stats.total, 2);
  assert.strictEqual(stats.fulfilled, 1);
  assert.strictEqual(stats.pending_7d, 1);
  repo.close();
});

test('runCleanup 同时清理额度、订单与埋点', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cleanup-'));
  const eventsFile = path.join(dir, 'events.jsonl');
  const nowMs = Date.parse('2026-11-20T12:00:00.000Z');
  const oldIso = new Date(nowMs - 40 * 24 * 60 * 60 * 1000).toISOString();
  fs.writeFileSync(
    eventsFile,
    [
      JSON.stringify({ event: 'page_view', page: '/', ref_host: '', ts: oldIso, rules_version: 3, rules_changed: '' }),
      JSON.stringify({ event: 'page_view', page: '/', ref_host: '', ts: new Date(nowMs).toISOString(), rules_version: 3, rules_changed: '' })
    ].join('\n') + '\n'
  );

  const repo = new SqliteOrderRepository(':memory:');
  repo.consumeTrial({ ipHash: 'f'.repeat(32), day: dayKey(nowMs - 40 * 24 * 60 * 60 * 1000), dailyQuota: 5, globalDaily: 100 });
  addOrder(repo, { outTradeNo: 'CLEAN_OLD', createdAt: new Date(nowMs - 8 * 24 * 60 * 60 * 1000).toISOString() });

  const result = runCleanup({ repository: repo, eventsFile, now: () => nowMs });
  assert.strictEqual(result.trialDeleted, 1);
  assert.strictEqual(result.ordersDeleted, 1);
  assert.strictEqual(result.eventsDeleted, 1);
  assert.strictEqual(fs.readFileSync(eventsFile, 'utf8').trim().split('\n').length, 1);
  repo.close();
  fs.rmSync(dir, { recursive: true, force: true });
});

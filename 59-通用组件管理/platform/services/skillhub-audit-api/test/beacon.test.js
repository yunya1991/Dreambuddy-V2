'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const express = require('express');
const { createBeaconHandler, countEvents, countTrialSuccessVersions, purgeEvents } = require('../src/beacon');

const ORIGIN = 'http://127.0.0.1:8099';
const FIELDS = ['event', 'page', 'ref_host', 'ts', 'rules_version', 'rules_changed'];

async function startBeaconServer(filePath, origins = [ORIGIN]) {
  const app = express();
  app.post(
    '/api/beacon',
    express.json({ limit: '2kb' }),
    createBeaconHandler({ filePath, origins, rulesVersion: 3, rulesChanged: 'FM006 enforce', now: () => Date.parse('2026-11-20T10:00:00.000Z') })
  );
  app.use((err, req, res, next) => {
    if (err && err.type === 'entity.too.large') {
      return res.status(413).json({ code: 'PAYLOAD_TOO_LARGE' });
    }
    return next(err);
  });

  const server = await new Promise((resolve) => {
    const s = app.listen(0, '127.0.0.1', () => resolve(s));
  });
  return { server, base: `http://127.0.0.1:${server.address().port}` };
}

function tempFile() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'beacon-'));
  return { dir, file: path.join(dir, 'events.jsonl') };
}

test('合法事件写入白名单字段，page 只保留 family，忽略未知字段', async () => {
  const { dir, file } = tempFile();
  const { server, base } = await startBeaconServer(file);
  try {
    const res = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: ORIGIN },
      body: JSON.stringify({ event: 'page_view', page: '/p/doc-tools.html?utm=x', email: 'a@b.com' })
    });
    assert.strictEqual(res.status, 204);

    const entry = JSON.parse(fs.readFileSync(file, 'utf8').trim());
    assert.deepStrictEqual(Object.keys(entry), FIELDS);
    assert.strictEqual(entry.event, 'page_view');
    assert.strictEqual(entry.page, '/p/doc-tools');
    assert.strictEqual(entry.rules_version, 3);
    assert.strictEqual(entry.rules_changed, 'FM006 enforce');
    assert.strictEqual(entry.email, undefined);
  } finally {
    server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('跨域 Origin 返回 403，允许列表中的 Referer 可用', async () => {
  const { dir, file } = tempFile();
  const { server, base } = await startBeaconServer(file);
  try {
    const evil = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: 'https://evil.example' },
      body: JSON.stringify({ event: 'page_view', page: '/' })
    });
    assert.strictEqual(evil.status, 403);

    const noOrigin = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event: 'page_view', page: '/' })
    });
    assert.strictEqual(noOrigin.status, 403);

    const referer = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Referer: `${ORIGIN}/guide.html` },
      body: JSON.stringify({ event: 'guide_view' })
    });
    assert.strictEqual(referer.status, 204);
    const entry = JSON.parse(fs.readFileSync(file, 'utf8').trim());
    assert.strictEqual(entry.event, 'guide_view');
    assert.strictEqual(entry.page, '/guide.html');
    assert.strictEqual(entry.ref_host, '127.0.0.1');
  } finally {
    server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('未知事件 400，超过 2KB 返回 413', async () => {
  const { dir, file } = tempFile();
  const { server, base } = await startBeaconServer(file);
  try {
    const bad = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: ORIGIN },
      body: JSON.stringify({ event: 'email_capture', page: '/' })
    });
    assert.strictEqual(bad.status, 400);

    const huge = await fetch(`${base}/api/beacon`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Origin: ORIGIN },
      body: JSON.stringify({ event: 'page_view', page: '/', pad: 'x'.repeat(3000) })
    });
    assert.strictEqual(huge.status, 413);
  } finally {
    server.close();
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('按 UTC+8 统计事件与规则版本，并清理过期埋点', () => {
  const { dir, file } = tempFile();
  fs.writeFileSync(
    file,
    [
      { event: 'page_view', page: '/', ref_host: '', ts: '2026-11-20T01:00:00.000Z', rules_version: 3, rules_changed: '' },
      { event: 'trial_success', page: '/trial.html', ref_host: '', ts: '2026-11-20T02:00:00.000Z', rules_version: 3, rules_changed: '' },
      { event: 'trial_success', page: '/trial.html', ref_host: '', ts: '2026-11-19T02:00:00.000Z', rules_version: 2, rules_changed: '' }
    ].map((entry) => JSON.stringify(entry)).join('\n') + '\n'
  );

  const counts = countEvents(file, '2026-11-20');
  assert.strictEqual(counts.page_view, 1);
  assert.strictEqual(counts.trial_success, 1);
  assert.deepStrictEqual(countTrialSuccessVersions(file, '2026-11-20'), { 3: 1 });

  const removed = purgeEvents(file, Date.parse('2026-11-20T00:00:00.000Z'));
  assert.strictEqual(removed, 1);
  assert.strictEqual(fs.readFileSync(file, 'utf8').trim().split('\n').length, 2);
  fs.rmSync(dir, { recursive: true, force: true });
});

'use strict';

/**
 * V18：并发上限。20 个并发请求 + 全站上限 5 → 成功数必须 ≤5（SPEC §5.5 M3）。
 * 额度判定与自增在同一事务内完成，依赖单实例部署（SPEC §3）。
 */

const test = require('node:test');
const assert = require('node:assert');
const { createTrialHandler } = require('../src/trial');
const { SqliteOrderRepository } = require('../src/store');

const SALT = 'test-salt-0123456789';
const SKILL_MD = ['---', 'name: demo-skill', 'description: 演示用技能，用于验证体检链路是否可用。', 'version: 1.0.0', '---', '', '# 用法', '', '运行 `python3 scripts/demo.py`。'].join('\n');

function mockResponse() {
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

test('20 并发 + 全站上限 5：成功数不超过 5', async () => {
  const store = new SqliteOrderRepository(':memory:');
  const handler = createTrialHandler({
    dailyQuota: 100,
    globalDaily: 5,
    ipSalt: SALT,
    store,
    onEvent: () => {}
  });

  const requests = Array.from({ length: 20 }, (_, index) =>
    new Promise((resolve) => {
      setImmediate(() => {
        const res = mockResponse();
        handler(
          { body: { skill_md: SKILL_MD }, headers: { 'x-real-ip': `10.9.${index}.1` }, socket: {} },
          res
        );
        resolve(res);
      });
    })
  );

  const results = await Promise.all(requests);
  const ok = results.filter((res) => res.statusCode === 200).length;
  const blocked = results.filter((res) => res.statusCode === 429).length;

  assert.strictEqual(ok, 5);
  assert.strictEqual(blocked, 15);
  store.close();
});

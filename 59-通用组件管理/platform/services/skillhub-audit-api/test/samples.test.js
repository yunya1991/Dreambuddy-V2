'use strict';

/**
 * V15：样例回归。断言按规则 id 集合，不按 verdict，避免灰度升 enforce 后测试漂移（SPEC §5.10 / n12）。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { auditSkill } = require('../src/audit');

const SAMPLES_DIR = path.resolve(__dirname, '../../../site/assets/samples');
const FILES = [
  { path: 'SKILL.md', size: 512 },
  { path: 'scripts/demo.py', size: 128 }
];

function auditSample(name) {
  const skillMd = fs.readFileSync(path.join(SAMPLES_DIR, `sample-${name}.md`), 'utf8');
  return auditSkill({ skill_md: skillMd, files: FILES });
}

function failingIds(report) {
  return report.checks
    .filter((check) => check.status !== 'pass' && check.status !== 'skipped')
    .map((check) => check.id)
    .sort();
}

test('样例：合规样本没有阻断项与建议项', () => {
  const report = auditSample('pass');
  assert.deepStrictEqual(failingIds(report), []);
  assert.strictEqual(report.verdict, 'pass');
});

test('样例：告警样本命中预期规则集合', () => {
  const report = auditSample('warn');
  assert.deepStrictEqual(failingIds(report), ['DOC002', 'EX001', 'FAQ001', 'FM005', 'FM007']);
  assert.strictEqual(report.verdict, 'needs_work');
});

test('样例：阻断样本命中预期规则集合', () => {
  const report = auditSample('blocker');
  assert.deepStrictEqual(
    failingIds(report),
    ['DOC001', 'DOC002', 'EX001', 'FAQ001', 'FM001', 'FM002', 'FM003', 'FM005', 'FM006', 'FM007']
  );
  assert.strictEqual(report.verdict, 'fail');
  assert.ok(report.blockers >= 4);
});

test('样例：三份样本都声明为示例，不含绝对路径', () => {
  for (const name of ['pass', 'warn', 'blocker']) {
    const text = fs.readFileSync(path.join(SAMPLES_DIR, `sample-${name}.md`), 'utf8');
    assert.ok(/示例样本/.test(text), `${name} 缺少示例样本声明`);
    assert.ok(!/\/Users\/|\/home\/|\/opt\//.test(text), `${name} 含绝对路径`);
  }
});

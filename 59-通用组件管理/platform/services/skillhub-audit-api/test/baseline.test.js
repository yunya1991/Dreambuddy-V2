'use strict';

/**
 * V19：基线门禁。对 8 个 SKU（4 商品族 × 变体）重跑当前规则，
 * 与 baseline-20261120.json 比对；出现新的 fail / warn 或分数下降 ≥10，
 * 必须在 allowed_changes 白名单中显式确认，否则测试失败（SPEC §8 / M4）。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { auditSkill } = require('../src/audit');

const MODULE_DIR = path.resolve(__dirname, '../../../..');
const BASELINE = JSON.parse(
  fs.readFileSync(path.join(__dirname, 'baseline', 'baseline-20261120.json'), 'utf8')
);

const SKUS = [
  ['cogsteward', 'free', null],
  ['cogsteward', 'pro', 'pro'],
  ['cogsteward', 'pro-pay', 'pro-pay'],
  ['event-context', 'free', null],
  ['event-context', 'pro', 'pro'],
  ['market-data', 'free', null],
  ['market-data', 'pro', 'pro'],
  ['market-facts-daily', 'free', null]
];

function walk(dir, base, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, base, out);
    else out.push({ path: path.relative(base, full).split(path.sep).join('/'), size: fs.statSync(full).size });
  }
}

function auditSku(component, overlay) {
  const baseDir = path.join(MODULE_DIR, 'components', component, 'skill');
  const files = [];
  walk(baseDir, baseDir, files);
  let skillMd = fs.readFileSync(path.join(baseDir, 'SKILL.md'), 'utf8');

  if (overlay) {
    const overlayDir = path.join(MODULE_DIR, 'components', component, 'variants', overlay);
    const overlayFiles = [];
    walk(overlayDir, overlayDir, overlayFiles);
    for (const file of overlayFiles) {
      files.push(file);
      if (file.path === 'SKILL.md') skillMd = fs.readFileSync(path.join(overlayDir, 'SKILL.md'), 'utf8');
    }
  }

  const deduped = new Map();
  for (const file of files) deduped.set(file.path, file.size);
  return auditSkill({
    skill_md: skillMd,
    files: [...deduped].map(([filePath, size]) => ({ path: filePath, size }))
  });
}

function ids(report, status) {
  return report.checks.filter((check) => check.status === status).map((check) => check.id).sort();
}

test('基线：8 个 SKU 全部有快照', () => {
  assert.strictEqual(Object.keys(BASELINE.skus).length, 8);
  for (const [component, key] of SKUS) {
    assert.ok(BASELINE.skus[`${component}/${key}`], `缺少基线 ${component}/${key}`);
  }
});

for (const [component, key, overlay] of SKUS) {
  const sku = `${component}/${key}`;
  test(`基线：${sku} 无未确认的规则差异`, () => {
    const baseline = BASELINE.skus[sku];
    const allowed = new Set(BASELINE.allowed_changes[sku] || []);
    const report = auditSku(component, overlay);

    const newFailing = ids(report, 'fail').filter((id) => !baseline.failing.includes(id) && !allowed.has(id));
    const newWarn = ids(report, 'warn').filter((id) => !baseline.warn.includes(id) && !allowed.has(id));
    const scoreDrop = baseline.score - report.score;

    assert.deepStrictEqual(newFailing, [], `${sku} 新增阻断项`);
    assert.deepStrictEqual(newWarn, [], `${sku} 新增建议项`);
    if (scoreDrop >= 10) {
      assert.fail(`${sku} 分数从 ${baseline.score} 降到 ${report.score}，需人工确认后写入 allowed_changes`);
    }
  });
}

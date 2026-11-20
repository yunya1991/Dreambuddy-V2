'use strict';

/**
 * V17：付费交付物。付费报告必须给出 ≥3 条可粘贴 patches[]，
 * 免费报告只暴露 patch_count，不泄露补丁内容（SPEC §5.2 / B3）。
 */

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { auditSkill } = require('../src/audit');
const { trimReport } = require('../src/trial');

const SAMPLE = path.resolve(__dirname, '../../../site/assets/samples/sample-blocker.md');
const FILES = [{ path: 'SKILL.md', size: 512 }];

function blockerReport() {
  return auditSkill({ skill_md: fs.readFileSync(SAMPLE, 'utf8'), files: FILES });
}

test('阻断样本的付费报告含 ≥3 条 patches，字段契约完整', () => {
  const report = blockerReport();
  assert.ok(Array.isArray(report.patches));
  assert.ok(report.patches.length >= 3, `patch 数量 ${report.patches.length}`);

  for (const patch of report.patches) {
    assert.ok(patch.rule_id);
    assert.ok(patch.target);
    assert.ok(['frontmatter_field', 'description_rewrite', 'package_tree'].includes(patch.kind));
    assert.ok(typeof patch.after === 'string' && patch.after.length > 0);
    assert.ok(patch.apply_hint);
  }

  const ids = report.patches.map((patch) => patch.rule_id);
  for (const id of ['FM001', 'FM002', 'FM003', 'FM006']) {
    assert.ok(ids.includes(id), `缺少 ${id} 的补丁`);
  }
});

test('frontmatter_field 补丁给可直接粘贴的行', () => {
  const report = blockerReport();
  const patch = report.patches.find((item) => item.rule_id === 'FM001');
  assert.strictEqual(patch.target, 'SKILL.md');
  assert.match(patch.after, /^slug: [a-z0-9-]+$/);
  assert.strictEqual(patch.before, null);
});

test('免费裁剪只给 patch_count，不含 patches 明细', () => {
  const trimmed = trimReport(blockerReport());
  assert.strictEqual(typeof trimmed.patch_count, 'number');
  assert.ok(trimmed.patch_count >= 3);
  assert.strictEqual(trimmed.patches, undefined);
});

test('remediation_plan 是唯一源：order 连续，前 3 条 visible_in_free', () => {
  const report = blockerReport();
  const items = report.remediation_plan.items;
  assert.ok(items.length > 0);
  items.forEach((item, index) => {
    assert.strictEqual(item.order, index + 1);
    assert.strictEqual(item.visible_in_free, index < 3);
    assert.ok(item.fix);
  });
  assert.deepStrictEqual(
    report.next_actions,
    items.slice(0, 3).map((item) => `${item.rule_id} ${item.title}：${item.fix}`)
  );
});

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const { auditSkill } = require('../src/audit');

const BASE_FRONT = [
  'name: demo-skill',
  'slug: demo-skill',
  'displayName: 演示技能',
  'version: 1.0.0',
  'description: 当用户需要演示体检链路时使用本技能，覆盖结构、示例与限制。',
  'summary: 演示用技能',
  'license: MIT'
].join('\n');

const BASE_BODY = [
  '# 演示技能',
  '',
  '## 使用',
  '按下面的命令运行即可。',
  '',
  '## 示例',
  '```bash',
  'python3 scripts/demo.py',
  '```',
  '',
  '## 限制',
  '仅用于演示场景，不处理真实数据。',
  '',
  '## FAQ',
  'Q: 为什么只支持演示？',
  'A: 示例需要保持最小可运行。',
  ''
].join('\n') + 'x'.repeat(220);

function skill(front, body) {
  return `---\n${front === undefined ? BASE_FRONT : front}\n---\n\n${body === undefined ? BASE_BODY : body}`;
}

function check(report, id) {
  return report.checks.find((item) => item.id === id);
}

test('基线样本：全部规则通过', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(report.verdict, 'pass');
  assert.strictEqual(report.score, 100);
  assert.strictEqual(report.rules_version, 3);
  assert.strictEqual(report.score_formula_version, 'v2');
});

test('FM000：缺少 frontmatter 时同组规则 skipped 且不扣分', () => {
  const report = auditSkill({ skill_md: BASE_BODY });
  assert.strictEqual(check(report, 'FM000').status, 'fail');
  assert.strictEqual(check(report, 'FM001').status, 'skipped');
  assert.strictEqual(check(report, 'FM006').status, 'skipped');
  assert.ok(report.counts.skipped >= 6);
  assert.strictEqual(report.score, 85);
});

test('FM001：缺 slug 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('slug: demo-skill\n', '')) });
  assert.strictEqual(check(report, 'FM001').status, 'fail');
});

test('FM001：slug 非 kebab-case 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('slug: demo-skill', 'slug: Demo_Skill')) });
  assert.strictEqual(check(report, 'FM001').status, 'fail');
});

test('FM002：version 非 SemVer 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('version: 1.0.0', 'version: v1')) });
  assert.strictEqual(check(report, 'FM002').status, 'fail');
});

test('FM003：缺 displayName 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('displayName: 演示技能\n', '')) });
  assert.strictEqual(check(report, 'FM003').status, 'fail');
});

test('FM004：缺 summary 与 description 判 warn', () => {
  const front = BASE_FRONT.replace('description: 当用户需要演示体检链路时使用本技能，覆盖结构、示例与限制。\n', '').replace('summary: 演示用技能\n', '');
  const report = auditSkill({ skill_md: skill(front) });
  assert.strictEqual(check(report, 'FM004').status, 'warn');
});

test('FM005：缺 license 判 warn', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('license: MIT', '')) });
  assert.strictEqual(check(report, 'FM005').status, 'warn');
});

test('FM006：缺 name 判 fail（平台必填）', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('name: demo-skill\n', '')) });
  assert.strictEqual(check(report, 'FM006').status, 'fail');
  assert.strictEqual(report.verdict, 'fail');
});

test('FM006：name 含保留词判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('name: demo-skill', 'name: claude-helper')) });
  assert.strictEqual(check(report, 'FM006').status, 'fail');
});

test('FM006：name 超过 64 字符判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('name: demo-skill', `name: ${'a'.repeat(65)}`)) });
  assert.strictEqual(check(report, 'FM006').status, 'fail');
});

test('FM007：description 缺触发短语按 warn 计分（灰度）', () => {
  const front = BASE_FRONT.replace('description: 当用户需要演示体检链路时使用本技能，覆盖结构、示例与限制。', 'description: 演示技能');
  const report = auditSkill({ skill_md: skill(front) });
  assert.strictEqual(check(report, 'FM007').status, 'warn');
  assert.strictEqual(report.score, 95);
});

test('FM007：description 超过 1024 字符判 warn', () => {
  const front = BASE_FRONT.replace('description: 当用户需要演示体检链路时使用本技能，覆盖结构、示例与限制。', `description: 当${'很'.repeat(1100)}`);
  const report = auditSkill({ skill_md: skill(front) });
  assert.strictEqual(check(report, 'FM007').status, 'warn');
});

test('FM008：未提供包目录名时 skipped', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(check(report, 'FM008').status, 'skipped');
});

test('FM008：name 与包目录名一致时 pass', () => {
  const report = auditSkill({ skill_md: skill(), package_root: 'demo-skill' });
  assert.strictEqual(check(report, 'FM008').status, 'pass');
});

test('FM008：name 与包目录名不一致按 warn 计分', () => {
  const report = auditSkill({ skill_md: skill(), package_root: 'other-dir' });
  assert.strictEqual(check(report, 'FM008').status, 'warn');
  assert.strictEqual(report.score, 95);
});

test('DOC001：内容为空判 fail', () => {
  const report = auditSkill({ skill_md: '' });
  assert.strictEqual(check(report, 'DOC001').status, 'fail');
});

test('DOC001：正文过短判 warn', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT, '# 短\n\n太短了') });
  assert.strictEqual(check(report, 'DOC001').status, 'warn');
});

test('DOC001：超过 200KB 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT, 'x'.repeat(210 * 1024)) });
  assert.strictEqual(check(report, 'DOC001').status, 'fail');
});

test('DOC002：缺少限制章节判 warn', () => {
  const body = BASE_BODY.replace('## 限制\n仅用于演示场景，不处理真实数据。\n', '');
  const report = auditSkill({ skill_md: skill(BASE_FRONT, body) });
  assert.strictEqual(check(report, 'DOC002').status, 'warn');
});

test('EX001：包含代码块时 pass', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(check(report, 'EX001').status, 'pass');
});

test('EX001：没有代码块或命令时 warn', () => {
  const body = BASE_BODY.replace('```bash\npython3 scripts/demo.py\n```', '直接阅读文档即可。');
  const report = auditSkill({ skill_md: skill(BASE_FRONT, body) });
  assert.strictEqual(check(report, 'EX001').status, 'warn');
});

test('FAQ001：文档内 FAQ 标题即通过', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(check(report, 'FAQ001').status, 'pass');
});

test('FAQ001：包内提供 FAQ.md 也通过', () => {
  const body = BASE_BODY.replace('## FAQ\nQ: 为什么只支持演示？\nA: 示例需要保持最小可运行。\n', '');
  const report = auditSkill({
    skill_md: skill(BASE_FRONT, body),
    files: [{ path: 'FAQ.md', size: 100 }]
  });
  assert.strictEqual(check(report, 'FAQ001').status, 'pass');
});

test('SEC001：包内含 .env 判 fail', () => {
  const report = auditSkill({
    skill_md: skill(),
    files: [{ path: '.env', size: 10 }, { path: 'SKILL.md', size: 1024 }]
  });
  assert.strictEqual(check(report, 'SEC001').status, 'fail');
});

test('SEC001：未提供文件清单时 skipped', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(check(report, 'SEC001').status, 'skipped');
});

test('SEC002：出现 /Users 绝对路径判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT, `${BASE_BODY}\n路径：/Users/demo/work` ) });
  assert.strictEqual(check(report, 'SEC002').status, 'fail');
});

test('SEC003：出现 SkillHub Token 判 fail', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT, `${BASE_BODY}\nskh_0123456789abcdef0123456789abcdef` ) });
  assert.strictEqual(check(report, 'SEC003').status, 'fail');
});

test('PKG001：文件数超过 200 判 fail', () => {
  const files = Array.from({ length: 201 }, (_, i) => ({ path: `f${i}.md`, size: 1 }));
  const report = auditSkill({ skill_md: skill(), files });
  assert.strictEqual(check(report, 'PKG001').status, 'fail');
});

test('PKG002：包体积超过 10MB 判 warn', () => {
  const report = auditSkill({ skill_md: skill(), files: [{ path: 'big.bin', size: 11 * 1024 * 1024 }] });
  assert.strictEqual(check(report, 'PKG002').status, 'warn');
});

test('免费文档：PAY000 pass 且付费规则不参与', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.strictEqual(check(report, 'PAY000').status, 'pass');
  assert.strictEqual(check(report, 'PAY001'), undefined);
});

test('付费意图（target=pay）缺五要素全部 fail', () => {
  const report = auditSkill({ skill_md: skill(), target: 'pay' });
  for (const id of ['PAY001', 'PAY002', 'PAY003', 'PAY004', 'PAY005']) {
    assert.strictEqual(check(report, id).status, 'fail', id);
  }
  assert.strictEqual(check(report, 'PAY100').status, 'pass');
});

test('付费协议五要素齐全时全部 pass', () => {
  const body = `${BASE_BODY}\n\n402 Payment-Needed Payment-Proof payment.verify fulfillment.confirm\n`;
  const report = auditSkill({ skill_md: skill(BASE_FRONT, body), target: 'pay' });
  for (const id of ['PAY001', 'PAY002', 'PAY003', 'PAY004', 'PAY005']) {
    assert.strictEqual(check(report, id).status, 'pass', id);
  }
  assert.strictEqual(report.verdict, 'pass');
});

test('auto 目标：文档出现付费词时按 pay 求值', () => {
  const body = `${BASE_BODY}\n\n本技能支持按次收费。\n`;
  const report = auditSkill({ skill_md: skill(BASE_FRONT, body) });
  assert.strictEqual(report.publish_type, 'pay');
  assert.strictEqual(check(report, 'PAY001').status, 'fail');
});

test('next_actions 不含 skipped 项', () => {
  const report = auditSkill({ skill_md: skill() });
  assert.ok(report.next_actions.every((item) => !item.includes('FLAG')));
  assert.strictEqual(report.next_actions.length, 0);
});

test('计数一致：error + warning + skipped <= total', () => {
  const report = auditSkill({ skill_md: skill(BASE_FRONT.replace('license: MIT', '')) });
  const { error, warning, skipped, total } = report.counts;
  assert.strictEqual(total, report.checks.length);
  assert.ok(error + warning + skipped <= total);
  assert.strictEqual(report.blockers, error);
});

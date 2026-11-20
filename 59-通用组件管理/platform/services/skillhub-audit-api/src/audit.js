'use strict';

/**
 * 体检规则引擎（SPEC §5.1 / §5.2）。
 *
 * 规则与文案一律来自 rules.generated.js（由 contracts/skill-quality-rules.yaml 生成），
 * 本文件只负责求值、灰度降级、skipped 短路与计分。
 */

const spec = require('./rules.generated');

const WEIGHTS = spec.score.weights;
const PAY_MARKERS = spec.pay_markers;
const RULES_VERSION = spec.version;
const SCORE_FORMULA_VERSION = spec.score.formula;
const RULES_CHANGED = latestChanged(spec.changelog);
const RULE_BY_ID = {};
spec.rules.forEach((rule) => {
  RULE_BY_ID[rule.id] = rule;
});

function latestChanged(changelog) {
  const list = changelog || [];
  const last = list[list.length - 1];
  if (!last) return '';
  if (Array.isArray(last.changed)) return last.changed.join('；');
  return String(last.summary || '');
}

function auditSkill(input) {
  const payload = input || {};
  const skillMd = String(payload.skill_md || '');
  const files = Array.isArray(payload.files) ? payload.files : null;
  const packageRoot = typeof payload.package_root === 'string' ? payload.package_root : '';
  const target = payload.target === 'pay' || payload.target === 'free' ? payload.target : 'auto';
  const lower = skillMd.toLowerCase();
  const isPay = target === 'pay' || (target === 'auto' && PAY_MARKERS.some((m) => lower.includes(String(m).toLowerCase())));

  const front = parseFrontmatter(skillMd);
  const ctx = { skillMd, files, packageRoot, meta: front.data, frontOk: front.ok };

  const results = [];
  const statusById = {};
  const failedGroups = new Set();

  for (const rule of spec.rules) {
    if (!appliesTo(rule, isPay)) continue;

    const reason = skipReason(rule, statusById, failedGroups, ctx);
    if (reason) {
      results.push({ id: rule.id, title: rule.title, status: 'skipped', detail: reason });
      statusById[rule.id] = 'skipped';
      continue;
    }

    const result = evaluate(rule, ctx);
    results.push(result);
    statusById[rule.id] = result.status;
    if (result.status === 'fail' && rule.on_fail === 'skip_group') {
      failedGroups.add(rule.group);
    }
  }

  const checks = results.slice();
  if (isPay) {
    checks.push(pass('PAY100', '收费后端形态', '付费 Skill 必须依赖独立部署的后端服务；本次体检只能核对文档与结构，无法验证后端真实可用性'));
  } else {
    checks.push(pass('PAY000', '发布类型', '按免费 Skill 体检；如要按次收费请以 Pay Skill 流程重新体检'));
  }

  const error = checks.filter((c) => c.status === 'fail').length;
  const warning = checks.filter((c) => c.status === 'warn').length;
  const skipped = checks.filter((c) => c.status === 'skipped').length;

  let score = 100;
  for (let i = 0; i < results.length; i += 1) {
    const rule = spec.rules.filter((r) => r.id === results[i].id)[0];
    const result = results[i];
    if (result.status === 'fail') {
      score -= WEIGHTS.blocker;
    } else if (result.status === 'warn' && rule && rule.severity === 'info') {
      score -= WEIGHTS.info;
    } else if (result.status === 'warn') {
      score -= WEIGHTS.warn;
    }
  }
  score = Math.max(0, score);

  const verdict = error > 0 ? 'fail' : warning > 0 ? 'needs_work' : 'pass';
  const dimensions = summarizeDimensions(results);
  const remediationPlan = buildRemediationPlan(results);
  const patches = buildPatches(results, { meta: front.data, packageRoot });
  const skippedDetail = results
    .filter((result) => result.status === 'skipped')
    .map((result) => ({ rule_id: result.id, title: result.title, reason: result.detail }));

  return {
    service: 'SkillHub Skill 上架体检',
    verdict,
    score,
    publish_type: isPay ? 'pay' : 'free',
    summary:
      verdict === 'pass'
        ? '结构与合规检查通过，可按计划提交发布'
        : verdict === 'needs_work'
          ? '存在建议项，修正后收益更高'
          : '存在阻断项，不能直接发布',
    rules_version: RULES_VERSION,
    rules_changed: RULES_CHANGED,
    score_formula_version: SCORE_FORMULA_VERSION,
    blockers: error,
    counts: { error, warning, skipped, total: checks.length },
    dimensions,
    coverage: {
      assessed: Object.keys(dimensions).filter((key) => dimensions[key].assessed > 0),
      not_assessed: ['效果与收益', '兼容性'],
      note: '只报告可静态核验的维度与覆盖度，不输出五维总分'
    },
    checks,
    patches,
    remediation_plan: remediationPlan,
    skipped: skippedDetail,
    next_actions: remediationPlan.items.slice(0, 3).map((item) => `${item.rule_id} ${item.title}：${item.fix}`),
    disclaimer: '本报告基于提交内容做结构与合规体检，不替代 SkillHub 官方审核，也不能证明收费后端已真实可用。',
    audited_at: new Date().toISOString()
  };
}

const SEVERITY_RANK = { blocker: 0, warn: 1, info: 2 };

function summarizeDimensions(results) {
  const labels = spec.dimensions || {};
  const summary = {};
  Object.keys(labels).forEach((key) => {
    const related = results.filter((result) => (RULE_BY_ID[result.id] || {}).dimension === key);
    const assessed = related.filter((result) => result.status !== 'skipped').length;
    summary[key] = {
      label: labels[key].label || key,
      checks: related.length,
      assessed,
      coverage: related.length ? Number((assessed / related.length).toFixed(2)) : 0
    };
  });
  return summary;
}

/** remediation_plan 是唯一源，next_actions 只取前 3 条标题。 */
function buildRemediationPlan(results) {
  const items = results
    .filter((result) => result.status !== 'pass' && result.status !== 'skipped')
    .map((result) => {
      const rule = RULE_BY_ID[result.id] || {};
      const severity =
        result.status === 'fail' ? rule.severity || 'blocker' : rule.severity === 'info' ? 'info' : 'warn';
      return {
        rule_id: result.id,
        severity,
        order: 0,
        title: result.title,
        fix: (rule.messages && rule.messages.fix) || result.detail,
        detail: result.detail,
        visible_in_free: false
      };
    })
    .sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.rule_id.localeCompare(b.rule_id));

  items.forEach((item, index) => {
    item.order = index + 1;
    item.visible_in_free = index < 3;
  });
  return { version: '1.0', items };
}

/** 付费报告的可粘贴补丁（SPEC §5.2）：frontmatter_field / description_rewrite / package_tree。 */
function buildPatches(results, ctx) {
  const patches = [];
  results.forEach((result) => {
    if (result.status === 'pass' || result.status === 'skipped') return;
    const rule = RULE_BY_ID[result.id];
    if (!rule || !rule.patchable || !rule.patch) return;
    const patch = buildPatch(rule, ctx);
    if (patch) patches.push(patch);
  });
  return patches;
}

function buildPatch(rule, ctx) {
  const kind = rule.patch.kind;
  if (kind === 'frontmatter_field') {
    const field = rule.patch.field;
    const after = suggestFieldValue(field, ctx);
    if (!after) return null;
    return {
      rule_id: rule.id,
      target: 'SKILL.md',
      kind,
      before: ctx.meta[String(field).toLowerCase()] || null,
      after: `${field}: ${after}`,
      apply_hint: '粘贴到 SKILL.md frontmatter 的对应位置后重新体检'
    };
  }
  if (kind === 'description_rewrite') {
    const before = ctx.meta.description || '';
    const name = ctx.meta.displayname || ctx.meta.name || ctx.packageRoot || '本技能';
    const after = `description: 当用户需要${name}相关能力时使用本技能。${before}`.slice(0, 1024);
    return {
      rule_id: rule.id,
      target: 'SKILL.md',
      kind,
      before: before || null,
      after,
      apply_hint: '用 after 整体替换 frontmatter 的 description 行'
    };
  }
  if (kind === 'package_tree') {
    return {
      rule_id: rule.id,
      target: '包结构',
      kind,
      before: null,
      after: 'SKILL.md\nscripts/\nreferences/\nassets/',
      apply_hint: '把脚本移入 scripts/、参考资料移入 references/、图片移入 assets/ 后重新打包'
    };
  }
  return null;
}

function suggestFieldValue(field, ctx) {
  const name = ctx.meta.name || ctx.packageRoot || 'my-skill';
  switch (String(field).toLowerCase()) {
    case 'slug':
    case 'name':
      return slugify(name);
    case 'version':
      return '1.0.0';
    case 'displayname':
      return ctx.meta.displayname || name;
    case 'summary':
      return String(ctx.meta.description || '一句话说明本技能能做什么').slice(0, 60);
    case 'license':
      return 'MIT';
    default:
      return '';
  }
}

function slugify(value) {
  const slug = String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
  return slug || 'my-skill';
}

function appliesTo(rule, isPay) {
  const scope = rule.applies_to || ['all'];
  if (scope.includes('all')) return true;
  return scope.includes(isPay ? 'pay' : 'free');
}

function skipReason(rule, statusById, failedGroups, ctx) {
  const check = rule.check || {};
  if (check.requires === 'files' && !ctx.files) return '未提供包内文件清单，已跳过';
  if (check.requires === 'package_root' && !ctx.packageRoot) return '未提供包目录名，已跳过';
  const deps = rule.depends_on || [];
  if (deps.some((id) => statusById[id] && statusById[id] !== 'pass')) {
    return '前置规则未通过，已跳过';
  }
  if (rule.group && failedGroups.has(rule.group)) return '同组前置规则未通过，已跳过';
  return '';
}

function evaluate(rule, ctx) {
  const outcome = runCheck(rule, ctx);
  let status = outcome.status;
  if (status === 'fail' && (rule.stage === 'gray' || rule.severity !== 'blocker')) {
    status = 'warn';
  }
  const messageKey = status === 'pass' ? 'pass' : outcome.messageKey || (status === 'warn' ? 'fail' : 'fail');
  const template = (rule.messages && (rule.messages[messageKey] || rule.messages.fail)) || '';
  return {
    id: rule.id,
    title: rule.title,
    status,
    detail: render(template, outcome.data || {})
  };
}

function runCheck(rule, ctx) {
  const check = rule.check || {};
  const type = rule.type || check.type;
  switch (type) {
    case 'frontmatter_parse':
      return ctx.frontOk
        ? { status: 'pass' }
        : { status: 'fail', messageKey: 'fail' };
    case 'text_length':
      return checkTextLength(check, ctx);
    case 'frontmatter':
      return checkFrontmatter(check, ctx);
    case 'regex_absent':
      return checkRegexAbsent(check, ctx);
    case 'regex_present':
      return checkRegexPresent(check, ctx);
    case 'files':
      return checkFiles(check, ctx);
    case 'section_present':
      return checkSectionPresent(check, ctx);
    case 'frontmatter_name_matches_dir':
      return checkNameMatchesDir(check, ctx);
    default:
      throw new Error(`未知 check.type: ${type}`);
  }
}

function checkTextLength(check, ctx) {
  const bytes = Buffer.byteLength(ctx.skillMd, 'utf8');
  if (bytes > check.max_bytes) {
    return { status: 'fail', messageKey: 'fail_oversize', data: { count: bytes } };
  }
  if (ctx.skillMd.length === 0) {
    return { status: 'fail', messageKey: 'fail_empty' };
  }
  if (ctx.skillMd.trim().length < check.warn_below) {
    return { status: 'warn', messageKey: 'warn_short', data: { count: ctx.skillMd.trim().length } };
  }
  return { status: 'pass' };
}

function checkFrontmatter(check, ctx) {
  const fields = check.any_of || [check.field];
  let value = '';
  let field = fields[0];
  for (const name of fields) {
    const found = ctx.meta[String(name).toLowerCase()];
    if (found) {
      value = found;
      field = name;
      break;
    }
  }
  const data = { value, field, count: String(value).length };
  if (!value) {
    return { status: 'fail', messageKey: 'fail_missing', data };
  }
  if (check.pattern && !new RegExp(check.pattern).test(value)) {
    return { status: 'fail', messageKey: 'fail_invalid', data };
  }
  if ((check.min_len && value.length < check.min_len) || (check.max_len && value.length > check.max_len)) {
    return { status: 'fail', messageKey: 'fail_invalid', data };
  }
  if (check.exclude_words && check.exclude_words.some((word) => value.toLowerCase().includes(String(word).toLowerCase()))) {
    return { status: 'fail', messageKey: 'fail_reserved', data };
  }
  if (check.must_include_any && !check.must_include_any.some((word) => value.toLowerCase().includes(String(word).toLowerCase()))) {
    return { status: 'fail', messageKey: 'fail_trigger', data };
  }
  return { status: 'pass', data };
}

function checkRegexAbsent(check, ctx) {
  if (check.patterns) {
    const labels = check.patterns
      .filter((item) => new RegExp(item.pattern, item.flags || '').test(ctx.skillMd))
      .map((item) => item.label);
    return labels.length
      ? { status: 'fail', messageKey: 'fail', data: { labels: labels.join('、') } }
      : { status: 'pass' };
  }
  const found = [...new Set(ctx.skillMd.match(new RegExp(check.pattern, 'g')) || [])];
  return found.length
    ? { status: 'fail', messageKey: 'fail', data: { values: found.slice(0, 3).join(', ') } }
    : { status: 'pass' };
}

function checkRegexPresent(check, ctx) {
  return new RegExp(check.pattern, check.flags || '').test(ctx.skillMd)
    ? { status: 'pass' }
    : { status: 'fail', messageKey: 'fail' };
}

function checkFiles(check, ctx) {
  const files = ctx.files || [];
  if (check.kind === 'count') {
    return files.length > check.max
      ? { status: 'fail', messageKey: 'fail', data: { count: files.length, max: check.max } }
      : { status: 'pass', data: { count: files.length } };
  }
  if (check.kind === 'total_bytes') {
    const total = files.reduce((sum, file) => sum + (Number(file.size) || 0), 0);
    const mb = (total / 1048576).toFixed(2);
    return total > check.max
      ? { status: 'fail', messageKey: 'fail', data: { value: mb, count: total } }
      : { status: 'pass', data: { value: mb } };
  }
  if (check.kind === 'filename_match') {
    const flags = check.flags || '';
    const risky = files
      .map((file) => String(file.path || ''))
      .filter((path) => check.patterns.some((pattern) => new RegExp(pattern, flags).test(path)));
    return risky.length
      ? { status: 'fail', messageKey: 'fail', data: { values: risky.slice(0, 5).join(', ') } }
      : { status: 'pass' };
  }
  throw new Error(`未知 files.kind: ${check.kind}`);
}

function checkSectionPresent(check, ctx) {
  const text =
    check.scope === 'headings'
      ? ctx.skillMd
          .split(/\r?\n/)
          .filter((line) => /^\s*#{1,6}\s/.test(line))
          .join('\n')
      : ctx.skillMd;

  if (check.file_any && ctx.files && ctx.files.some((file) => new RegExp(check.file_any, 'i').test(String(file.path || '')))) {
    return { status: 'pass' };
  }

  const labels = check.group_labels || [];
  const missing = [];
  (check.groups || []).forEach((group, index) => {
    if (!group.some((alt) => new RegExp(alt, 'i').test(text))) {
      missing.push(labels[index] || group[0]);
    }
  });

  return missing.length
    ? { status: 'fail', messageKey: 'fail', data: { values: missing.join('、') } }
    : { status: 'pass' };
}

function checkNameMatchesDir(check, ctx) {
  const name = ctx.meta[String(check.field || 'name').toLowerCase()] || '';
  if (!name) {
    return { status: 'fail', messageKey: 'fail_missing', data: { value: '', expected: ctx.packageRoot } };
  }
  return name === ctx.packageRoot
    ? { status: 'pass' }
    : { status: 'fail', messageKey: 'fail', data: { value: name, expected: ctx.packageRoot } };
}

function render(template, data) {
  return String(template).replace(/\{(\w+)\}/g, (match, key) =>
    data[key] !== undefined && data[key] !== null ? String(data[key]) : match
  );
}

function parseFrontmatter(md) {
  const match = /^\uFEFF?---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(md);
  if (!match) return { ok: false, data: {} };
  const data = {};
  for (const line of match[1].split(/\r?\n/)) {
    const kv = /^([A-Za-z0-9_-]+)\s*:\s*(.*)$/.exec(line.trim());
    if (!kv) continue;
    data[kv[1].toLowerCase()] = kv[2].replace(/^['"]|['"]$/g, '').trim();
  }
  return { ok: true, data };
}

function pass(id, title, detail) {
  return { id, title, status: 'pass', detail };
}

module.exports = { auditSkill, parseFrontmatter };

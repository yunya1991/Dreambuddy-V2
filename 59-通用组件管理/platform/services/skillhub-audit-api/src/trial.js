'use strict';

const crypto = require('node:crypto');
const { auditSkill } = require('./audit');
const { dayKey, retryAfterSeconds } = require('./time');

const MAX_SKILL_MD_BYTES = 200 * 1024;
const MAX_FILES = 500;
const FREE_CHECK_LIMIT = 6;

/** 只信 nginx 注入的 X-Real-IP；XFF 可被客户端伪造，不得参与额度计算。 */
function clientIp(req) {
  const real = req.headers && req.headers['x-real-ip'];
  if (typeof real === 'string' && real.trim()) return normalizeIp(real.trim());
  return normalizeIp((req.socket && req.socket.remoteAddress) || 'unknown');
}

function normalizeIp(raw) {
  let ip = String(raw || '').trim();
  if (!ip) return 'unknown';
  if (ip.startsWith('[')) {
    const end = ip.indexOf(']');
    if (end > 0) ip = ip.slice(1, end);
  }
  ip = ip.split('%')[0];
  if (/^::ffff:\d+\.\d+\.\d+\.\d+$/i.test(ip)) return ip.slice(7);
  if (/^\d+\.\d+\.\d+\.\d+$/.test(ip)) return ip;
  if (ip.includes(':')) return ipv6Prefix(ip);
  return ip;
}

/** IPv6 按 /64 归并，避免同一用户换后缀刷额度。 */
function ipv6Prefix(ip) {
  const chunks = ip.split('::');
  if (chunks.length > 2) return ip.toLowerCase();
  const left = chunks[0] ? chunks[0].split(':').filter(Boolean) : [];
  const right = chunks.length === 2 && chunks[1] ? chunks[1].split(':').filter(Boolean) : [];
  const missing = Math.max(0, 8 - left.length - right.length);
  const groups = [...left, ...Array(missing).fill('0'), ...right].slice(0, 4);
  return `${groups.map((group) => parseInt(group, 16).toString(16)).join(':')}::/64`;
}

function hashIp(ip, salt) {
  return crypto.createHash('sha256').update(`${ip}${salt}`).digest('hex').slice(0, 32);
}

function normalizeInput(body) {
  if (!body || typeof body !== 'object') {
    return { error: '请求体必须是 JSON 对象' };
  }
  const skillMd = body.skill_md;
  if (typeof skillMd !== 'string' || skillMd.trim().length === 0) {
    return { error: 'skill_md 必须是非空字符串' };
  }
  if (Buffer.byteLength(skillMd, 'utf8') > MAX_SKILL_MD_BYTES) {
    return { error: 'skill_md 超过 200KB 上限' };
  }
  let files = null;
  if (body.files !== undefined) {
    if (!Array.isArray(body.files) || body.files.length > MAX_FILES) {
      return { error: 'files 必须是最多 500 项的数组' };
    }
    files = body.files.map((item) => ({
      path: String((item && item.path) || '').slice(0, 300),
      size: Number((item && item.size) || 0)
    }));
  }
  return { skillMd, files };
}

/** 免费额度只给阻断项 + 前 6 条建议，完整报告（含 patches）仍需走 /api/audit 付费链路。 */
function trimReport(report) {
  const checks = report.checks || [];
  const visible = checks.filter((c) => c.status !== 'skipped');
  const blockers = visible.filter((c) => c.status === 'fail');
  const warns = visible.filter((c) => c.status === 'warn').slice(0, FREE_CHECK_LIMIT);
  const ordered = [...blockers, ...warns];
  if (ordered.length < FREE_CHECK_LIMIT) {
    const passes = visible.filter((c) => c.status === 'pass');
    ordered.push(...passes.slice(0, FREE_CHECK_LIMIT - ordered.length));
  }

  return {
    service: report.service,
    verdict: report.verdict,
    score: report.score,
    publish_type: report.publish_type,
    summary: report.summary,
    rules_version: report.rules_version,
    rules_changed: report.rules_changed,
    score_formula_version: report.score_formula_version,
    blockers: report.blockers,
    dimensions: report.dimensions,
    coverage: report.coverage,
    patch_count: Array.isArray(report.patches) ? report.patches.length : report.patch_count,
    counts: report.counts,
    checks: ordered,
    next_actions: (report.next_actions || []).slice(0, 3),
    hidden_checks: Math.max(0, visible.length - ordered.length),
    skipped_count: checks.length - visible.length,
    disclaimer: report.disclaimer,
    audited_at: report.audited_at
  };
}

/**
 * 创建免费体检处理器（SQLite 额度 + UTC+8 自然日 + 全局日上限）。
 * @param {{ dailyQuota: number, globalDaily: number, ipSalt: string,
 *           store: object, now?: () => number, onEvent?: Function }} options
 */
function createTrialHandler(options) {
  const dailyQuota = Number(options.dailyQuota) || 0;
  const globalDaily = Number(options.globalDaily) || 0;
  const ipSalt = String(options.ipSalt || '');
  const store = options.store;
  const now = options.now || Date.now;
  const onEvent = typeof options.onEvent === 'function' ? options.onEvent : null;

  if (!store || typeof store.consumeTrial !== 'function') {
    throw new Error('免费体检需要 SQLite 额度存储（store.consumeTrial）');
  }
  if (ipSalt.length < 16) {
    throw new Error('免费体检需要不少于 16 字符的 TRIAL_IP_SALT');
  }

  function reject(res, scope, retryAfter) {
    res.set('Retry-After', String(retryAfter));
    res.set('Cache-Control', 'no-store');
    if (onEvent) onEvent(scope === 'global' ? 'trial_global_cap' : 'trial_quota_exceeded');
    return res.status(429).json({
      code: 'TRIAL_QUOTA_EXCEEDED',
      message: scope === 'global' ? '今日全站免费体检额度已用完，请明日再试' : '今日免费体检次数已用完',
      scope,
      remaining: 0,
      daily_quota: dailyQuota,
      retry_after: retryAfter
    });
  }

  return function handleTrial(req, res) {
    const input = normalizeInput(req.body);
    if (input.error) {
      return res.status(400).json({ code: 'INVALID_REQUEST', message: input.error });
    }

    const nowMs = now();
    const day = dayKey(nowMs);
    const ipHash = hashIp(clientIp(req), ipSalt);
    const retryAfter = retryAfterSeconds(nowMs);

    const quota = store.consumeTrial({ ipHash, day, dailyQuota, globalDaily });
    if (!quota.allowed) {
      return reject(res, quota.reason, retryAfter);
    }

    let report;
    try {
      report = auditSkill({ skill_md: input.skillMd, files: input.files, target: 'free' });
    } catch (error) {
      store.releaseTrial(ipHash, day);
      console.error('[trial] 体检失败:', error && error.message);
      return res.status(502).json({ code: 'AUDIT_FAILED', message: '体检服务异常，请稍后重试' });
    }

    res.set('Cache-Control', 'no-store');
    return res.json({
      trial: true,
      remaining: quota.remaining,
      daily_quota: dailyQuota,
      report: trimReport(report)
    });
  };
}

function mountTrial(app, config, { store, onEvent } = {}) {
  if (!config.trial) return false;
  app.post(
    '/api/trial',
    createTrialHandler({
      dailyQuota: config.trial.dailyQuota,
      globalDaily: config.trial.globalDaily,
      ipSalt: config.trial.ipSalt,
      store,
      onEvent
    })
  );
  return true;
}

module.exports = {
  createTrialHandler,
  mountTrial,
  trimReport,
  normalizeInput,
  clientIp,
  normalizeIp,
  hashIp
};

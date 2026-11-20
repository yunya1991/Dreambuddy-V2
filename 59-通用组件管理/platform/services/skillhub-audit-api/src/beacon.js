'use strict';

const fs = require('node:fs');
const path = require('node:path');

const EVENTS = new Set([
  'page_view',
  'trial_submit',
  'trial_success',
  'trial_quota_exceeded',
  'trial_global_cap',
  'cta_skillhub',
  'guide_view'
]);

const PAGE_WHITELIST = new Set(['/', '/index.html', '/trial.html', '/guide.html', '/privacy.html']);

function normalizeOrigin(value) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  try {
    return new URL(raw).origin.toLowerCase();
  } catch (_) {
    return raw.replace(/\/+$/, '').toLowerCase();
  }
}

/** page 只接受本站白名单路径；/p/<family>.html 仅保留 family。 */
function normalizePage(value) {
  let page = String(value || '').trim();
  if (!page) return '';
  page = page.split('?')[0].split('#')[0];
  if (/^https?:\/\//i.test(page)) {
    try {
      page = new URL(page).pathname;
    } catch (_) {
      return '';
    }
  }
  if (!page.startsWith('/')) page = `/${page}`;
  if (PAGE_WHITELIST.has(page)) return page;
  const family = /^\/p\/([a-z0-9][a-z0-9-]{0,63})(?:\.html)?$/.exec(page);
  if (family) return `/p/${family[1]}`;
  return '';
}

function normalizeHost(value) {
  const raw = String(value || '').trim().toLowerCase();
  return /^[a-z0-9.-]{1,100}$/.test(raw) ? raw : '';
}

function originOf(req) {
  const origin = normalizeOrigin(req.get('origin'));
  if (origin) return origin;
  const referer = req.get('referer');
  if (!referer) return '';
  try {
    return new URL(referer).origin.toLowerCase();
  } catch (_) {
    return '';
  }
}

function hostOf(referer) {
  if (!referer) return '';
  try {
    return normalizeHost(new URL(referer).hostname);
  } catch (_) {
    return '';
  }
}

function appendJsonl(filePath, entry) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.appendFileSync(filePath, `${JSON.stringify(entry)}\n`);
}

function createBeaconLogger({ filePath, rulesVersion, rulesChanged, now = Date.now }) {
  return function log(event, fields = {}) {
    const entry = {
      event,
      page: normalizePage(fields.page),
      ref_host: normalizeHost(fields.ref_host),
      ts: new Date(now()).toISOString(),
      rules_version: rulesVersion,
      rules_changed: rulesChanged
    };
    appendJsonl(filePath, entry);
    return entry;
  };
}

function createBeaconHandler({ filePath, origins, rulesVersion, rulesChanged, now = Date.now }) {
  const allowed = new Set((origins || []).map(normalizeOrigin).filter(Boolean));
  const log = createBeaconLogger({ filePath, rulesVersion, rulesChanged, now });

  return function handleBeacon(req, res) {
    const origin = originOf(req);
    if (!origin || !allowed.has(origin)) {
      return res.status(403).json({ code: 'FORBIDDEN_ORIGIN', message: '来源站点不在白名单' });
    }

    const body = req.body || {};
    const event = String(body.event || '');
    if (!EVENTS.has(event)) {
      return res.status(400).json({ code: 'INVALID_EVENT', message: '事件不在白名单' });
    }

    const page = body.page || (req.get('referer') ? (() => {
      try {
        return new URL(req.get('referer')).pathname;
      } catch (_) {
        return '';
      }
    })() : '');

    log(event, {
      page,
      ref_host: body.ref_host || hostOf(req.get('referer'))
    });

    res.set('Cache-Control', 'no-store');
    return res.status(204).end();
  };
}

function readEntries(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return [];
  return fs
    .readFileSync(filePath, 'utf8')
    .split('\n')
    .filter(Boolean)
    .map((line) => {
      try {
        return JSON.parse(line);
      } catch (_) {
        return null;
      }
    })
    .filter(Boolean);
}

function countEvents(filePath, day) {
  const counts = {};
  for (const entry of readEntries(filePath)) {
    if (!entry || typeof entry.ts !== 'string') continue;
    if (day && dayKeyOf(entry.ts) !== day) continue;
    const key = String(entry.event || '');
    if (!EVENTS.has(key)) continue;
    counts[key] = (counts[key] || 0) + 1;
  }
  return counts;
}

function dayKeyOf(iso) {
  const time = Date.parse(String(iso || ''));
  if (!Number.isFinite(time)) return '';
  return new Date(time + 8 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

/** 灰度决策：按 rules_version 统计当天的成功体检数（免费侧埋点）。 */
function countTrialSuccessVersions(filePath, day) {
  const counts = {};
  for (const entry of readEntries(filePath)) {
    if (!entry || entry.event !== 'trial_success') continue;
    if (day && dayKeyOf(entry.ts) !== day) continue;
    const version = String(entry.rules_version ?? '');
    if (!version) continue;
    counts[version] = (counts[version] || 0) + 1;
  }
  return counts;
}

/** 删除 30 天前的埋点，返回删除条数。 */
function purgeEvents(filePath, cutoffMs) {
  if (!filePath || !fs.existsSync(filePath)) return 0;
  const entries = readEntries(filePath);
  const kept = entries.filter((entry) => Date.parse(entry.ts) >= cutoffMs);
  fs.writeFileSync(filePath, kept.map((entry) => JSON.stringify(entry)).join('\n') + (kept.length ? '\n' : ''));
  return entries.length - kept.length;
}

module.exports = {
  EVENTS,
  normalizePage,
  normalizeOrigin,
  createBeaconHandler,
  createBeaconLogger,
  countEvents,
  countTrialSuccessVersions,
  purgeEvents
};

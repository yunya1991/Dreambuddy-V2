'use strict';

const fs = require('node:fs');
const spec = require('./rules.generated');
const { dayKey } = require('./time');
const { countEvents, countTrialSuccessVersions } = require('./beacon');

const CACHE_MS = 30 * 1000;

function readPublicBuild(publicJsonPath) {
  if (!publicJsonPath || !fs.existsSync(publicJsonPath)) {
    return { public_json: null, registry_check: 'unknown' };
  }
  try {
    const data = JSON.parse(fs.readFileSync(publicJsonPath, 'utf8'));
    return {
      public_json: (data.build && data.build.generated_at) || null,
      registry_check: 'pass'
    };
  } catch (_) {
    return { public_json: null, registry_check: 'fail' };
  }
}

/**
 * /api/stats（仅 8789 + X-Admin-Token 可达），30 秒缓存。
 */
function createStatsService({
  repository,
  eventsFile,
  trialGlobalDaily = 0,
  publicJsonPath = '',
  paidVersions = () => ({}),
  now = Date.now
}) {
  let cached = null;
  let cachedAt = 0;

  function build() {
    const nowMs = now();
    const day = dayKey(nowMs);
    const trial = repository.trialUsageForDay(day);
    const events = countEvents(eventsFile, day);
    const orders = repository.orderStats(new Date(nowMs));
    const reports = { ...countTrialSuccessVersions(eventsFile, day) };

    for (const [version, count] of Object.entries(paidVersions() || {})) {
      reports[version] = (reports[version] || 0) + count;
    }

    const pub = readPublicBuild(publicJsonPath);

    return {
      trial: {
        today: trial.total,
        limit: trialGlobalDaily,
        unique_ips: trial.uniqueIps,
        global_cap_hit: trialGlobalDaily > 0 && trial.total >= trialGlobalDaily
      },
      events,
      orders: {
        total: orders.total,
        fulfilled: orders.fulfilled,
        pending_7d: orders.pending_7d
      },
      reports_by_rules_version: reports,
      build: {
        public_json: pub.public_json,
        rules_version: spec.version,
        score_formula_version: spec.score.formula,
        registry_check: pub.registry_check
      },
      limits: { rate_limit_mode: 'memory' }
    };
  }

  return {
    getStats(force = false) {
      const nowMs = now();
      if (!force && cached && nowMs - cachedAt < CACHE_MS) return cached;
      cached = build();
      cachedAt = nowMs;
      return cached;
    }
  };
}

module.exports = { createStatsService, CACHE_MS };

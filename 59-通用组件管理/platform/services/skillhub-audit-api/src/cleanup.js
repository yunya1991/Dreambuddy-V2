'use strict';

const { DAY_MS, dayKey } = require('./time');
const { purgeEvents } = require('./beacon');

const DEFAULT_DELAY_MS = 30 * 1000;
const DEFAULT_INTERVAL_MS = DAY_MS;

/** 清理任务：额度 30 天、订单 7 天未支付、埋点 30 天。 */
function runCleanup({
  repository,
  eventsFile,
  now = Date.now,
  trialRetentionDays = 30,
  orderRetentionDays = 7,
  batchSize = 500
}) {
  const nowMs = now();
  const trialDeleted = repository.purgeTrialUsageBefore(dayKey(nowMs - trialRetentionDays * DAY_MS), batchSize);
  const ordersDeleted = repository.purgeStalePendingOrders(
    new Date(nowMs - orderRetentionDays * DAY_MS).toISOString(),
    batchSize
  );
  const eventsDeleted = eventsFile ? purgeEvents(eventsFile, nowMs - trialRetentionDays * DAY_MS) : 0;
  return { trialDeleted, ordersDeleted, eventsDeleted };
}

function startCleanupJobs(options) {
  let interval = null;
  const timer = setTimeout(() => {
    runCleanup(options);
    interval = setInterval(() => runCleanup(options), options.intervalMs || DEFAULT_INTERVAL_MS);
    interval.unref();
  }, options.delayMs ?? DEFAULT_DELAY_MS);
  timer.unref();

  return {
    runNow: () => runCleanup(options),
    stop() {
      clearTimeout(timer);
      if (interval) clearInterval(interval);
    }
  };
}

module.exports = { runCleanup, startCleanupJobs, DEFAULT_DELAY_MS, DEFAULT_INTERVAL_MS };

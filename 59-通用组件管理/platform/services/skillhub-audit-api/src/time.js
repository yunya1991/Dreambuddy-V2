'use strict';

/** 统一 UTC+8 自然日，避免额度、统计、清理各算一套。 */
const DAY_MS = 24 * 60 * 60 * 1000;
const UTC8_OFFSET_MS = 8 * 60 * 60 * 1000;

function dayKey(now = Date.now()) {
  return new Date(Number(now) + UTC8_OFFSET_MS).toISOString().slice(0, 10);
}

/** 距离下一个 UTC+8 零点的秒数，向上取整，保证跨过 dayKey 边界。 */
function retryAfterSeconds(now = Date.now()) {
  const shifted = Number(now) + UTC8_OFFSET_MS;
  const nextMidnight = (Math.floor(shifted / DAY_MS) + 1) * DAY_MS;
  return Math.max(1, Math.ceil((nextMidnight - shifted) / 1000));
}

module.exports = { DAY_MS, UTC8_OFFSET_MS, dayKey, retryAfterSeconds };

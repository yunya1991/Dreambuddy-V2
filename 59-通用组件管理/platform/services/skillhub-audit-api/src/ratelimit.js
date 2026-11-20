'use strict';

const { clientIp } = require('./trial');

/**
 * 匿名调用滑动窗口限流（单实例内存态，SPEC §5.6）。
 * 携带 Payment-Proof 的请求直接放行，避免付费用户被误伤。
 */
function createRateLimiter({ max = 20, windowMs = 60 * 60 * 1000, now = Date.now } = {}) {
  const buckets = new Map();

  function middleware(req, res, next) {
    if (req.get('Payment-Proof')) return next();

    const key = clientIp(req);
    const nowMs = now();
    const recent = (buckets.get(key) || []).filter((stamp) => nowMs - stamp < windowMs);

    if (recent.length >= max) {
      const retryAfter = Math.max(1, Math.ceil((recent[0] + windowMs - nowMs) / 1000));
      buckets.set(key, recent);
      res.set('Retry-After', String(retryAfter));
      return res.status(429).json({
        code: 'RATE_LIMITED',
        message: '匿名调用过于频繁，请稍后再试或携带 Payment-Proof',
        limit: max,
        retry_after: retryAfter
      });
    }

    recent.push(nowMs);
    buckets.set(key, recent);

    if (buckets.size > 10000) {
      for (const [bucketKey, stamps] of buckets) {
        const alive = stamps.filter((stamp) => nowMs - stamp < windowMs);
        if (alive.length) buckets.set(bucketKey, alive);
        else buckets.delete(bucketKey);
      }
    }

    return next();
  }

  middleware.reset = () => buckets.clear();
  return middleware;
}

module.exports = { createRateLimiter };

'use strict';

const fs = require('node:fs');
const path = require('node:path');
const Database = require('better-sqlite3');

const SCHEMA = `
CREATE TABLE IF NOT EXISTS orders (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  out_trade_no   TEXT NOT NULL UNIQUE,
  trade_no       TEXT UNIQUE,
  amount         TEXT NOT NULL,
  currency       TEXT NOT NULL,
  resource_id    TEXT NOT NULL,
  goods_name     TEXT NOT NULL,
  pay_before     TEXT NOT NULL,
  order_status   TEXT NOT NULL,
  fulfill_status TEXT NOT NULL,
  service_result TEXT,
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_trade_no ON orders(trade_no);
CREATE INDEX IF NOT EXISTS idx_orders_pending ON orders(order_status, fulfill_status, created_at);

CREATE TABLE IF NOT EXISTS trial_usage (
  ip_hash    TEXT NOT NULL,
  day        TEXT NOT NULL,
  count      INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (ip_hash, day)
);
CREATE INDEX IF NOT EXISTS idx_trial_usage_day ON trial_usage(day);
`;

class SqliteOrderRepository {
  constructor(dbPath) {
    if (dbPath !== ':memory:') {
      fs.mkdirSync(path.dirname(dbPath), { recursive: true, mode: 0o700 });
    }
    this.db = new Database(dbPath);
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('synchronous = FULL');
    this.db.pragma('busy_timeout = 5000');
    this.db.exec(SCHEMA);
  }

  createPending(order) {
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO orders (out_trade_no, amount, currency, resource_id, goods_name, pay_before,
                             order_status, fulfill_status, created_at, updated_at)
         VALUES (@outTradeNo, @amount, @currency, @resourceId, @goodsName, @payBefore,
                 @orderStatus, @fulfillStatus, @now, @now)`
      )
      .run({ ...order, now });
  }

  findByOutTradeNo(outTradeNo) {
    const row = this.db.prepare('SELECT * FROM orders WHERE out_trade_no = ?').get(outTradeNo);
    return row ? toOrder(row) : null;
  }

  findByTradeNo(tradeNo) {
    const row = this.db.prepare('SELECT * FROM orders WHERE trade_no = ?').get(tradeNo);
    return row ? toOrder(row) : null;
  }

  /**
   * 原子进入待确认/已完成：资源只生成一次，重复凭证返回已保存结果。
   */
  prepareFulfillment({ outTradeNo, tradeNo, expectedAmount, expectedResourceId, createResource }) {
    const tx = this.db.transaction(() => {
      const row = this.db.prepare('SELECT * FROM orders WHERE out_trade_no = ?').get(outTradeNo);
      if (!row) {
        throw new OrderError('ORDER_NOT_FOUND', `本地订单不存在：${outTradeNo}`);
      }
      const order = toOrder(row);
      if (order.fulfillStatus === 'FULFILLED') {
        return { state: 'FULFILLED', serviceResult: order.serviceResult };
      }
      if (order.tradeNo && order.tradeNo !== tradeNo) {
        throw new OrderError('TRADE_NO_CONFLICT', '该订单已绑定其他支付交易号');
      }
      if (order.amount !== expectedAmount) {
        throw new OrderError('AMOUNT_MISMATCH', '支付金额与本地订单金额不一致');
      }
      if (order.resourceId !== expectedResourceId) {
        throw new OrderError('RESOURCE_ID_MISMATCH', '验付资源与本地订单资源不一致');
      }
      const usedByOther = this.db.prepare('SELECT out_trade_no FROM orders WHERE trade_no = ? AND out_trade_no <> ?').get(tradeNo, outTradeNo);
      if (usedByOther) {
        throw new OrderError('TRADE_NO_REUSED', '该支付交易号已被其他订单履约');
      }
      const state = order.fulfillStatus === 'PENDING_CONFIRM' && order.serviceResult
        ? { state: 'PENDING_CONFIRM', serviceResult: order.serviceResult }
        : null;
      if (state) {
        return state;
      }
      const serviceResult = createResource();
      this.db
        .prepare(
          `UPDATE orders SET trade_no = @tradeNo, order_status = 'PAID', fulfill_status = 'PENDING_CONFIRM',
                             service_result = @serviceResult, updated_at = @now
           WHERE out_trade_no = @outTradeNo`
        )
        .run({ tradeNo, serviceResult, outTradeNo, now: new Date().toISOString() });
      return { state: 'PENDING_CONFIRM', serviceResult };
    });
    return tx.immediate();
  }

  markFulfilled(outTradeNo, tradeNo) {
    this.db
      .prepare(
        `UPDATE orders SET fulfill_status = 'FULFILLED', trade_no = COALESCE(trade_no, @tradeNo),
                           order_status = 'PAID', updated_at = @now
         WHERE out_trade_no = @outTradeNo`
      )
      .run({ outTradeNo, tradeNo, now: new Date().toISOString() });
  }

  stats() {
    return this.db
      .prepare(
        `SELECT COUNT(*) AS total,
                SUM(CASE WHEN fulfill_status = 'FULFILLED' THEN 1 ELSE 0 END) AS fulfilled
         FROM orders`
      )
      .get();
  }

  orderStats(now = new Date()) {
    const pendingCutoff = new Date(Number(now) - 7 * 24 * 60 * 60 * 1000).toISOString();
    return this.db
      .prepare(
        `SELECT COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN fulfill_status = 'FULFILLED' THEN 1 ELSE 0 END), 0) AS fulfilled,
                COALESCE(SUM(CASE WHEN order_status = 'PENDING_PAYMENT'
                                   AND fulfill_status = 'UNFULFILLED'
                                   AND created_at >= @pendingCutoff THEN 1 ELSE 0 END), 0) AS pending_7d
         FROM orders`
      )
      .get({ pendingCutoff });
  }

  /**
   * 原子占用一次免费额度：同事务内完成「个人额度判定 + 全局额度判定 + 自增」，
   * 并发下不会越过 TRIAL_GLOBAL_DAILY。
   */
  consumeTrial({ ipHash, day, dailyQuota, globalDaily, now = new Date() }) {
    const tx = this.db.transaction(() => {
      const row = this.db
        .prepare('SELECT count FROM trial_usage WHERE ip_hash = ? AND day = ?')
        .get(ipHash, day);
      const used = row ? row.count : 0;
      const globalUsed = this.db
        .prepare('SELECT COALESCE(SUM(count), 0) AS total FROM trial_usage WHERE day = ?')
        .get(day).total;

      if (used >= dailyQuota) {
        return { allowed: false, reason: 'ip', remaining: 0, used, globalUsed };
      }
      if (globalUsed >= globalDaily) {
        return {
          allowed: false,
          reason: 'global',
          remaining: Math.max(0, dailyQuota - used),
          used,
          globalUsed
        };
      }

      this.db
        .prepare(
          `INSERT INTO trial_usage (ip_hash, day, count, updated_at)
           VALUES (@ipHash, @day, 1, @now)
           ON CONFLICT(ip_hash, day) DO UPDATE SET
             count = trial_usage.count + 1,
             updated_at = excluded.updated_at`
        )
        .run({ ipHash, day, now: new Date(now).toISOString() });

      return { allowed: true, reason: null, remaining: dailyQuota - used - 1, used: used + 1, globalUsed: globalUsed + 1 };
    });
    return tx.immediate();
  }

  /** 体检执行失败时归还额度，避免用户因服务异常被扣次数。 */
  releaseTrial(ipHash, day) {
    this.db
      .prepare(
        `UPDATE trial_usage SET count = count - 1, updated_at = @now
         WHERE ip_hash = @ipHash AND day = @day AND count > 0`
      )
      .run({ ipHash, day, now: new Date().toISOString() });
  }

  trialUsageForDay(day) {
    const row = this.db
      .prepare('SELECT COALESCE(SUM(count), 0) AS total, COUNT(*) AS uniqueIps FROM trial_usage WHERE day = ?')
      .get(day);
    return { total: row.total, uniqueIps: row.uniqueIps };
  }

  purgeTrialUsageBefore(cutoffDay, batchSize = 500) {
    return this._purgeByIds(
      'SELECT rowid FROM trial_usage WHERE day < ? LIMIT ?',
      'DELETE FROM trial_usage WHERE rowid IN (SELECT rowid FROM trial_usage WHERE day < ? LIMIT ?)',
      cutoffDay,
      batchSize
    );
  }

  purgeStalePendingOrders(cutoffIso, batchSize = 500) {
    return this._purgeByIds(
      `SELECT rowid FROM orders
        WHERE order_status = 'PENDING_PAYMENT' AND fulfill_status = 'UNFULFILLED' AND created_at < ?
        LIMIT ?`,
      `DELETE FROM orders WHERE rowid IN (
         SELECT rowid FROM orders
          WHERE order_status = 'PENDING_PAYMENT' AND fulfill_status = 'UNFULFILLED' AND created_at < ?
          LIMIT ?)`,
      cutoffIso,
      batchSize
    );
  }

  _purgeByIds(selectSql, deleteSql, cutoff, batchSize) {
    let removed = 0;
    for (;;) {
      const rows = this.db.prepare(selectSql).all(cutoff, batchSize);
      if (!rows.length) break;
      const info = this.db.prepare(deleteSql).run(cutoff, batchSize);
      removed += info.changes;
      if (rows.length < batchSize) break;
    }
    return removed;
  }

  close() {
    this.db.close();
  }
}

class OrderError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function toOrder(row) {
  return {
    outTradeNo: row.out_trade_no,
    tradeNo: row.trade_no,
    amount: row.amount,
    currency: row.currency,
    resourceId: row.resource_id,
    goodsName: row.goods_name,
    payBefore: row.pay_before,
    orderStatus: row.order_status,
    fulfillStatus: row.fulfill_status,
    serviceResult: row.service_result
  };
}

module.exports = { SqliteOrderRepository, OrderError };

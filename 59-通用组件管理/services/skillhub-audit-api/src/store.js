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

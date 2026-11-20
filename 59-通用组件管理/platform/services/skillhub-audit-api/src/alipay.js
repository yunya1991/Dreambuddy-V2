'use strict';

const crypto = require('node:crypto');
const { AlipaySdk } = require('alipay-sdk');

const SIGN_FIELDS = ['amount', 'currency', 'goods_name', 'out_trade_no', 'pay_before', 'resource_id', 'seller_id', 'service_id'];

function base64UrlEncode(input) {
  return Buffer.from(input, 'utf8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function base64UrlDecode(input) {
  let str = String(input || '').trim().replace(/-/g, '+').replace(/_/g, '/');
  while (str.length % 4) str += '=';
  return Buffer.from(str, 'base64').toString('utf8');
}

function decodePaymentProof(header) {
  const candidates = [base64UrlDecode(header), Buffer.from(String(header), 'base64').toString('utf8')];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      const protocol = parsed.protocol || {};
      const method = parsed.method || {};
      return {
        paymentProof: protocol.payment_proof,
        tradeNo: protocol.trade_no,
        clientSession: method.client_session
      };
    } catch (_) {
      /* 尝试下一种编码 */
    }
  }
  return null;
}

/** 支付宝要求 yyyy-MM-ddTHH:mm:ss+08:00，与服务器本地时区无关。 */
function formatPayBefore(date) {
  const shifted = new Date(date.getTime() + 8 * 3600 * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return (
    `${shifted.getUTCFullYear()}-${pad(shifted.getUTCMonth() + 1)}-${pad(shifted.getUTCDate())}` +
    `T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}:${pad(shifted.getUTCSeconds())}+08:00`
  );
}

function createPrivateKey(anyFormatKey) {
  const base64 = String(anyFormatKey)
    .replace(/-----(BEGIN|END)[^-]+-----/g, '')
    .replace(/\s+/g, '');
  const der = Buffer.from(base64, 'base64');
  try {
    return crypto.createPrivateKey({ key: der, format: 'der', type: 'pkcs1' });
  } catch (_) {
    return crypto.createPrivateKey({ key: der, format: 'der', type: 'pkcs8' });
  }
}

/** 商家账单签名：按 key 字典序拼接后 RSA-SHA256，只在商家本地完成。 */
function signBill(fields, privateKey) {
  const content = SIGN_FIELDS.filter((k) => fields[k] !== undefined && fields[k] !== null && fields[k] !== '')
    .map((k) => `${k}=${fields[k]}`)
    .join('&');
  return crypto.createSign('RSA-SHA256').update(content, 'utf8').sign(createPrivateKey(privateKey), 'base64');
}

function buildPaymentNeeded(config, bill, serviceId) {
  const sid = serviceId || config.serviceId;
  const sellerSignature = signBill(
    {
      amount: bill.amount,
      currency: bill.currency,
      goods_name: bill.goodsName,
      out_trade_no: bill.outTradeNo,
      pay_before: bill.payBefore,
      resource_id: bill.resourceId,
      seller_id: config.sellerId,
      service_id: sid
    },
    config.privateKey
  );

  const payload = {
    protocol: {
      out_trade_no: bill.outTradeNo,
      amount: bill.amount,
      currency: bill.currency,
      resource_id: bill.resourceId,
      pay_before: bill.payBefore,
      seller_signature: sellerSignature,
      seller_sign_type: 'RSA2',
      seller_unique_id: config.sellerId
    },
    method: {
      seller_name: config.sellerName,
      seller_id: config.sellerId,
      seller_app_id: config.appId,
      goods_name: bill.goodsName,
      seller_unique_id_key: 'seller_id',
      service_id: sid
    }
  };
  return base64UrlEncode(JSON.stringify(payload));
}

function createAlipayClient(config) {
  const sdk = new AlipaySdk({
    appId: config.appId,
    privateKey: config.privateKey,
    alipayPublicKey: config.alipayPublicKey,
    gateway: config.gateway,
    signType: 'RSA2',
    timeout: 30000
  });

  async function exec(method, bizContent) {
    const response = await sdk.exec(method, { bizContent });
    const nested = response[`${method.replace(/\./g, '_')}_response`];
    return nested || response;
  }

  return {
    async verifyPayment({ paymentProof, tradeNo, clientSession }) {
      const bizContent = { trade_no: tradeNo, payment_proof: paymentProof };
      if (clientSession) bizContent.client_session = clientSession;
      const data = await exec('alipay.aipay.agent.payment.verify', bizContent);
      return {
        code: data.code,
        msg: data.sub_msg || data.msg,
        active: data.active === true || data.active === 'true',
        tradeNo: data.trade_no || data.tradeNo || '',
        outTradeNo: data.out_trade_no || data.outTradeNo || '',
        amount: data.amount,
        resourceId: data.resource_id || data.resourceId || ''
      };
    },

    async confirmFulfillment(tradeNo) {
      const data = await exec('alipay.aipay.agent.fulfillment.confirm', { trade_no: tradeNo });
      if (data.code === '10000' || data.code === 10000) {
        return { ok: true };
      }
      return { ok: false, code: data.sub_code || data.code, msg: data.sub_msg || data.msg };
    }
  };
}

module.exports = {
  createAlipayClient,
  buildPaymentNeeded,
  decodePaymentProof,
  formatPayBefore,
  signBill,
  base64UrlEncode,
  base64UrlDecode
};

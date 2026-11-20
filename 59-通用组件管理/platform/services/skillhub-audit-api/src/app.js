'use strict';

const express = require('express');
const crypto = require('node:crypto');
const { auditSkill } = require('./audit');
const { buildPaymentNeeded, decodePaymentProof, formatPayBefore, base64UrlEncode } = require('./alipay');
const { normalizeDataInput, runDataQuery } = require('./data');
const { normalizeCogstewardInput, buildCogstewardReport } = require('./cogsteward');

const RESOURCE_PATH = '/api/audit';
const MAX_BODY = '1mb';

function createApp({ config, repository, alipay }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: MAX_BODY }));
  app.use((req, res, next) => {
    res.set('Cache-Control', 'no-store');
    next();
  });

  const resources = buildResources(config);

  app.get('/health', (req, res) => {
    const stats = repository.stats();
    res.json({
      status: 'ok',
      service: 'skillhub-audit-api',
      price: config.price,
      currency: config.currency,
      resources: resources.map((r) => ({ path: r.path, price: r.price })),
      orders: stats
    });
  });

  app.get('/', (req, res) => {
    res.json({
      service: 'SkillHub 付费资源服务',
      currency: config.currency,
      protocol: '支付宝 AI 按量付费（HTTP 402 + Payment-Needed / Payment-Proof）',
      resources: resources.map((r) => ({
        endpoint: `POST ${r.path}`,
        price: `${r.price} CNY / 次`,
        goods_name: r.goodsName
      })),
      usage_audit: 'POST {"skill_md":"<SKILL.md 内容>","files":[{"path":"SKILL.md","size":123}],"target":"auto|free|pay"}',
      usage_data: 'POST {"skill":"market-data-pro","cmd":"macro","params":{"series":"DGS10"}}',
      usage_cogsteward: 'POST {"metrics":{"broken_links":2,"orphan_files":7,"index_drift":0,"skill_conflicts":1,"stale_sessions":3,"pending_backlog":12},"inventory":{"documents":400,"skills":45,"sessions":80},"mode":"dev"}'
    });
  });

  for (const resource of resources) {
    app.post(resource.path, (req, res) => handlePaid(req, res, { config, repository, alipay, resource }));
  }

  app.use((err, req, res, next) => {
    if (err && err.type === 'entity.too.large') {
      return res.status(413).json({ code: 'PAYLOAD_TOO_LARGE', message: '请求体过大（上限 1MB）' });
    }
    console.error('[error]', err && err.message);
    return res.status(500).json({ code: 'INTERNAL_ERROR', message: '服务异常' });
  });

  return app;
}

function buildResources(config) {
  const list = [
    {
      path: config.resourceId,
      price: config.price,
      goodsName: config.goodsName,
      serviceId: config.serviceId,
      normalize: normalizeInput,
      execute: (input) =>
        Promise.resolve(auditSkill({ skill_md: input.skillMd, files: input.files, target: input.target }))
    }
  ];
  if (config.data) {
    list.push({
      path: config.data.resourceId,
      price: config.data.price,
      goodsName: config.data.goodsName,
      serviceId: config.data.serviceId,
      normalize: normalizeDataInput,
      execute: (input) => runDataQuery(input, config.data)
    });
  }
  if (config.cogsteward) {
    list.push({
      path: config.cogsteward.resourceId,
      price: config.cogsteward.price,
      goodsName: config.cogsteward.goodsName,
      serviceId: config.cogsteward.serviceId,
      normalize: normalizeCogstewardInput,
      execute: (input) => Promise.resolve(buildCogstewardReport(input))
    });
  }
  return list;
}

function normalizeInput(body) {
  if (!body || typeof body !== 'object') {
    return { error: '请求体必须是 JSON 对象' };
  }
  const skillMd = body.skill_md;
  if (typeof skillMd !== 'string' || skillMd.trim().length === 0) {
    return { error: 'skill_md 必须是非空字符串' };
  }
  if (Buffer.byteLength(skillMd, 'utf8') > 200 * 1024) {
    return { error: 'skill_md 超过 200KB 上限' };
  }
  let files = null;
  if (body.files !== undefined) {
    if (!Array.isArray(body.files) || body.files.length > 500) {
      return { error: 'files 必须是最多 500 项的数组' };
    }
    files = body.files.map((f) => ({
      path: String((f && f.path) || '').slice(0, 300),
      size: Number((f && f.size) || 0)
    }));
  }
  const target = ['auto', 'free', 'pay'].includes(body.target) ? body.target : 'auto';
  return { skillMd, files, target };
}

async function handlePaid(req, res, { config, repository, alipay, resource }) {
  const input = resource.normalize(req.body);
  if (input.error) {
    return res.status(400).json({ code: 'INVALID_REQUEST', message: input.error });
  }

  const proofHeader = req.get('Payment-Proof');
  if (!proofHeader || !proofHeader.trim()) {
    return createPaymentRequired(res, { config, repository, resource });
  }

  const proof = decodePaymentProof(proofHeader);
  if (!proof || !proof.paymentProof || !proof.tradeNo) {
    return createPaymentRequired(res, { config, repository, resource });
  }

  let verify;
  try {
    verify = await alipay.verifyPayment(proof);
  } catch (error) {
    console.error('[verify] 调用验付失败:', error.message);
    return res.status(502).json({ code: 'VERIFY_UPSTREAM_ERROR', message: '验付接口暂不可用，请稍后用同一 Payment-Proof 重试' });
  }

  if (verify.code !== '10000' && verify.code !== 10000) {
    console.warn('[verify] 验付返回失败:', verify.code, verify.msg);
    return createPaymentRequired(res, { config, repository, resource });
  }

  const order = verify.outTradeNo ? repository.findByOutTradeNo(verify.outTradeNo) : null;
  const sandboxMode = config.sandboxExact;
  const tradeNo = verify.tradeNo || (sandboxMode ? proof.tradeNo : '');
  const amountMissing = verify.amount === undefined || verify.amount === null || verify.amount === '';
  const amount = amountMissing && sandboxMode && order ? order.amount : verify.amount;
  const resourceId = verify.resourceId || (sandboxMode && order ? order.resourceId : '');

  if (!verify.active || !tradeNo || tradeNo !== proof.tradeNo || !verify.outTradeNo || !resourceId) {
    console.warn('[verify] 凭证校验不通过:', {
      active: verify.active,
      hasTradeNo: Boolean(tradeNo),
      hasOutTradeNo: Boolean(verify.outTradeNo),
      hasResource: Boolean(resourceId)
    });
    return createPaymentRequired(res, { config, repository, resource });
  }

  const orderUsable =
    order &&
    order.currency === 'CNY' &&
    ['PENDING_PAYMENT', 'PAID'].includes(order.orderStatus) &&
    ['UNFULFILLED', 'PENDING_CONFIRM', 'FULFILLED'].includes(order.fulfillStatus) &&
    (['PENDING_CONFIRM', 'FULFILLED'].includes(order.fulfillStatus) || Date.parse(order.payBefore) > Date.now());

  if (!orderUsable || order.resourceId !== resourceId || resourceId !== resource.path || !amountMatches(order.amount, amount)) {
    console.warn('[verify] 本地订单校验不通过:', { orderFound: Boolean(order), resourceId, amount });
    return createPaymentRequired(res, { config, repository, resource });
  }

  if (order.fulfillStatus === 'FULFILLED' && order.serviceResult) {
    return sendSuccess(res, {
      tradeNo,
      outTradeNo: verify.outTradeNo,
      resourceId,
      report: JSON.parse(order.serviceResult),
      alreadyFulfilled: true
    });
  }

  let content;
  try {
    content = await resource.execute(input);
  } catch (error) {
    console.error('[exec] 资源生成失败:', error.code || '', error.message);
    return res.status(error.status && error.status < 500 ? 503 : 502).json({
      code: error.code || 'EXECUTION_FAILED',
      message: '资源生成失败，请稍后用同一 Payment-Proof 重试'
    });
  }

  let fulfillment;
  try {
    fulfillment = repository.prepareFulfillment({
      outTradeNo: verify.outTradeNo,
      tradeNo,
      expectedAmount: normalizeAmount(amount),
      expectedResourceId: resourceId,
      createResource: () => JSON.stringify(content)
    });
  } catch (error) {
    console.error('[fulfill] 履约准备失败:', error.code || '', error.message);
    return createPaymentRequired(res, { config, repository, resource });
  }

  if (fulfillment.state === 'FULFILLED') {
    return sendSuccess(res, {
      tradeNo,
      outTradeNo: verify.outTradeNo,
      resourceId,
      report: JSON.parse(fulfillment.serviceResult),
      alreadyFulfilled: true
    });
  }

  const confirmed = await alipay.confirmFulfillment(tradeNo);
  if (!confirmed.ok) {
    console.error('[fulfill] 履约确认失败:', confirmed.code, confirmed.msg);
    return res.status(502).json({
      code: 'FULFILLMENT_CONFIRM_FAILED',
      message: '结果已生成但履约确认失败，请稍后使用同一 Payment-Proof 重试'
    });
  }

  repository.markFulfilled(verify.outTradeNo, tradeNo);
  return sendSuccess(res, {
    tradeNo,
    outTradeNo: verify.outTradeNo,
    resourceId,
    report: JSON.parse(fulfillment.serviceResult),
    alreadyFulfilled: false
  });
}

function newOutTradeNo() {
  return `PAY_${Date.now()}_${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`;
}

function createPaymentRequired(res, { config, repository, resource }) {
  const outTradeNo = newOutTradeNo();
  const payBefore = formatPayBefore(new Date(Date.now() + config.payWindowMinutes * 60 * 1000));
  const bill = {
    outTradeNo,
    amount: resource.price,
    currency: config.currency,
    resourceId: resource.path,
    goodsName: resource.goodsName,
    payBefore
  };

  const paymentNeeded = buildPaymentNeeded(config, bill, resource.serviceId);
  repository.createPending({
    outTradeNo,
    amount: resource.price,
    currency: config.currency,
    resourceId: resource.path,
    goodsName: resource.goodsName,
    payBefore,
    orderStatus: 'PENDING_PAYMENT',
    fulfillStatus: 'UNFULFILLED'
  });

  res.set('Payment-Needed', paymentNeeded);
  return res.status(402).json({
    code: 'Payment-Needed',
    message: '需要支付后返回结果',
    out_trade_no: outTradeNo,
    amount: resource.price,
    currency: config.currency,
    goods_name: resource.goodsName,
    resource_id: resource.path,
    pay_before: payBefore
  });
}

function sendSuccess(res, { tradeNo, outTradeNo, resourceId, report, alreadyFulfilled }) {
  res.set(
    'Payment-Validation',
    base64UrlEncode(JSON.stringify({ trade_no: tradeNo, out_trade_no: outTradeNo, validated: true, resource_id: resourceId }))
  );
  return res.json({
    resource_id: resourceId,
    content: report,
    trade_no: tradeNo,
    out_trade_no: outTradeNo,
    already_fulfilled: alreadyFulfilled,
    fulfillment_confirmed: true
  });
}

function normalizeAmount(value) {
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(String(value ?? '').trim());
  if (!match) return null;
  return `${BigInt(match[1]).toString()}.${(match[2] || '').padEnd(2, '0')}`;
}

function amountMatches(left, right) {
  const a = normalizeAmount(left);
  const b = normalizeAmount(right);
  return a !== null && b !== null && a === b;
}

module.exports = { createApp, RESOURCE_PATH };

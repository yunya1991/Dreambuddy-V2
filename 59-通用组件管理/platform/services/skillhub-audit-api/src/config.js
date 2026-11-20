'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');

const SANDBOX_GATEWAY = 'https://openapi-sandbox.dl.alipaydev.com/gateway.do';
const SANDBOX_SERVICE_ID = 'api_mock_service_id';

function readKey(value, envName) {
  if (!value) {
    throw new Error(`缺少环境变量 ${envName}`);
  }
  if (value.includes('BEGIN')) {
    return value;
  }
  if (fs.existsSync(value)) {
    return fs.readFileSync(value, 'utf8').trim();
  }
  return value.trim();
}

function normalizeKey(raw) {
  return raw
    .replace(/-----(BEGIN|END)[^-]+-----/g, '')
    .replace(/\s+/g, '');
}

function assertPrivateKey(pemLike) {
  const base64 = normalizeKey(pemLike);
  try {
    crypto.createPrivateKey({ key: Buffer.from(base64, 'base64'), format: 'der', type: 'pkcs1' });
    return 'pkcs1';
  } catch (_) {
    try {
      crypto.createPrivateKey({ key: Buffer.from(base64, 'base64'), format: 'der', type: 'pkcs8' });
      return 'pkcs8';
    } catch (_) {
      throw new Error('ALIPAY_PRIVATE_KEY 既不是有效 PKCS#1 也不是有效 PKCS#8 私钥');
    }
  }
}

function loadConfig(env = process.env) {
  const config = {
    port: Number(env.PORT || 8788),
    host: env.HOST || '127.0.0.1',
    dbPath: env.DB_PATH || '/var/lib/skillhub-audit/orders.db',
    price: env.PRICE_YUAN || '0.99',
    currency: 'CNY',
    goodsName: env.GOODS_NAME || 'Skill 上架体检报告',
    sellerName: env.SELLER_NAME || 'DreamBuddy',
    payWindowMinutes: Number(env.PAY_WINDOW_MINUTES || 30),
    resourceId: env.RESOURCE_ID || '/api/audit',
    appId: env.ALIPAY_APP_ID || '',
    sellerId: env.ALIPAY_SELLER_ID || '',
    serviceId: env.ALIPAY_SERVICE_ID || '',
    gateway: env.ALIPAY_GATEWAY || SANDBOX_GATEWAY,
    alipayPublicKey: '',
    privateKey: '',
    privateKeyType: ''
  };

  if (!/^\d+(\.\d{1,2})$/.test(config.price)) {
    throw new Error(`PRICE_YUAN 非法：${config.price}`);
  }
  const missing = ['ALIPAY_APP_ID', 'ALIPAY_SELLER_ID', 'ALIPAY_SERVICE_ID', 'ALIPAY_PRIVATE_KEY', 'ALIPAY_PUBLIC_KEY']
    .filter((name) => !env[name]);
  if (missing.length) {
    throw new Error(`缺少环境变量：${missing.join(', ')}`);
  }

  config.privateKey = readKey(env.ALIPAY_PRIVATE_KEY, 'ALIPAY_PRIVATE_KEY');
  config.alipayPublicKey = readKey(env.ALIPAY_PUBLIC_KEY, 'ALIPAY_PUBLIC_KEY');
  config.privateKeyType = assertPrivateKey(config.privateKey);

  config.sandboxExact = config.gateway === SANDBOX_GATEWAY && config.serviceId === SANDBOX_SERVICE_ID;

  config.data = buildDataResource(env, config);
  config.cogsteward = buildCogstewardResource(env, config);
  return config;
}

/** 认知管家体检资源（/api/cogsteward）：未配置 COGSTEWARD_PRICE_YUAN 时不挂载。 */
function buildCogstewardResource(env, base) {
  if (!env.COGSTEWARD_PRICE_YUAN) return null;
  const price = env.COGSTEWARD_PRICE_YUAN;
  if (!/^\d+(\.\d{1,2})$/.test(price)) {
    throw new Error(`COGSTEWARD_PRICE_YUAN 非法：${price}`);
  }
  return {
    resourceId: env.COGSTEWARD_RESOURCE_ID || '/api/cogsteward',
    price,
    goodsName: env.COGSTEWARD_GOODS_NAME || '认知管家·工作区体检报告',
    serviceId: env.COGSTEWARD_ALIPAY_SERVICE_ID || base.serviceId
  };
}

/** 数据服务资源（/api/data）：未配置 DATA_PRICE_YUAN 时不挂载。 */
function buildDataResource(env, base) {
  if (!env.DATA_PRICE_YUAN) return null;
  const price = env.DATA_PRICE_YUAN;
  if (!/^\d+(\.\d{1,2})$/.test(price)) {
    throw new Error(`DATA_PRICE_YUAN 非法：${price}`);
  }
  const timeouts = Number(env.PARTNER_TIMEOUT_MS || 45000);
  return {
    resourceId: env.DATA_RESOURCE_ID || '/api/data',
    price,
    goodsName: env.DATA_GOODS_NAME || '数据服务·单次取数',
    serviceId: env.DATA_ALIPAY_SERVICE_ID || base.serviceId,
    partnerBase: env.PARTNER_BASE || 'https://www.neodrm.com',
    partnerToken: env.PARTNER_TOKEN || '',
    timeoutMs: Number.isFinite(timeouts) && timeouts > 0 ? timeouts : 45000
  };
}

module.exports = { loadConfig, SANDBOX_GATEWAY, SANDBOX_SERVICE_ID };

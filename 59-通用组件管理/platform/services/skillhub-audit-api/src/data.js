'use strict';

/**
 * 数据服务资源：把已支付的请求转给只读数据网关（partner-gateway）。
 * 只做转发与白名单校验，不在本服务里做任何计算。
 */

const ALLOWED = {
  'market-data-hub': ['macro', 'filings', 'onchain'],
  'market-data-pro': ['macro', 'filings', 'onchain', 'quotes'],
  'event-context': ['events', 'event-context']
};

const MAX_PARAMS = 12;

function normalizeDataInput(body) {
  if (!body || typeof body !== 'object') {
    return { error: '请求体必须是 JSON 对象' };
  }
  const skill = String(body.skill || '').trim();
  const cmd = String(body.cmd || '').trim();
  if (!ALLOWED[skill]) {
    return { error: `skill 不支持：${skill || '(空)'}；可选 ${Object.keys(ALLOWED).join(' / ')}` };
  }
  if (!ALLOWED[skill].includes(cmd)) {
    return { error: `cmd 不支持：${cmd || '(空)'}；${skill} 可选 ${ALLOWED[skill].join(' / ')}` };
  }
  const raw = body.params && typeof body.params === 'object' ? body.params : {};
  const params = {};
  for (const [key, value] of Object.entries(raw)) {
    if (Object.keys(params).length >= MAX_PARAMS) break;
    if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,31}$/.test(key)) continue;
    if (value === null || value === undefined) continue;
    params[key] = String(value).slice(0, 300);
  }
  return { skill, cmd, params };
}

async function runDataQuery(input, resource) {
  const query = new URLSearchParams({ skill: input.skill, cmd: input.cmd, ...input.params });
  const url = `${resource.partnerBase.replace(/\/+$/, '')}/api/partner/v1/run?${query}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), resource.timeoutMs);
  try {
    const response = await fetch(url, {
      headers: { 'X-Partner-Token': resource.partnerToken, accept: 'application/json' },
      signal: controller.signal
    });
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch (_) {
      payload = { error: 'UPSTREAM_NOT_JSON', message: text.slice(0, 500) };
    }
    if (!response.ok) {
      throw Object.assign(new Error(payload.message || `上游返回 ${response.status}`), {
        code: payload.code || 'PARTNER_UPSTREAM',
        status: response.status
      });
    }
    return payload;
  } finally {
    clearTimeout(timer);
  }
}

module.exports = { ALLOWED, normalizeDataInput, runDataQuery };

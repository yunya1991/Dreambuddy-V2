'use strict';

/**
 * 认知管家体检报告资源（/api/cogsteward）。
 * 客户端只上传「指标 + 指针」（路径 / 大小 / 哈希 / 边数），不上传正文；
 * 本服务做基准对比与修复优先级排序，不落盘、不读用户文件。
 *
 * 指标口径唯一事实源：src/metrics-contract.json（与免费版 / Pro 版逐字节一致，
 * 由 scripts/release_check.py 校验）。调整阈值、权重、标签只改契约。
 */

const contract = require('./metrics-contract.json');

const METRICS = contract.metrics;
const METRIC_KEYS = METRICS.map((m) => m.key);
const RATIOS = contract.ratios;
const PROBLEM_KEYS = contract.problem_metrics;
const SCHEMA_VERSION = contract.schema_version;
const INVENTORY_KEYS = ['documents', 'skills', 'memories', 'sessions'];
const MODES = ['dev', 'office'];
const MAX_VALUE = 1000000;

function toCount(value) {
  if (value === undefined || value === null) return null;
  if (typeof value !== 'number' || !Number.isFinite(value)) return NaN;
  if (!Number.isInteger(value) || value < 0 || value > MAX_VALUE) return NaN;
  return value;
}

function normalizeCogstewardInput(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return { error: '请求体必须是 JSON 对象' };
  }

  const rawMetrics = body.metrics === undefined ? {} : body.metrics;
  if (!rawMetrics || typeof rawMetrics !== 'object' || Array.isArray(rawMetrics)) {
    return { error: 'metrics 必须是对象' };
  }

  const metrics = {};
  let provided = 0;
  for (const key of METRIC_KEYS) {
    if (rawMetrics[key] === undefined) continue;
    const n = toCount(rawMetrics[key]);
    if (Number.isNaN(n)) {
      return { error: `metrics.${key} 必须是非负整数（≤${MAX_VALUE}）` };
    }
    metrics[key] = n;
    provided += 1;
  }

  const rawInventory = body.inventory === undefined ? {} : body.inventory;
  if (!rawInventory || typeof rawInventory !== 'object' || Array.isArray(rawInventory)) {
    return { error: 'inventory 必须是对象' };
  }
  const inventory = {};
  for (const key of INVENTORY_KEYS) {
    if (rawInventory[key] === undefined) continue;
    const n = toCount(rawInventory[key]);
    if (Number.isNaN(n)) {
      return { error: `inventory.${key} 必须是非负整数（≤${MAX_VALUE}）` };
    }
    inventory[key] = n;
    provided += 1;
  }

  if (provided === 0) {
    return { error: '缺少可评估数据：metrics 或 inventory 至少提供一项' };
  }

  const mode = MODES.includes(body.mode) ? body.mode : 'dev';
  const notes = Array.isArray(body.notes)
    ? body.notes.filter((n) => typeof n === 'string').slice(0, 10).map((n) => n.slice(0, 200))
    : [];

  return { metrics, inventory, mode, notes };
}

function level(value, rule) {
  if (value >= rule.high_at) return 'high';
  if (value >= rule.warn_at) return 'warn';
  return 'ok';
}

function healthOf(metrics) {
  const problems = PROBLEM_KEYS.filter((key) => (metrics[key] || 0) > 0).length;
  const rules = contract.health;
  if (problems <= rules.ok_max_problems) return 'good';
  if (problems <= rules.attention_max_problems) return 'attention';
  return 'poor';
}

function buildCogstewardReport(input) {
  const findings = [];
  const benchmarks = [];
  let score = 100;

  for (const rule of METRICS) {
    if (input.metrics[rule.key] === undefined) continue;
    const value = input.metrics[rule.key];
    const state = level(value, rule);
    if (state === 'high') score -= rule.weight;
    else if (state === 'warn') score -= Math.round(rule.weight * 0.5);

    benchmarks.push({
      metric: rule.key,
      label: rule.label,
      value,
      warn_at: rule.warn_at,
      high_at: rule.high_at,
      status: state
    });

    if (state !== 'ok') {
      findings.push({
        id: rule.key,
        label: rule.label,
        priority: state === 'high' ? 'P0' : 'P1',
        value,
        threshold: `${rule.warn_at} / ${rule.high_at}`,
        action: rule.action
      });
    }
  }

  const ratios = buildRatios(input);
  const covered = new Set(findings.map((f) => f.id));
  for (const ratio of Object.values(ratios)) {
    if (!ratio || covered.has(ratio.metric)) continue;
    if (ratio.status === 'high' && ratio.weight) {
      score -= ratio.weight;
      findings.push({
        id: ratio.id,
        label: ratio.label,
        priority: 'P1',
        value: ratio.value,
        threshold: `${ratio.warn_at}% / ${ratio.high_at}%`,
        action: ratio.action
      });
    }
  }

  score = Math.max(0, Math.min(100, score));
  const grade = score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 60 ? 'C' : 'D';

  return {
    schema_version: SCHEMA_VERSION,
    command: 'cogsteward-report',
    mode: input.mode,
    generated_at: new Date().toISOString(),
    grade,
    score,
    health: healthOf(input.metrics),
    coverage: {
      orphan: input.metrics.orphan_files === undefined ? 'unavailable' : 'complete'
    },
    metrics: input.metrics,
    inventory: input.inventory,
    ratios,
    benchmarks,
    findings: findings.sort((a, b) => (a.priority === b.priority ? 0 : a.priority === 'P0' ? -1 : 1)).slice(0, 3),
    total_findings: findings.length,
    notes: input.notes,
    disclaimer: '仅基于客户端上报的指标与指针计算，不读取文档正文；比率在分母为 0 时留空。'
  };
}

function buildRatios(input) {
  const percent = (numerator, denominator) =>
    typeof numerator === 'number' && typeof denominator === 'number' && denominator > 0
      ? Math.round((numerator / denominator) * 10000) / 100
      : null;

  const result = {};
  for (const rule of RATIOS) {
    const value = percent(input.metrics[rule.metric], input.inventory[rule.denominator]);
    if (value === null) {
      result[rule.id] = null;
      continue;
    }
    result[rule.id] = {
      id: rule.id,
      label: rule.label,
      metric: rule.metric,
      value,
      warn_at: rule.warn_at,
      high_at: rule.high_at,
      weight: rule.weight,
      status: value >= rule.high_at ? 'high' : value >= rule.warn_at ? 'warn' : 'ok',
      informational: Boolean(rule.informational),
      action: rule.action
    };
  }
  return result;
}

module.exports = {
  METRICS,
  INVENTORY_KEYS,
  SCHEMA_VERSION,
  normalizeCogstewardInput,
  buildCogstewardReport
};

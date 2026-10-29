// ============================================
// 全局搜索数据源接入 — 四大模块 → SearchItem 归一化
// FAIL-OPEN：任一数据源失败不影响其他模块索引
// ============================================
import { getSearchIndex, type SearchItem } from './search-core';
import { reportsApi, type Report, type Briefing } from '@/lib/v3/api/reports';
import { configApi, type Strategy, type Channel, type ApiKeyItem } from '@/lib/v3/api/config';
import { notebookApi } from '@/lib/v3/api/notebook';
import { boardApi, type Proposal } from '@/lib/v3/api/board';
import api from '@/lib/api-client';

/** 研报域：Report + Briefing → report 模块 */
async function loadReports(): Promise<SearchItem[]> {
  const [reports, briefings] = await Promise.all([
    reportsApi.list().catch(() => [] as Report[]),
    reportsApi.getBriefings().catch(() => [] as Briefing[]),
  ]);
  const items: SearchItem[] = [];
  for (const r of reports) {
    items.push({
      id: `report:${r.id}`,
      moduleId: r.id,
      module: 'report',
      title: r.title || r.id,
      keywords: '研报 报告 report',
      href: '/dashboard/reports',
    });
  }
  for (const b of briefings) {
    items.push({
      id: `briefing:${b.id}`,
      moduleId: b.id,
      module: 'report',
      title: b.title || b.id,
      keywords: '简报 briefing',
      href: '/dashboard/reports',
    });
  }
  return items;
}

/** 配置域：Strategy/Channel/ApiKeyItem → strategy 模块 */
async function loadConfig(): Promise<SearchItem[]> {
  const [strategies, channels, apiKeys] = await Promise.all([
    configApi.listStrategies().catch(() => [] as Strategy[]),
    configApi.listChannels().catch(() => [] as Channel[]),
    configApi.listApiKeys().catch(() => [] as ApiKeyItem[]),
  ]);
  const items: SearchItem[] = [];
  for (const s of strategies) {
    items.push({
      id: `strategy:${s.id}`,
      moduleId: s.id,
      module: 'strategy',
      title: s.name || s.id,
      keywords: '策略 strategy 配置',
      href: '/dashboard/settings',
    });
  }
  for (const c of channels) {
    items.push({
      id: `channel:${c.id}`,
      moduleId: c.id,
      module: 'strategy',
      title: c.name || c.id,
      keywords: '渠道 channel 通知',
      href: '/dashboard/settings',
    });
  }
  for (const k of apiKeys) {
    items.push({
      id: `apikey:${k.id}`,
      moduleId: k.id,
      module: 'strategy',
      title: k.name || k.id,
      keywords: '密钥 api key',
      href: '/dashboard/settings',
    });
  }
  return items;
}

/** 治理域：Proposal → strategy 模块 */
async function loadBoard(): Promise<SearchItem[]> {
  const proposals = await boardApi.listProposals().catch(() => [] as Proposal[]);
  const items: SearchItem[] = [];
  for (const p of proposals) {
    items.push({
      id: `proposal:${p.id}`,
      moduleId: p.id,
      module: 'strategy',
      title: p.title || p.id,
      subtitle: [p.type, p.symbol, p.status].filter(Boolean).join(' · '),
      keywords: '提案 proposal 治理 治理提案',
      href: '/dashboard/governance',
    });
  }
  return items;
}

/** 笔记本域：任务列表 → memory 模块 */
async function loadNotebook(): Promise<SearchItem[]> {
  const tasks = await notebookApi.getTasks().catch(() => [] as unknown[]);
  const items: SearchItem[] = [];
  for (const t of tasks) {
    const task = t as Record<string, unknown>;
    const id = String(task.id ?? task.name ?? '');
    if (!id) continue;
    const title = String(task.title ?? task.name ?? id);
    items.push({
      id: `notebook:${id}`,
      moduleId: id,
      module: 'memory',
      title,
      keywords: '笔记本 notebook 任务 记忆',
      href: '/dashboard/notebook',
    });
  }
  return items;
}

/** 文档域：/api/docs/index（41 FIS 数据源，A2 桥接）→ doc 模块 */
async function loadDocs(): Promise<SearchItem[]> {
  const res = await api.get<{ docs?: Array<{ path: string; category?: string }> }>('/api/docs/index').catch(() => null);
  const docs = res?.docs ?? [];
  const items: SearchItem[] = [];
  for (const d of docs) {
    if (!d?.path) continue;
    const name = d.path.split('/').pop() || d.path;
    items.push({
      id: `doc:${d.path}`,
      moduleId: d.path,
      module: 'doc',
      title: name,
      subtitle: d.category || d.path,
      keywords: '文档 doc md 知识库',
      href: '/dashboard/monitor',
    });
  }
  return items;
}

/** 单次加载守卫：避免重复请求 */
let loadPromise: Promise<void> | null = null;

/**
 * 确保搜索索引已加载（幂等，可重复调用）
 * FAIL-OPEN：任一模块失败仅跳过该模块，不抛出异常
 */
export function ensureSearchLoaded(): Promise<void> {
  if (!loadPromise) {
    loadPromise = (async () => {
      const results = await Promise.allSettled([
        loadReports(),
        loadConfig(),
        loadBoard(),
        loadNotebook(),
        loadDocs(),
      ]);
      const items: SearchItem[] = [];
      for (const r of results) {
        if (r.status === 'fulfilled') items.push(...r.value);
      }
      getSearchIndex().replaceAll(items);
    })();
  }
  return loadPromise;
}

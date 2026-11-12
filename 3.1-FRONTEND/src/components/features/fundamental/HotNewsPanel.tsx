'use client';

import { Fragment, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { V3Card, V3Badge } from '@/components';
import { queryKey, queryStaleTime } from '@/lib/query-keys';
import { fetchModuleSnapshot } from './ModuleDetail';

// ============== 类型（39 hot_news.json 契约，SPEC-20261113 §5.1） ==============
interface HotNewsSentiment {
  score: number;
  confidence?: number | null;
  label: string;
}

interface HotNewsItem {
  rank: number;
  event_id?: string;
  title: string;
  title_short?: string;
  topic: string;
  event_type: string;
  symbols?: string[];
  sentiment?: HotNewsSentiment | null;
  importance: number;
  parts?: Record<string, number>;
  published_at?: string;
  origin?: string | null;
  source_url?: string | null;
  source_count?: number;
  dup_count?: number;
  recomputed?: boolean;
}

interface ThemeCluster {
  topic: string;
  label: string;
  count: number;
  avg_importance: number;
}

interface HotNewsSummary {
  total?: number;
  scored?: number;
  clusters?: number;
  dedup_saved?: number;
  high_impact?: number;
  avg_importance?: number;
  generated_at?: string;
  window_h?: number;
}

const TOPIC_LABELS: Record<string, string> = {
  rates_policy: '利率与央行',
  inflation: '通胀',
  labor: '就业',
  growth: '增长景气',
  crypto_reg: '加密监管',
  geopolitics: '地缘政治',
  earnings: '财报业绩',
  capital_action: '资本运作',
  tech_ai: '科技与 AI',
  commodities: '商品',
  other: '其他',
};

const PART_LABELS: Record<string, string> = {
  type: '类型',
  sentiment: '情绪',
  recency: '时效',
  source: '来源',
  corroboration: '印证',
};

// ============== 守卫与格式化 ==============
function asItems(v: unknown): HotNewsItem[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is HotNewsItem => !!x && typeof x === 'object' && typeof (x as HotNewsItem).title === 'string');
}

function asClusters(v: unknown): ThemeCluster[] {
  if (!Array.isArray(v)) return [];
  return v.filter((x): x is ThemeCluster => !!x && typeof x === 'object' && typeof (x as ThemeCluster).topic === 'string');
}

function asSummary(v: unknown): HotNewsSummary {
  return v && typeof v === 'object' ? (v as HotNewsSummary) : {};
}

function topicLabel(topic: string): string {
  return TOPIC_LABELS[topic] || topic || '其他';
}

function fmtImportance(n: number): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(1) : '--';
}

function fmtScore(n?: number | null): string {
  if (typeof n !== 'number' || !Number.isFinite(n)) return '--';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}`;
}

function fmtPart(n?: number): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(2) : '--';
}

function levelVariant(n: number): 'danger' | 'warning' | 'default' {
  if (n >= 70) return 'danger';
  if (n >= 50) return 'warning';
  return 'default';
}

function sentimentVariant(label?: string): 'success' | 'danger' | 'default' {
  if (label === '利好') return 'success';
  if (label === '利空') return 'danger';
  return 'default';
}

function relTime(iso?: string): string {
  if (!iso) return '--';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '--';
  const diff = Date.now() - t;
  if (diff < 0) return '刚刚';
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${Math.max(minutes, 1)} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

function absTime(iso?: string): string {
  if (!iso) return '--';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '--' : new Date(t).toLocaleString('zh-CN');
}

// ============== 子组件 ==============
function TitleCell({ item }: { item: HotNewsItem }) {
  const text = item.title_short || item.title;
  if (item.source_url) {
    return (
      <a
        href={item.source_url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-slate-200 hover:text-indigo-400 hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        {text}
      </a>
    );
  }
  return <span className="text-slate-200">{text}</span>;
}

function PartsRow({ parts }: { parts?: Record<string, number> }) {
  if (!parts) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-slate-500">
      {Object.keys(PART_LABELS).map((k) => (
        <span key={k}>
          {PART_LABELS[k]} <span className="text-slate-400">{fmtPart(parts[k])}</span>
        </span>
      ))}
    </div>
  );
}

// ============== 主面板 ==============
export function HotNewsPanel() {
  const [openId, setOpenId] = useState<string | null>(null);
  const { data, isFetching, isError, error, refetch } = useQuery({
    queryKey: queryKey('fundamental', 'module-snapshot', { module: 'news' }),
    queryFn: () => fetchModuleSnapshot('news'),
    staleTime: queryStaleTime('fundamental'),
  });

  const breakdown = data?.metrics?.breakdown ?? {};
  const items = asItems(breakdown.hot_news_top10);
  const clusters = asClusters(breakdown.theme_clusters);
  const summary = asSummary(breakdown.hot_news_summary);
  const top3 = items.slice(0, 3);
  const loading = isFetching && !data;
  const errorMsg = isError ? ((error as Error | null)?.message ?? '获取数据失败') : null;

  if (loading) {
    return (
      <V3Card padding="md">
        <p className="text-sm text-slate-500">加载新闻影响力榜中…</p>
      </V3Card>
    );
  }

  if (errorMsg && !data) {
    return (
      <V3Card padding="md">
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-rose-400">新闻影响力榜加载失败：{errorMsg}</p>
          <button
            onClick={() => void refetch()}
            className="px-3 py-1.5 rounded-lg text-xs bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30"
          >
            重试
          </button>
        </div>
      </V3Card>
    );
  }

  if (items.length === 0) {
    return (
      <V3Card padding="md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold text-slate-200">热点雷达 · 新闻影响力榜</p>
            <p className="text-[10px] text-slate-500 mt-0.5">
              近 24h 暂无可评分热点（39 语义流未产出或模型不可用）
            </p>
          </div>
          <button
            onClick={() => void refetch()}
            disabled={isFetching}
            className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-50"
          >
            {isFetching ? '刷新中…' : '刷新'}
          </button>
        </div>
      </V3Card>
    );
  }

  return (
    <V3Card padding="none" className="overflow-hidden">
      {/* 头部 */}
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-gray-700/30">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">热点雷达 · 新闻影响力榜</h3>
          <V3Badge variant="info" label={`${summary.window_h ?? 24}h`} />
        </div>
        <span className="text-[10px] text-slate-500">
          更新 {absTime(summary.generated_at)}
        </span>
      </div>

      <div className="px-4 py-2 border-b border-gray-700/20">
        <p className="text-[10px] text-slate-500">
          高影响 {summary.high_impact ?? 0} · 去重合并 {summary.dedup_saved ?? 0} · 事件{' '}
          {summary.total ?? items.length} · 主题 {clusters.length}
        </p>
      </div>

      {/* 关键事件卡 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 p-4 pb-2">
        {top3.map((item) => (
          <div key={`${item.event_id ?? item.rank}-card`} className="rounded-lg bg-slate-800/40 p-3 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <V3Badge variant={levelVariant(item.importance)} label={fmtImportance(item.importance)} />
              <span className="text-[10px] text-slate-500">{topicLabel(item.topic)}</span>
            </div>
            <p className="text-xs text-slate-200 line-clamp-2">{item.title_short || item.title}</p>
            <p className="text-[10px] text-slate-500">
              {item.sentiment?.label ?? '未知'} {fmtScore(item.sentiment?.score)} ·{' '}
              {item.source_count ?? 1} 源 · {relTime(item.published_at)}
            </p>
          </div>
        ))}
      </div>

      {/* Top10 表格（桌面） */}
      <div className="hidden md:block px-4 pb-2">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] text-slate-500 border-b border-gray-700/30">
              <th className="text-left font-normal py-1.5 w-8">#</th>
              <th className="text-left font-normal py-1.5">标题</th>
              <th className="text-left font-normal py-1.5 w-20">主题</th>
              <th className="text-left font-normal py-1.5 w-24">情绪</th>
              <th className="text-right font-normal py-1.5 w-16">影响度</th>
              <th className="text-right font-normal py-1.5 w-20">时间</th>
              <th className="text-right font-normal py-1.5 w-12">源数</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const key = `${item.event_id ?? item.rank}`;
              const expanded = openId === key;
              return (
                <Fragment key={key}>
                  <tr
                    className="border-b border-gray-800/40 hover:bg-slate-800/30 cursor-pointer"
                    onClick={() => setOpenId(expanded ? null : key)}
                  >
                    <td className="py-1.5 text-slate-500">{item.rank}</td>
                    <td className="py-1.5 pr-2">
                      <TitleCell item={item} />
                    </td>
                    <td className="py-1.5 text-slate-500">{topicLabel(item.topic)}</td>
                    <td className="py-1.5">
                      <span
                        className={
                          item.sentiment?.label === '利好'
                            ? 'text-emerald-400'
                            : item.sentiment?.label === '利空'
                              ? 'text-rose-400'
                              : 'text-slate-400'
                        }
                      >
                        {item.sentiment?.label ?? '未知'} {fmtScore(item.sentiment?.score)}
                      </span>
                    </td>
                    <td className="py-1.5 text-right">
                      <V3Badge variant={levelVariant(item.importance)} label={fmtImportance(item.importance)} />
                    </td>
                    <td className="py-1.5 text-right text-slate-500" title={absTime(item.published_at)}>
                      {relTime(item.published_at)}
                    </td>
                    <td className="py-1.5 text-right text-slate-500">{item.source_count ?? 1}</td>
                  </tr>
                  {expanded && (
                    <tr key={`${key}-parts`} className="bg-slate-800/20">
                      <td />
                      <td colSpan={6} className="py-1.5">
                        <PartsRow parts={item.parts} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* 移动端卡片列表 */}
      <div className="md:hidden px-4 pb-2 space-y-1.5">
        {items.map((item) => (
          <div key={`${item.event_id ?? item.rank}-m`} className="rounded-lg bg-slate-800/30 p-2.5 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] text-slate-500">
                #{item.rank} · {topicLabel(item.topic)}
              </span>
              <V3Badge variant={levelVariant(item.importance)} label={fmtImportance(item.importance)} />
            </div>
            <div className="text-xs">
              <TitleCell item={item} />
            </div>
            <p className="text-[10px] text-slate-500">
              <span
                className={
                  item.sentiment?.label === '利好'
                    ? 'text-emerald-400'
                    : item.sentiment?.label === '利空'
                      ? 'text-rose-400'
                      : 'text-slate-400'
                }
              >
                {item.sentiment?.label ?? '未知'} {fmtScore(item.sentiment?.score)}
              </span>{' '}
              · {item.source_count ?? 1} 源 · {relTime(item.published_at)}
            </p>
          </div>
        ))}
      </div>

      {/* 主题簇 chips */}
      {clusters.length > 0 && (
        <div className="px-4 py-2 border-t border-gray-700/20 flex flex-wrap gap-1.5">
          {clusters.map((c) => (
            <V3Badge key={c.topic} variant="default" label={`${c.label || topicLabel(c.topic)} ${c.count}`} />
          ))}
        </div>
      )}

      <div className="px-4 py-2 border-t border-gray-700/20 flex items-center justify-between gap-2">
        <span className="text-[10px] text-slate-600">
          数据源：39 语义蒸馏 · FinBERT(中文) · 启发式影响力评分（非预测）
        </span>
        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="px-3 py-1 rounded-lg text-[10px] bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-50"
        >
          {isFetching ? '刷新中…' : '刷新'}
        </button>
      </div>
    </V3Card>
  );
}

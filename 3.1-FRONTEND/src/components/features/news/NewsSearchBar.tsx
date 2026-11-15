'use client';

import { useRef, useState, type FormEvent } from 'react';
import { V3Card, V3Badge, IconSearch, IconClose } from '@/components';

// ============== 类型（exec_news_search 返回 items 契约） ==============
interface NewsSearchItem {
  ts?: string;
  title?: string;
  topic?: string;
  sentiment?: string | null;
  importance?: number | null;
  origin?: string | null;
  source_url?: string | null;
}

interface NewsSearchData {
  window_h?: number;
  source?: string;
  matched?: number;
  scanned?: number;
  coverage_note?: string | null;
  unclassified_ratio?: number | null;
  items?: NewsSearchItem[];
}

interface QueryResponse {
  ok: boolean;
  data?: {
    success?: boolean;
    intent?: string;
    handled?: boolean;
    degraded?: boolean;
    answer?: string;
    data?: NewsSearchData;
  } | null;
  error?: string;
}

// ============== 窗口配置（对齐 data_query_executor._NEWS_WINDOW_*） ==============
type WindowKey = '24h' | '7d' | '30d';

// windowWord 仅含时间词；"最近" 始终前置，因为它是 L1 event_listing 正则的
// 第二组触发词（有哪些/最近/今天…），缺失会导致 intent=unknown 被推给 L2。
const WINDOWS: { key: WindowKey; label: string; windowWord: string }[] = [
  { key: '24h', label: '24h', windowWord: '24小时' },
  { key: '7d', label: '7天', windowWord: '' },
  { key: '30d', label: '30天', windowWord: '30天' },
];

// ============== 与 HotNewsPanel 同源的轻量格式化（避免循环依赖） ==============
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

function topicLabel(topic?: string): string {
  if (!topic) return '其他';
  return TOPIC_LABELS[topic] || topic;
}

function fmtImportance(n?: number | null): string {
  return typeof n === 'number' && Number.isFinite(n) ? n.toFixed(1) : '--';
}

function levelVariant(n?: number | null): 'danger' | 'warning' | 'default' {
  if (typeof n !== 'number' || !Number.isFinite(n)) return 'default';
  if (n >= 70) return 'danger';
  if (n >= 50) return 'warning';
  return 'default';
}

function sentimentVariant(label?: string | null): 'success' | 'danger' | 'default' {
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

function fmtRatio(r?: number | null): string {
  return typeof r === 'number' && Number.isFinite(r) ? `${Math.round(r * 100)}%` : '--';
}

// 仅放行 http(s) 链接，避免 javascript: 等异常协议被渲染成可点击跳转
function safeHttpUrl(url?: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

// ============== 主组件 ==============
export function NewsSearchBar() {
  const [keyword, setKeyword] = useState('');
  const [window, setWindow] = useState<WindowKey>('7d');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<NewsSearchData | null>(null);
  const [answer, setAnswer] = useState<string | null>(null);
  // 用于中断进行中的检索请求（“x” 按钮）
  const abortRef = useRef<AbortController | null>(null);

  function buildMessage(kw: string, win: WindowKey): string {
    const w = WINDOWS.find((x) => x.key === win)!;
    const trimmed = kw.trim();
    // "最近" 是 event_listing 意图触发词，必须始终包含；
    // windowWord 叠加在 "最近" 后决定时间窗口（24小时/30天，空=默认7天）。
    const windowPart = w.windowWord ? `最近${w.windowWord}` : '最近';
    if (!trimmed) return `${windowPart}新闻`;
    return `${trimmed} ${windowPart}新闻`;
  }

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (loading) return;
    const message = buildMessage(keyword, window);
    if (!message) return;

    // 新一轮检索前先取消上一轮未完成的请求
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setLoading(true);
    setError(null);
    setResult(null);
    setAnswer(null);

    try {
      const resp = await fetch('/api/data/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const json = (await resp.json()) as QueryResponse;
      if (controller.signal.aborted) return;
      if (!json.ok || !json.data) {
        setError(json.error || '检索失败，请稍后重试');
        return;
      }
      setAnswer(json.data.answer ?? null);
      setResult(json.data.data ?? null);
    } catch (err) {
      // 主动中断不视为错误
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : '网络异常');
    } finally {
      // 仅当仍是当前请求时收尾，避免旧请求覆盖新一轮状态
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLoading(false);
      }
    }
  }

  // “x”：中断进行中的检索并清空输入/结果
  function handleCancel() {
    abortRef.current?.abort();
    abortRef.current = null;
    setKeyword('');
    setResult(null);
    setAnswer(null);
    setError(null);
    setLoading(false);
  }

  const items = result?.items ?? [];
  const matched = result?.matched ?? 0;
  const showCancel = loading || keyword.length > 0 || result !== null || error !== null;

  return (
    <V3Card padding="md" className="space-y-3">
      {/* 头部 */}
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-200">新闻检索</h3>
        <span className="text-[10px] text-slate-500">关键词 + 时间窗口 · 走 /api/data/query L1 路由</span>
      </div>

      {/* 搜索框 + 窗口 chips */}
      <form onSubmit={handleSubmit} className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="flex-1 relative">
            <IconSearch className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-600" />
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="输入关键词，如 以太坊 / 美联储 / CPI…"
              className={`w-full bg-slate-900/50 border border-slate-700/50 rounded-lg pl-8 ${
                showCancel ? 'pr-8' : 'pr-3'
              } py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-indigo-500/50`}
            />
            {showCancel && (
              <button
                type="button"
                onClick={handleCancel}
                aria-label={loading ? '停止检索' : '清空'}
                title={loading ? '停止检索' : '清空'}
                className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 flex items-center justify-center rounded-full text-slate-500 hover:text-slate-200 hover:bg-slate-700/50"
              >
                <IconClose className="w-3 h-3" />
              </button>
            )}
          </div>
          <button
            type="submit"
            disabled={loading}
            className="px-3 py-1.5 rounded-lg text-xs bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30 disabled:opacity-50"
          >
            {loading ? '检索中…' : '搜索'}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-slate-500 mr-1">窗口:</span>
          {WINDOWS.map((w) => (
            <button
              key={w.key}
              type="button"
              onClick={() => setWindow(w.key)}
              className={`px-2 py-0.5 rounded text-[10px] ${
                window === w.key
                  ? 'bg-indigo-600/20 text-indigo-400'
                  : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
      </form>

      {/* 错误态 */}
      {error && (
        <div className="rounded-lg bg-rose-900/10 border border-rose-500/20 px-3 py-2">
          <p className="text-xs text-rose-400">检索失败：{error}</p>
        </div>
      )}

      {/* 结果区 */}
      {result && (
        <div className="space-y-2">
          {/* 统计条 */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-slate-500">
            <span>命中 <span className="text-slate-300">{matched}</span> 条</span>
            <span>扫描 {result.scanned ?? 0} 条</span>
            <span>未分类 {fmtRatio(result.unclassified_ratio)}</span>
            <span>窗口 {result.window_h ?? '--'}h</span>
          </div>

          {/* 0 命中：展示 coverage_note */}
          {matched === 0 && (
            <div className="rounded-lg bg-slate-800/30 border border-slate-700/30 px-3 py-2 space-y-1">
              <p className="text-xs text-slate-400">{answer || '未检索到相关新闻'}</p>
              {result.coverage_note && (
                <p className="text-[10px] text-amber-400/80">注意：{result.coverage_note}</p>
              )}
            </div>
          )}

          {/* 结果列表 */}
          {matched > 0 && items.length > 0 && (
            <div className="space-y-1.5">
              {items.map((item, idx) => {
                const href = safeHttpUrl(item.source_url);
                return (
                  <div
                    key={`${item.ts ?? idx}-${idx}`}
                    className="rounded-lg bg-slate-800/30 border border-slate-700/20 p-2.5 space-y-1"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] text-slate-500">
                        #{idx + 1} · {topicLabel(item.topic)}
                      </span>
                      <V3Badge
                        variant={levelVariant(item.importance)}
                        label={fmtImportance(item.importance)}
                      />
                    </div>
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={`${item.title || ''}${item.origin ? ` · 来源：${item.origin}` : ''}`}
                        className="block text-xs text-slate-200 line-clamp-2 hover:text-indigo-400 hover:underline"
                      >
                        {item.title || '(无标题)'}
                      </a>
                    ) : (
                      <p className="text-xs text-slate-200 line-clamp-2">{item.title || '(无标题)'}</p>
                    )}
                    <p className="text-[10px] text-slate-500">
                      <span
                        className={
                          item.sentiment === '利好'
                            ? 'text-emerald-400'
                            : item.sentiment === '利空'
                              ? 'text-rose-400'
                              : 'text-slate-400'
                        }
                      >
                        {item.sentiment || '未知'}
                      </span>{' '}
                      · <span title={absTime(item.ts)}>{relTime(item.ts)}</span>
                    </p>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 空态提示 */}
      {!result && !error && !loading && (
        <p className="text-[10px] text-slate-600">输入关键词并选择时间窗口后点击搜索</p>
      )}
    </V3Card>
  );
}

export default NewsSearchBar;

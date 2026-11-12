'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  getSearchIndex,
  getRecentSearches,
  addRecentSearch,
  clearRecentSearches,
  type SearchModule,
  type SearchResultItem,
} from '@/lib/search/search-core';
import { ensureSearchLoaded } from '@/lib/search/search-data';
import {
  buildCommandItems,
  COMMAND_GROUP_LABELS,
  type CommandGroup,
  type CommandItem,
} from '@/lib/command-palette';
import { useAgentSessionStore } from '@/stores/agent-session-store';
import api from '@/lib/api-client';

/** 模块过滤 tab 定义 */
const MODULE_TABS: { key: SearchModule | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'report', label: '报告' },
  { key: 'strategy', label: '策略' },
  { key: 'memory', label: '记忆' },
  { key: 'doc', label: '文档' },
];

const GROUP_ORDER: CommandGroup[] = ['action', 'nav', 'session'];

interface GlobalSearchDialogProps {
  open: boolean;
  onClose: () => void;
}

export default function GlobalSearchDialog({ open, onClose }: GlobalSearchDialogProps) {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [moduleFilter, setModuleFilter] = useState<SearchModule | 'all'>('all');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [recent, setRecent] = useState<string[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  // 相似案例分区（阶段二 P1：case-retriever Soft Q 检索）
  const [similarCases, setSimilarCases] = useState<Array<{ id: string; title: string; score: number }>>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const agentSessions = useAgentSessionStore((s) => s.sessions);
  const hydrateSessions = useAgentSessionStore((s) => s.hydrate);
  const createAgentSession = useAgentSessionStore((s) => s.createSession);

  // T-B10：命令面板条目（导航 NAV_ITEMS + 最近会话 + 固定动作）
  const commandItems = useMemo(
    () =>
      buildCommandItems({
        query,
        sessions: agentSessions.map((s) => ({ id: s.id, title: s.title })),
      }),
    [query, agentSessions],
  );

  // 打开时聚焦输入框并加载最近搜索
  useEffect(() => {
    if (open) {
      // 打开时加载索引数据（幂等，仅首次请求）
      ensureSearchLoaded().catch(() => {});
      hydrateSessions();
      setQuery('');
      setModuleFilter('all');
      setActiveIndex(0);
      setRecent(getRecentSearches());
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open, hydrateSessions]);

  // 防抖搜索（200ms）
  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setSimilarCases([]);
      setActiveIndex(0);
      return;
    }
    // cancelled：query 变更/关闭时作废旧请求，避免慢响应覆盖新查询（相似案例错位）
    let cancelled = false;
    const timer = setTimeout(() => {
      const idx = getSearchIndex();
      const filter = moduleFilter === 'all' ? undefined : moduleFilter;
      setResults(idx.search(trimmed, 20, filter));
      setActiveIndex(0);
      // 并行请求相似案例（FAIL-OPEN：失败不影响本地结果）
      api.get<{ success: boolean; similarCases?: Array<{ id: string; title: string; score: number }> }>(
        `/api/search?query=${encodeURIComponent(trimmed)}&limit=5`,
      ).then((res) => {
        if (cancelled) return;
        setSimilarCases(Array.isArray(res?.similarCases) ? res.similarCases : []);
      }).catch(() => {
        if (!cancelled) setSimilarCases([]);
      });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, moduleFilter, open]);

  // 选中某条搜索结果：记录最近搜索并跳转
  const selectResult = (item: SearchResultItem) => {
    addRecentSearch(query.trim());
    onClose();
    router.push(item.href);
  };

  // 执行命令项：动作优先，其次跳转
  const runCommand = (item: CommandItem) => {
    addRecentSearch(query.trim());
    onClose();
    if (item.action === 'new-session') {
      const id = createAgentSession();
      router.push(`/dashboard/agent?session=${encodeURIComponent(id)}`);
      return;
    }
    if (item.href) router.push(item.href);
  };

  const totalItems = commandItems.length + results.length;

  // 键盘导航：↑↓ 移动、Enter 选中、Esc 关闭
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => (totalItems === 0 ? 0 : Math.min(i + 1, totalItems - 1)));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex < commandItems.length) {
        const item = commandItems[activeIndex];
        if (item) runCommand(item);
      } else if (results[activeIndex - commandItems.length]) {
        selectResult(results[activeIndex - commandItems.length]);
      }
    }
  };

  if (!open) return null;

  const hasQuery = query.trim().length > 0;

  const renderCommandList = () => {
    const groups = GROUP_ORDER.map((group) => ({
      group,
      items: commandItems.filter((item) => item.group === group),
    })).filter((g) => g.items.length > 0);
    if (groups.length === 0) return null;
    let cursor = 0;
    return groups.map(({ group, items }) => (
      <div key={group} className="border-b border-slate-800 last:border-b-0">
        <div className="px-4 pt-2 pb-1 text-[10px] uppercase tracking-wider text-slate-600">
          {COMMAND_GROUP_LABELS[group]}
        </div>
        {items.map((item) => {
          const index = cursor++;
          return (
            <button
              key={item.id}
              onClick={() => runCommand(item)}
              onMouseEnter={() => setActiveIndex(index)}
              data-testid={`command-item-${item.id}`}
              className={`w-full text-left px-4 py-2 flex items-center gap-3 transition-colors ${
                index === activeIndex ? 'bg-slate-800' : 'hover:bg-slate-800/50'
              }`}
            >
              <span className="flex-1 min-w-0 truncate text-sm text-slate-200">{item.label}</span>
              {item.hint && <span className="text-[10px] text-slate-600 shrink-0">{item.hint}</span>}
            </button>
          );
        })}
      </div>
    ));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[10vh]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl mx-4 rounded-xl bg-slate-900 border border-slate-700 shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* 输入区 */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800">
          <span className="text-slate-500 text-sm">🔍</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索或跳转：报告、策略、记忆、文档、导航…（↑↓ 选择，Enter 打开，Esc 关闭）"
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 outline-none"
          />
          <kbd className="text-[10px] text-slate-600 border border-slate-700 rounded px-1.5 py-0.5">ESC</kbd>
        </div>

        {/* 模块过滤 tab */}
        <div className="flex items-center gap-1 px-3 py-2 border-b border-slate-800 overflow-x-auto">
          {MODULE_TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setModuleFilter(tab.key)}
              className={`px-2.5 py-1 rounded-md text-[11px] whitespace-nowrap transition-colors ${
                moduleFilter === tab.key
                  ? 'bg-indigo-600/30 text-indigo-300'
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* 内容区：命令分组 + 搜索结果；无查询时显示最近搜索 */}
        <div className="max-h-[50vh] overflow-y-auto">
          {renderCommandList()}

          {hasQuery ? (
            results.length > 0 ? (
              results.map((item, i) => {
                const index = commandItems.length + i;
                return (
                  <button
                    key={item.id}
                    onClick={() => selectResult(item)}
                    onMouseEnter={() => setActiveIndex(index)}
                    className={`w-full text-left px-4 py-2.5 flex items-center gap-3 transition-colors ${
                      index === activeIndex ? 'bg-slate-800' : 'hover:bg-slate-800/50'
                    }`}
                  >
                    <span className="text-xs text-slate-500 w-10 flex-shrink-0">{MODULE_TABS.find((t) => t.key === item.module)?.label ?? item.module}</span>
                    <span className="flex-1 min-w-0">
                      <span className="block text-sm text-slate-200 truncate" dangerouslySetInnerHTML={{ __html: item.highlight }} />
                      {item.subtitle && <span className="block text-[11px] text-slate-500 truncate">{item.subtitle}</span>}
                    </span>
                    <span className="text-[10px] text-slate-600 flex-shrink-0">{item.score.toFixed(1)}</span>
                  </button>
                );
              })
            ) : commandItems.length === 0 ? (
              <div className="px-4 py-8 text-center text-xs text-slate-600">没有匹配的结果</div>
            ) : null
          ) : recent.length > 0 ? (
            <div className="px-4 py-3 border-t border-slate-800">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] text-slate-600 uppercase tracking-wider">最近搜索</span>
                <button onClick={() => { clearRecentSearches(); setRecent([]); }} className="text-[10px] text-slate-600 hover:text-slate-400">清除</button>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {recent.map((q) => (
                  <button
                    key={q}
                    onClick={() => setQuery(q)}
                    className="px-2 py-1 rounded-md bg-slate-800 text-[11px] text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {hasQuery && similarCases.length > 0 && (
            <div className="border-t border-slate-800 px-4 py-3">
              <div className="text-[10px] text-slate-600 uppercase tracking-wider mb-2">相似案例（Soft Q 检索）</div>
              {similarCases.map((c) => (
                <div key={c.id} className="flex items-center gap-2 py-1">
                  <span className="flex-1 text-xs text-slate-400 truncate">{c.title}</span>
                  <span className="text-[10px] text-indigo-500/70 flex-shrink-0">Q={c.score.toFixed(2)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

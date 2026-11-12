'use client';

// ============================================
// 交易榜单 — 固定专题页
// Top10 列表 + 决策卡 + 品类筛选 + 一键入场
// REFACTOR: 通过 /api/trading-ranking/today 获取真实数据，API 不可用时降级到 mock
// ============================================

import { useState, Suspense } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RankingCard } from '@/components/features/ranking/RankingCard';
import { PrefillOrderBanner } from '@/components/features/ranking/PrefillOrderBanner';
import { RankingMonitor } from '@/components/features/ranking/RankingMonitor';
import { mockRankingItems, mockMonitorMetrics, type CategoryType, type TradingRankingItem, type RankingMonitorMetrics } from '@/components/features/ranking/types';
import { fetchTradingRanking } from '@/lib/v3/api/ranking';
import { queryKey, queryStaleTime } from '@/lib/query-keys';

const filters: { key: 'all' | CategoryType; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'crypto', label: '加密货币' },
  { key: 'commodity', label: '大宗商品' },
  { key: 'index', label: '美股/指数' },
];

export default function RankingPage() {
  const [filter, setFilter] = useState<'all' | CategoryType>('all');

  // 接口不可用/返回空时保持 mock 降级（queryFn 返回 null）
  const rankingQuery = useQuery({
    queryKey: queryKey('ranking', 'today'),
    queryFn: fetchTradingRanking,
    staleTime: queryStaleTime('ranking'),
  });

  const apiItems = rankingQuery.data?.items?.length
    ? (rankingQuery.data.items as TradingRankingItem[])
    : null;
  const items = apiItems ?? mockRankingItems;
  const metrics = (rankingQuery.data?.metrics as RankingMonitorMetrics | null) ?? mockMonitorMetrics;
  const loading = rankingQuery.isLoading;
  const dataSource: 'api' | 'mock' = apiItems ? 'api' : 'mock';

  const filtered = filter === 'all'
    ? items
    : items.filter(item => item.category === filter);

  return (
    <div className="p-4 max-w-4xl mx-auto">
      {/* 标题 */}
      <div className="mb-4">
        <h1 className="text-lg font-bold text-slate-200">今日十大交易机会</h1>
        <p className="text-xs text-slate-500">
          每日 08:00 更新 · 五维评分（技术 30% + 基本面 25% + 链上 20% + 情绪 15% + 事件 10%）
          {dataSource === 'mock' && !loading && (
            <span className="ml-2 text-amber-500/70">（演示数据）</span>
          )}
        </p>
      </div>

      {/* 预填订单 Banner（URL 含 symbol/entry 时显示） */}
      <div className="mb-3">
        <Suspense fallback={null}>
          <PrefillOrderBanner />
        </Suspense>
      </div>

      {/* 监控指标看板 */}
      <div className="mb-4">
        <RankingMonitor metrics={metrics} />
      </div>

      {/* 品类筛选 */}
      <div className="flex gap-2 mb-3">
        {filters.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
              filter === f.key
                ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/30'
                : 'bg-slate-800/50 text-slate-400 hover:text-slate-300 border border-transparent'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Top10 列表 */}
      <div className="space-y-2">
        {loading ? (
          <div className="text-center py-8 text-slate-500 text-xs">加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-xs">该品类暂无推荐</div>
        ) : (
          filtered.map(item => (
            <RankingCard key={`${item.rank}-${item.symbol}`} item={item} />
          ))
        )}
      </div>

      {/* 底部说明 */}
      <div className="mt-6 pt-4 border-t border-slate-800">
        <p className="text-[10px] text-slate-600 text-center">
          评分基于多因子模型 · 仅供参考，不构成投资建议 · 请根据自身风险承受能力决策
        </p>
      </div>
    </div>
  );
}

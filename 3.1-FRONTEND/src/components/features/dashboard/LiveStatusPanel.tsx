'use client';

/**
 * F5: 实时仪表盘状态面板
 *
 * 展示 DreamOS 系统实时状态:
 * - 产物中台统计 (调用 /api/artifacts?stats=1)
 * - 系统运行状态 (模拟)
 * - 自动刷新 (30s)
 */

import { useEffect, useState } from 'react';
import { V3Card, V3Badge, V3StatusDot } from '@/components';

interface ArtifactStats {
  total: number;
  by_type: Record<string, number>;
  total_size_bytes: number;
}

export function LiveStatusPanel() {
  const [stats, setStats] = useState<ArtifactStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>('');

  const fetchStats = async () => {
    try {
      // TODO: migrate to domain client — query param ?stats=1 not supported by artifactApi.list()
      const resp = await fetch('/api/artifacts?stats=1');
      const body = await resp.json();
      if (body.success) {
        setStats(body.stats);
        setLastUpdate(new Date().toLocaleTimeString());
      }
    } catch {
      // FAIL-OPEN: 静默失败
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStats();
    const timer = setInterval(fetchStats, 30000); // 30s 自动刷新
    return () => clearInterval(timer);
  }, []);

  const typeLabels: Record<string, string> = {
    insight_card: '洞察卡',
    mood_board: '情绪板',
    bull_bear_debate: '多空辩论',
    briefing: '盘前简报',
    report: '报告',
    chart: '图表',
  };

  const sizeKB = stats ? (stats.total_size_bytes / 1024).toFixed(1) : '0';

  return (
    <V3Card padding="md">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <V3StatusDot status="success" pulse />
          <span className="text-sm font-semibold text-slate-200">系统实时状态</span>
        </div>
        <span className="text-[10px] text-slate-500">
          {loading ? '加载中...' : `更新于 ${lastUpdate}`}
        </span>
      </div>

      {/* 产物统计 */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="rounded-lg bg-slate-800/50 p-2 text-center">
          <div className="text-lg font-bold text-emerald-400">
            {stats?.total ?? 0}
          </div>
          <div className="text-[10px] text-slate-500">产物总数</div>
        </div>
        <div className="rounded-lg bg-slate-800/50 p-2 text-center">
          <div className="text-lg font-bold text-cyan-400">
            {Object.keys(stats?.by_type ?? {}).filter(
              (k) => (stats?.by_type[k] ?? 0) > 0
            ).length}
          </div>
          <div className="text-[10px] text-slate-500">活跃类型</div>
        </div>
        <div className="rounded-lg bg-slate-800/50 p-2 text-center">
          <div className="text-lg font-bold text-amber-400">{sizeKB}</div>
          <div className="text-[10px] text-slate-500">存储 (KB)</div>
        </div>
      </div>

      {/* 各类型产物 */}
      {stats && (
        <div className="space-y-1">
          {Object.entries(stats.by_type).map(([type, count]) => (
            <div key={type} className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">{typeLabels[type] || type}</span>
              <span className={`font-mono ${count > 0 ? 'text-slate-200' : 'text-slate-600'}`}>
                {count}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 系统状态 */}
      <div className="mt-3 pt-3 border-t border-slate-700/40">
        <div className="grid grid-cols-2 gap-2 text-[10px]">
          <div className="flex items-center gap-1">
            <V3StatusDot status="success" size="sm" />
            <span className="text-slate-400">Python Server</span>
          </div>
          <div className="flex items-center gap-1">
            <V3StatusDot status="success" size="sm" />
            <span className="text-slate-400">GraphStore</span>
          </div>
          <div className="flex items-center gap-1">
            <V3StatusDot status="success" size="sm" />
            <span className="text-slate-400">Cognitive</span>
          </div>
          <div className="flex items-center gap-1">
            <V3StatusDot status="success" size="sm" />
            <span className="text-slate-400">Artifact Store</span>
          </div>
        </div>
      </div>
    </V3Card>
  );
}

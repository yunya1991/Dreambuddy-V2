'use client';

import { useEffect, useState } from 'react';
import { opsApi } from '@/lib/v3/api';

interface QueueStats {
  total_tasks: number;
  pending_tasks: number;
  processing_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  avg_latency_ms: number;
  queue_depth_by_department: Record<string, number>;
  items?: QueueItem[];
}

interface QueueItem {
  task_id: string;
  trace_id: string;
  created_at: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  department: string;
  workflow_type: string;
}

interface DecisionLevel {
  level: string;
  label: string;
  description: string;
  requires_board_approval: boolean;
  auto_threshold: number;
}

// Dev-mode fallback so the panel renders meaningful data when Hub is offline.
const MOCK_STATS: QueueStats = {
  total_tasks: 128,
  pending_tasks: 12,
  processing_tasks: 5,
  completed_tasks: 108,
  failed_tasks: 3,
  avg_latency_ms: 246,
  queue_depth_by_department: { research: 4, trading: 7, risk: 2, ops: 3 },
  items: [
    { task_id: 'tsk-8f3a9c1b2d4e5f6a', trace_id: 'trc-001', created_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(), status: 'processing', department: 'trading', workflow_type: 'signal_execution' },
    { task_id: 'tsk-1a2b3c4d5e6f7a8b', trace_id: 'trc-002', created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(), status: 'pending', department: 'research', workflow_type: 'factor_backtest' },
    { task_id: 'tsk-9c8d7e6f5a4b3c2d', trace_id: 'trc-003', created_at: new Date(Date.now() - 1000 * 60 * 9).toISOString(), status: 'completed', department: 'risk', workflow_type: 'portfolio_rebalance' },
    { task_id: 'tsk-4d5e6f7a8b9c0d1e', trace_id: 'trc-004', created_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(), status: 'failed', department: 'ops', workflow_type: 'data_pipeline' },
  ],
};

const MOCK_LEVELS: DecisionLevel[] = [
  { level: 'L1', label: '常规决策', description: '低风险常规操作，系统自动执行', requires_board_approval: false, auto_threshold: 10000 },
  { level: 'L2', label: '重要决策', description: '中等风险操作，需主管审批', requires_board_approval: false, auto_threshold: 100000 },
  { level: 'L3', label: '重大决策', description: '高风险操作，需董事会审批', requires_board_approval: true, auto_threshold: 1000000 },
];

export default function OpsPage() {
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [levels, setLevels] = useState<DecisionLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState(5);
  const [usingMock, setUsingMock] = useState(false);

  async function fetchData() {
    try {
      const [statsData, levelsData] = await Promise.all([
        opsApi.getQueues(),
        opsApi.getDecisionLevels(),
      ]);

      if (statsData) {
        const stats = statsData as unknown as QueueStats;
        setStats(stats);
        setItems(stats.items ?? []);
      } else {
        throw new Error('stats_unavailable');
      }
      setLevels((levelsData as unknown as DecisionLevel[]) ?? []);
      setUsingMock(false);
      setError(null);
    } catch (e) {
      // Dev fallback: render mock data so the panel stays usable.
      setStats(MOCK_STATS);
      setItems(MOCK_STATS.items ?? []);
      setLevels(MOCK_LEVELS);
      setUsingMock(true);
      setError(e instanceof Error ? e.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, refreshInterval * 1000);
    return () => clearInterval(interval);
  }, [refreshInterval]);

  if (loading && !stats) {
    return (
      <div className="p-6 text-slate-100">
        <div className="animate-pulse">
          <div className="h-8 bg-slate-800 rounded w-48 mb-6"></div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {[1, 2, 3, 4, 5].map(i => (
              <div key={i} className="h-24 bg-slate-800 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 text-slate-100 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">运维监控台</h1>
          <p className="text-slate-400 mt-1 text-sm">队列状态 · 任务监控 · 决策分级</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-slate-400 text-sm">自动刷新:</label>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value))}
            className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-slate-100 text-sm"
          >
            <option value={5}>5秒</option>
            <option value={10}>10秒</option>
            <option value={30}>30秒</option>
            <option value={60}>1分钟</option>
          </select>
          <button
            onClick={fetchData}
            className="bg-indigo-600 hover:bg-indigo-700 px-4 py-1.5 rounded text-sm transition-colors"
          >
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-900/40 border border-red-800 rounded-lg p-4">
          <p className="text-red-300 text-sm">
            {error}
            {usingMock && <span className="ml-2 text-red-400/80">（已加载模拟数据）</span>}
          </p>
        </div>
      )}

      {/* Queue Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <StatCard title="总任务数" value={stats?.total_tasks ?? 0} color="slate" />
        <StatCard title="待处理" value={stats?.pending_tasks ?? 0} color="amber" />
        <StatCard title="处理中" value={stats?.processing_tasks ?? 0} color="blue" />
        <StatCard title="已完成" value={stats?.completed_tasks ?? 0} color="emerald" />
        <StatCard title="失败" value={stats?.failed_tasks ?? 0} color="red" />
      </div>

      {/* Performance & Department */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
          <h3 className="text-lg font-semibold text-slate-200 mb-4">系统性能</h3>
          <div className="flex justify-between items-center">
            <span className="text-slate-400">平均延迟</span>
            <span className="text-2xl font-bold text-slate-100">
              {stats?.avg_latency_ms ?? 0} <span className="text-sm text-slate-500">ms</span>
            </span>
          </div>
        </div>
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
          <h3 className="text-lg font-semibold text-slate-200 mb-4">部门队列深度</h3>
          <div className="space-y-3">
            {Object.entries(stats?.queue_depth_by_department ?? {}).map(([dept, count]) => (
              <div key={dept} className="flex justify-between items-center">
                <span className="text-slate-400 capitalize w-20">{dept}</span>
                <div className="flex items-center gap-3 flex-1 ml-4">
                  <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500"
                      style={{ width: `${Math.min(100, (count / (stats?.total_tasks || 1)) * 100)}%` }}
                    />
                  </div>
                  <span className="text-slate-200 font-bold w-8 text-right">{count}</span>
                </div>
              </div>
            ))}
            {Object.keys(stats?.queue_depth_by_department ?? {}).length === 0 && (
              <p className="text-slate-500 text-sm">暂无数据</p>
            )}
          </div>
        </div>
      </div>

      {/* Decision Levels */}
      <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">决策分级 (L1/L2/L3)</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {levels.map((level) => (
            <div
              key={level.level}
              className={`rounded-lg p-4 border ${
                level.level === 'L1' ? 'border-emerald-800 bg-emerald-950/30' :
                level.level === 'L2' ? 'border-amber-800 bg-amber-950/30' :
                'border-red-800 bg-red-950/30'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xl font-bold ${
                  level.level === 'L1' ? 'text-emerald-400' :
                  level.level === 'L2' ? 'text-amber-400' :
                  'text-red-400'
                }`}>{level.level}</span>
                <span className="text-slate-100 font-semibold">{level.label}</span>
              </div>
              <p className="text-sm text-slate-400 mb-2">{level.description}</p>
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <span>阈值: ${level.auto_threshold.toLocaleString()}</span>
                {level.requires_board_approval && (
                  <span className="text-red-400">⚠️ 需审批</span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Queue Items Table */}
      <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
        <h3 className="text-lg font-semibold text-slate-200 mb-4">队列项目 (最新20条)</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-800">
                <th className="text-left py-2 px-3 font-medium">任务ID</th>
                <th className="text-left py-2 px-3 font-medium">状态</th>
                <th className="text-left py-2 px-3 font-medium">部门</th>
                <th className="text-left py-2 px-3 font-medium">工作流类型</th>
                <th className="text-left py-2 px-3 font-medium">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.task_id} className="border-b border-slate-800 hover:bg-slate-800/40">
                  <td className="py-2 px-3 font-mono text-xs text-slate-300">
                    {item.task_id.length > 16 ? `${item.task_id.substring(0, 16)}...` : item.task_id}
                  </td>
                  <td className="py-2 px-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="py-2 px-3 text-slate-300 capitalize">{item.department}</td>
                  <td className="py-2 px-3 text-slate-300">{item.workflow_type}</td>
                  <td className="py-2 px-3 text-slate-500">
                    {new Date(item.created_at).toLocaleString('zh-CN')}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-slate-500">
                    暂无队列项目
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ title, value, color }: {
  title: string;
  value: number;
  color: 'slate' | 'amber' | 'blue' | 'emerald' | 'red';
}) {
  const colorMap: Record<string, string> = {
    slate: 'bg-slate-800 border-slate-700 text-slate-100',
    amber: 'bg-amber-950/50 border-amber-800 text-amber-400',
    blue: 'bg-blue-950/50 border-blue-800 text-blue-400',
    emerald: 'bg-emerald-950/50 border-emerald-800 text-emerald-400',
    red: 'bg-red-950/50 border-red-800 text-red-400',
  };
  return (
    <div className={`rounded-lg p-4 border ${colorMap[color]}`}>
      <div className="text-3xl font-bold">{value}</div>
      <div className="text-sm mt-1 text-slate-400">{title}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const style: Record<string, string> = {
    pending: 'bg-amber-950/50 text-amber-400 border-amber-800',
    processing: 'bg-blue-950/50 text-blue-400 border-blue-800',
    completed: 'bg-emerald-950/50 text-emerald-400 border-emerald-800',
    failed: 'bg-red-950/50 text-red-400 border-red-800',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${style[status] || style.pending}`}>
      {status}
    </span>
  );
}

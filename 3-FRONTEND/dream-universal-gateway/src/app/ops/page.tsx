'use client';

import { useEffect, useState } from 'react';

interface QueueStats {
  total_tasks: number;
  pending_tasks: number;
  processing_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  avg_latency_ms: number;
  queue_depth_by_department: Record<string, number>;
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

export default function OpsPage() {
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [items, setItems] = useState<QueueItem[]>([]);
  const [levels, setLevels] = useState<DecisionLevel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState(5);

  async function fetchData() {
    try {
      const [statsRes, itemsRes, levelsRes] = await Promise.all([
        fetch('/api/ops/queues'),
        fetch('/api/ops/queues/items?limit=20'),
        fetch('/api/ops/decision-levels'),
      ]);
      const statsData = await statsRes.json();
      const itemsData = await itemsRes.json();
      const levelsData = await levelsRes.json();
      if (statsData.success) setStats(statsData.data);
      if (itemsData.success) setItems(itemsData.data);
      if (levelsData.success) setLevels(levelsData.data);
      setError(null);
    } catch (e) {
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
      <div className="min-h-screen bg-gray-950 text-white p-8">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-800 rounded w-48 mb-6"></div>
          <div className="grid grid-cols-4 gap-4">
            {[1,2,3,4].map(i => (
              <div key={i} className="h-24 bg-gray-800 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white p-8">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">运维监控台</h1>
          <p className="text-gray-400 mt-1">队列状态 · 任务监控 · 决策分级</p>
        </div>
        <div className="flex items-center gap-4">
          <label className="text-gray-400 text-sm">自动刷新:</label>
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value))}
            className="bg-gray-800 border border-gray-700 rounded px-3 py-1 text-white text-sm"
          >
            <option value={5}>5秒</option>
            <option value={10}>10秒</option>
            <option value={30}>30秒</option>
            <option value={60}>1分钟</option>
          </select>
          <button
            onClick={fetchData}
            className="bg-blue-600 hover:bg-blue-700 px-4 py-1 rounded text-sm"
          >
            刷新
          </button>
        </div>
      </header>

      {error && (
        <div className="bg-red-900/50 border border-red-700 rounded p-4 mb-6">
          <p className="text-red-300">{error}</p>
        </div>
      )}

      {/* Queue Stats Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-8">
        <StatCard title="总任务数" value={stats?.total_tasks ?? 0} color="gray" />
        <StatCard title="待处理" value={stats?.pending_tasks ?? 0} color="yellow" />
        <StatCard title="处理中" value={stats?.processing_tasks ?? 0} color="blue" />
        <StatCard title="已完成" value={stats?.completed_tasks ?? 0} color="green" />
        <StatCard title="失败" value={stats?.failed_tasks ?? 0} color="red" />
      </div>

      {/* Performance & Department */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-semibold text-gray-300 mb-4">系统性能</h3>
          <div className="flex justify-between items-center">
            <span className="text-gray-400">平均延迟</span>
            <span className="text-2xl font-bold text-white">
              {stats?.avg_latency_ms ?? 0} <span className="text-sm text-gray-500">ms</span>
            </span>
          </div>
        </div>
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-semibold text-gray-300 mb-4">部门队列深度</h3>
          <div className="space-y-2">
            {Object.entries(stats?.queue_depth_by_department ?? {}).map(([dept, count]) => (
              <div key={dept} className="flex justify-between items-center">
                <span className="text-gray-400 capitalize">{dept}</span>
                <div className="flex items-center gap-2">
                  <div className="w-24 h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-600"
                      style={{ width: `${Math.min(100, (count / (stats?.total_tasks || 1)) * 100)}%` }}
                    />
                  </div>
                  <span className="text-gray-200 font-bold">{count}</span>
                </div>
              </div>
            ))}
            {Object.keys(stats?.queue_depth_by_department ?? {}).length === 0 && (
              <p className="text-gray-500 text-sm">暂无数据</p>
            )}
          </div>
        </div>
      </div>

      {/* Decision Levels */}
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800 mb-8">
        <h3 className="text-lg font-semibold text-gray-300 mb-4">决策分级 (L1/L2/L3)</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {levels.map((level) => (
            <div
              key={level.level}
              className={`rounded-lg p-4 border ${
                level.level === 'L1' ? 'border-green-700 bg-green-950/30' :
                level.level === 'L2' ? 'border-yellow-700 bg-yellow-950/30' :
                'border-red-700 bg-red-950/30'
              }`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={`text-xl font-bold ${
                  level.level === 'L1' ? 'text-green-400' :
                  level.level === 'L2' ? 'text-yellow-400' :
                  'text-red-400'
                }`}>{level.level}</span>
                <span className="text-white font-semibold">{level.label}</span>
              </div>
              <p className="text-sm text-gray-400 mb-2">{level.description}</p>
              <div className="flex items-center gap-2 text-xs text-gray-500">
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
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h3 className="text-lg font-semibold text-gray-300 mb-4">队列项目 (最新20条)</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-gray-400 border-b border-gray-800">
                <th className="text-left py-2 px-3">任务ID</th>
                <th className="text-left py-2 px-3">状态</th>
                <th className="text-left py-2 px-3">部门</th>
                <th className="text-left py-2 px-3">工作流类型</th>
                <th className="text-left py-2 px-3">创建时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.task_id} className="border-b border-gray-800 hover:bg-gray-800/50">
                  <td className="py-2 px-3 font-mono text-xs text-gray-300">
                    {item.task_id.substring(0, 16)}...
                  </td>
                  <td className="py-2 px-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="py-2 px-3 text-gray-300 capitalize">{item.department}</td>
                  <td className="py-2 px-3 text-gray-300">{item.workflow_type}</td>
                  <td className="py-2 px-3 text-gray-500">
                    {new Date(item.created_at).toLocaleString('zh-CN')}
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-gray-500">
                    暂无队列项目
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Navigation */}
      <div className="mt-8 flex gap-4">
        <a href="/board" className="text-blue-400 hover:text-blue-300 text-sm">
          ← 返回董事会总览台
        </a>
        <a href="/board/proposals" className="text-blue-400 hover:text-blue-300 text-sm">
          提案管理 →
        </a>
      </div>
    </div>
  );
}

function StatCard({ title, value, color }: {
  title: string;
  value: number;
  color: 'gray' | 'yellow' | 'blue' | 'green' | 'red';
}) {
  const colorMap = {
    gray: 'bg-gray-800 border-gray-700 text-white',
    yellow: 'bg-yellow-950/50 border-yellow-700 text-yellow-400',
    blue: 'bg-blue-950/50 border-blue-700 text-blue-400',
    green: 'bg-green-950/50 border-green-700 text-green-400',
    red: 'bg-red-950/50 border-red-700 text-red-400',
  };
  return (
    <div className={`rounded-lg p-4 border ${colorMap[color]}`}>
      <div className="text-3xl font-bold">{value}</div>
      <div className="text-sm mt-1 text-gray-400">{title}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const style = {
    pending: 'bg-yellow-950/50 text-yellow-400 border-yellow-700',
    processing: 'bg-blue-950/50 text-blue-400 border-blue-700',
    completed: 'bg-green-950/50 text-green-400 border-green-700',
    failed: 'bg-red-950/50 text-red-400 border-red-700',
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${style[status as keyof typeof style] || style.pending}`}>
      {status}
    </span>
  );
}

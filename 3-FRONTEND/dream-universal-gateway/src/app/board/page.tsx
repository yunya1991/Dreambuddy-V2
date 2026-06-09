'use client';

import { useEffect, useState } from 'react';

interface BoardMetrics {
  total_traces: number;
  total_decisions: number;
  total_artifacts: number;
  pending_approvals: number;
  recent_performance: { avg_win_rate: number; total_pnl: number; trade_count: number };
  department_breakdown: Record<string, number>;
}

interface ApprovalSummary {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
}

export default function BoardPage() {
  const [metrics, setMetrics] = useState<BoardMetrics | null>(null);
  const [approvalSummary, setApprovalSummary] = useState<ApprovalSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      try {
        const [metricsRes, approvalRes] = await Promise.all([
          fetch('/api/board/metrics'),
          fetch('/api/board/approval/summary'),
        ]);
        const metricsData = await metricsRes.json();
        const approvalData = await approvalRes.json();
        if (metricsData.success) setMetrics(metricsData.data);
        if (approvalData.success) setApprovalSummary(approvalData.data);
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load data');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 text-white p-8">
        <div className="animate-pulse">
          <div className="h-8 bg-gray-800 rounded w-48 mb-6"></div>
          <div className="grid grid-cols-4 gap-4">
            {[1,2,3,4].map(i => (
              <div key={i} className="h-32 bg-gray-800 rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 text-white p-8">
        <div className="bg-red-900/50 border border-red-700 rounded p-4">
          <h2 className="text-lg font-bold text-red-400">Error Loading Board Data</h2>
          <p className="text-red-300">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-white">董事会总览台</h1>
        <p className="text-gray-400 mt-1">Artifact Hub 治理层监控面板</p>
      </header>

      {/* Key Metrics Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <MetricCard
          title="总追踪数"
          value={metrics?.total_traces ?? 0}
          icon="🔍"
          color="blue"
        />
        <MetricCard
          title="总决策数"
          value={metrics?.total_decisions ?? 0}
          icon="⚖️"
          color="purple"
        />
        <MetricCard
          title="总产物数"
          value={metrics?.total_artifacts ?? 0}
          icon="📦"
          color="green"
        />
        <MetricCard
          title="待审批"
          value={approvalSummary?.pending ?? 0}
          icon="⏳"
          color="yellow"
        />
      </div>

      {/* Approval Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-semibold text-gray-300 mb-4">审批状态</h3>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-gray-400">待审批</span>
              <span className="text-yellow-400 font-bold">{approvalSummary?.pending ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">已批准</span>
              <span className="text-green-400 font-bold">{approvalSummary?.approved ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">已拒绝</span>
              <span className="text-red-400 font-bold">{approvalSummary?.rejected ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Performance */}
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-semibold text-gray-300 mb-4">近期表现</h3>
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-gray-400">胜率</span>
              <span className="text-blue-400 font-bold">
                {((metrics?.recent_performance.avg_win_rate ?? 0) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">PnL</span>
              <span className={`font-bold ${(metrics?.recent_performance.total_pnl ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${(metrics?.recent_performance.total_pnl ?? 0).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">交易数</span>
              <span className="text-gray-200 font-bold">{metrics?.recent_performance.trade_count ?? 0}</span>
            </div>
          </div>
        </div>

        {/* Department Breakdown */}
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-semibold text-gray-300 mb-4">部门分布</h3>
          <div className="space-y-2">
            {Object.entries(metrics?.department_breakdown ?? {}).map(([dept, count]) => (
              <div key={dept} className="flex justify-between">
                <span className="text-gray-400 capitalize">{dept}</span>
                <span className="text-gray-200 font-bold">{count}</span>
              </div>
            ))}
            {Object.keys(metrics?.department_breakdown ?? {}).length === 0 && (
              <p className="text-gray-500 text-sm">暂无数据</p>
            )}
          </div>
        </div>
      </div>

      {/* Navigation */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <NavCard href="/board/proposals" title="提案管理" description="查看和管理董事会提案" icon="📋" />
        <NavCard href="/board/review" title="绩效审查" description="查看策略执行绩效" icon="📊" />
        <NavCard href="/ops" title="运维监控" description="队列状态和系统健康" icon="⚙️" />
      </div>
    </div>
  );
}

function MetricCard({ title, value, icon, color }: {
  title: string;
  value: number;
  icon: string;
  color: 'blue' | 'purple' | 'green' | 'yellow';
}) {
  const colorMap = {
    blue: 'border-blue-600 bg-blue-950/30',
    purple: 'border-purple-600 bg-purple-950/30',
    green: 'border-green-600 bg-green-950/30',
    yellow: 'border-yellow-600 bg-yellow-950/30',
  };
  return (
    <div className={`rounded-lg p-6 border ${colorMap[color]}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-3xl">{icon}</span>
      </div>
      <div className="text-3xl font-bold text-white">{value}</div>
      <div className="text-sm text-gray-400 mt-1">{title}</div>
    </div>
  );
}

function NavCard({ href, title, description, icon }: {
  href: string;
  title: string;
  description: string;
  icon: string;
}) {
  return (
    <a href={href} className="block bg-gray-900 rounded-lg p-6 border border-gray-800 hover:border-gray-700 transition-colors">
      <div className="flex items-start gap-4">
        <span className="text-3xl">{icon}</span>
        <div>
          <h3 className="text-lg font-semibold text-white">{title}</h3>
          <p className="text-sm text-gray-400 mt-1">{description}</p>
        </div>
      </div>
    </a>
  );
}

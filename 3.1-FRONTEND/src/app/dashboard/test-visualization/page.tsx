'use client';

import { useMemo } from 'react';

interface TestCategory {
  name: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  icon: string;
}

interface TestRun {
  id: string;
  timestamp: string;
  status: 'passed' | 'failed' | 'running';
  duration: string;
  count: number;
  branch: string;
}

interface FailedTest {
  name: string;
  error: string;
  file: string;
  suite: string;
}

const categories: TestCategory[] = [
  { name: '单元测试', total: 98, passed: 92, failed: 4, skipped: 2, icon: '🧩' },
  { name: '集成测试', total: 34, passed: 30, failed: 2, skipped: 2, icon: '🔗' },
  { name: '端到端测试', total: 16, passed: 14, failed: 1, skipped: 1, icon: '🌐' },
  { name: '回归测试', total: 8, passed: 6, failed: 1, skipped: 1, icon: '🔄' },
];

const runs: TestRun[] = [
  { id: 'run-2041', timestamp: '2026-09-28 14:32:10', status: 'passed', duration: '2m 14s', count: 156, branch: 'main' },
  { id: 'run-2040', timestamp: '2026-09-28 11:08:45', status: 'failed', duration: '1m 52s', count: 154, branch: 'feature/factor-v3' },
  { id: 'run-2039', timestamp: '2026-09-28 09:15:22', status: 'passed', duration: '2m 03s', count: 156, branch: 'main' },
  { id: 'run-2038', timestamp: '2026-09-27 22:41:03', status: 'passed', duration: '2m 08s', count: 156, branch: 'develop' },
  { id: 'run-2037', timestamp: '2026-09-27 18:27:55', status: 'running', duration: '—', count: 156, branch: 'hotfix/queue-latency' },
];

const failedTests: FailedTest[] = [
  {
    name: 'should throttle high-frequency signals',
    error: 'Expected latency < 100ms but got 142ms',
    file: 'src/engine/executor/throttle.test.ts',
    suite: 'ThrottleExecutor',
  },
  {
    name: 'rejects duplicate task ids',
    error: "Expected error to be thrown, but got undefined",
    file: 'src/engine/queue/dedup.test.ts',
    suite: 'DedupQueue',
  },
  {
    name: 'computes factor score for empty window',
    error: 'Cannot read properties of undefined (reading "length")',
    file: 'src/factors/momentum/score.test.ts',
    suite: 'MomentumScore',
  },
  {
    name: 'e2e: order lifecycle completes within 3s',
    error: 'Timeout of 3000ms exceeded',
    file: 'tests/e2e/order-lifecycle.test.ts',
    suite: 'OrderLifecycle',
  },
];

export default function TestVisualizationPage() {
  const summary = useMemo(() => {
    const total = 156;
    const passed = 142;
    const failed = 8;
    const skipped = 6;
    const passRate = Math.round((passed / total) * 1000) / 10;
    return { total, passed, failed, skipped, passRate };
  }, []);

  // Ring (donut) progress parameters
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const passArc = (summary.passRate / 100) * circumference;
  const failArc = (summary.failed / summary.total) * circumference;

  return (
    <div className="p-6 space-y-6 text-slate-100">
      <header>
        <h1 className="text-2xl font-bold text-slate-100">测试可视化</h1>
        <p className="text-slate-400 mt-1 text-sm">测试结果总览 · 通过率分析 · 失败用例追踪</p>
      </header>

      {/* Summary + Pass Rate Ring */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <StatCard label="总测试数" value={summary.total} accent="slate" />
        <StatCard label="通过" value={summary.passed} accent="emerald" />
        <StatCard label="失败" value={summary.failed} accent="red" />
        <StatCard label="跳过" value={summary.skipped} accent="amber" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Pass rate donut */}
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800 flex flex-col items-center justify-center">
          <h3 className="text-sm font-semibold text-slate-300 mb-4 self-start">通过率</h3>
          <div className="relative">
            <svg width="140" height="140" viewBox="0 0 140 140" className="-rotate-90">
              <circle cx="70" cy="70" r={radius} fill="none" stroke="rgb(30 41 59)" strokeWidth="14" />
              <circle
                cx="70" cy="70" r={radius} fill="none"
                stroke="rgb(16 185 129)" strokeWidth="14"
                strokeDasharray={`${passArc} ${circumference - passArc}`}
                strokeLinecap="round"
              />
              <circle
                cx="70" cy="70" r={radius} fill="none"
                stroke="rgb(239 68 68)" strokeWidth="14"
                strokeDasharray={`${failArc} ${circumference}`}
                strokeDashoffset={-passArc}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-bold text-slate-100">{summary.passRate}%</span>
              <span className="text-xs text-slate-500">pass rate</span>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5 text-emerald-400">
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-500" /> 通过 {summary.passed}
            </span>
            <span className="flex items-center gap-1.5 text-red-400">
              <span className="h-2.5 w-2.5 rounded-full bg-red-500" /> 失败 {summary.failed}
            </span>
            <span className="flex items-center gap-1.5 text-amber-400">
              <span className="h-2.5 w-2.5 rounded-full bg-amber-500" /> 跳过 {summary.skipped}
            </span>
          </div>
        </div>

        {/* Test categories */}
        <div className="bg-slate-900 rounded-lg p-6 border border-slate-800 lg:col-span-2">
          <h3 className="text-sm font-semibold text-slate-300 mb-4">测试分类</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {categories.map(cat => {
              const rate = Math.round((cat.passed / cat.total) * 100);
              return (
                <div key={cat.name} className="rounded-lg border border-slate-800 bg-slate-800/40 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
                      <span>{cat.icon}</span>{cat.name}
                    </span>
                    <span className="text-xs text-slate-500">{cat.total} 用例</span>
                  </div>
                  <div className="flex h-2 overflow-hidden rounded-full bg-slate-700">
                    <div className="bg-emerald-500" style={{ width: `${(cat.passed / cat.total) * 100}%` }} />
                    <div className="bg-red-500" style={{ width: `${(cat.failed / cat.total) * 100}%` }} />
                    <div className="bg-amber-500" style={{ width: `${(cat.skipped / cat.total) * 100}%` }} />
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-slate-400">
                    <span className="text-emerald-400">通过 {cat.passed}</span>
                    <span className="text-red-400">失败 {cat.failed}</span>
                    <span className="text-amber-400">跳过 {cat.skipped}</span>
                    <span className="text-slate-300 font-medium">{rate}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recent runs */}
      <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">最近测试运行</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-slate-400 border-b border-slate-800">
                <th className="text-left py-2 px-3 font-medium">运行 ID</th>
                <th className="text-left py-2 px-3 font-medium">状态</th>
                <th className="text-left py-2 px-3 font-medium">分支</th>
                <th className="text-left py-2 px-3 font-medium">用例数</th>
                <th className="text-left py-2 px-3 font-medium">耗时</th>
                <th className="text-left py-2 px-3 font-medium">时间</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(run => (
                <tr key={run.id} className="border-b border-slate-800/60 hover:bg-slate-800/40">
                  <td className="py-2.5 px-3 font-mono text-xs text-slate-300">{run.id}</td>
                  <td className="py-2.5 px-3">
                    <RunStatus status={run.status} />
                  </td>
                  <td className="py-2.5 px-3 text-slate-300 font-mono text-xs">{run.branch}</td>
                  <td className="py-2.5 px-3 text-slate-300">{run.count}</td>
                  <td className="py-2.5 px-3 text-slate-400">{run.duration}</td>
                  <td className="py-2.5 px-3 text-slate-500 text-xs">{run.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Failed tests */}
      <div className="bg-slate-900 rounded-lg p-6 border border-slate-800">
        <h3 className="text-sm font-semibold text-slate-300 mb-4">
          失败用例 <span className="text-red-400">({failedTests.length})</span>
        </h3>
        <div className="space-y-3">
          {failedTests.map((t, i) => (
            <div key={i} className="rounded-lg border border-red-900/50 bg-red-950/20 p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-100 font-mono">{t.name}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    <span className="text-slate-400">{t.suite}</span> · {t.file}
                  </p>
                </div>
                <span className="shrink-0 rounded bg-red-900/40 px-2 py-0.5 text-xs text-red-300 border border-red-800">FAIL</span>
              </div>
              <div className="mt-3 rounded bg-slate-950/60 px-3 py-2 border border-slate-800">
                <code className="text-xs text-red-300 break-words">{t.error}</code>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: {
  label: string;
  value: number;
  accent: 'slate' | 'emerald' | 'red' | 'amber';
}) {
  const accentMap: Record<string, string> = {
    slate: 'text-slate-100',
    emerald: 'text-emerald-400',
    red: 'text-red-400',
    amber: 'text-amber-400',
  };
  return (
    <div className="bg-slate-900 rounded-lg p-5 border border-slate-800">
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${accentMap[accent]}`}>{value}</div>
    </div>
  );
}

function RunStatus({ status }: { status: TestRun['status'] }) {
  const map: Record<TestRun['status'], string> = {
    passed: 'bg-emerald-950/50 text-emerald-400 border-emerald-800',
    failed: 'bg-red-950/50 text-red-400 border-red-800',
    running: 'bg-blue-950/50 text-blue-400 border-blue-800',
  };
  const label: Record<TestRun['status'], string> = {
    passed: '通过',
    failed: '失败',
    running: '运行中',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border ${map[status]}`}>
      {status === 'running' && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />}
      {label[status]}
    </span>
  );
}

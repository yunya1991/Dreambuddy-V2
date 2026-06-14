// ============================================================================
// 推荐策略引擎: 回测历史
// ============================================================================

import { PrismaClient } from "@prisma/client";
import type { Metadata } from "next";

const prisma = new PrismaClient();

export const metadata: Metadata = { title: "回测历史 | 推荐策略引擎" };
export const dynamic = "force-dynamic";

async function getBacktestData() {
  const [records, total] = await Promise.all([
    prisma.strategyBacktestRecord.findMany({
      include: {
        strategy: { select: { id: true, name: true, direction: true, symbol: true, regime: true } },
      },
      orderBy: { backtestDate: "desc" },
      take: 50,
    }),
    prisma.strategyBacktestRecord.count(),
  ]);

  return { records, total };
}

export default async function BacktestsPage() {
  const { records, total } = await getBacktestData();

  return (
    <div className="space-y-4">
      {/* 统计 */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">总回测次数</div>
          <div className="text-2xl font-bold text-gray-900">{total}</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">优于基线</div>
          <div className="text-2xl font-bold text-green-600">
            {records.filter((r) => r.isBetterThanBaseline).length}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">劣于基线</div>
          <div className="text-2xl font-bold text-red-600">
            {records.filter((r) => !r.isBetterThanBaseline).length}
          </div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">平均 Sharpe</div>
          <div className="text-2xl font-bold text-blue-600">
            {total > 0
              ? (records.reduce((sum, r) => sum + r.sharpeRatio, 0) / records.length).toFixed(3)
              : "—"}
          </div>
        </div>
      </div>

      {/* 回测列表 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900">回测历史记录（最近50条）</h3>
        </div>

        {records.length === 0 ? (
          <div className="text-sm text-gray-400 py-12 text-center">
            暂无回测记录
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left text-xs text-gray-600">策略</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">方向</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">回测日期</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">周期</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">Sharpe</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">MaxDD</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">胜率</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">收益率</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">vs 基线</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">对比结果</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {records.map((r) => (
                <tr key={r.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-900 truncate max-w-[180px]">
                    {r.strategy.name}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                        r.strategy.direction === "BUY"
                          ? "bg-red-100 text-red-700"
                          : "bg-green-100 text-green-700"
                      }`}
                    >
                      {r.strategy.direction}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {new Date(r.backtestDate).toLocaleDateString("zh-CN")}
                  </td>
                  <td className="px-4 py-2 text-gray-500">{r.backtestPeriod}</td>
                  <td
                    className={`px-4 py-2 font-mono font-medium ${
                      r.sharpeRatio >= r.baselineSharpe ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {r.sharpeRatio.toFixed(3)}
                  </td>
                  <td
                    className={`px-4 py-2 font-mono ${
                      r.maxDrawdown <= r.baselineMaxDrawdown ? "text-green-600" : "text-red-600"
                    }`}
                  >
                    {r.maxDrawdown.toFixed(2)}%
                  </td>
                  <td className="px-4 py-2 font-mono text-gray-700">{r.winRate.toFixed(1)}%</td>
                  <td className="px-4 py-2 font-mono text-gray-900">{r.totalReturn.toFixed(2)}%</td>
                  <td className="px-4 py-2 font-mono text-gray-500 text-xs">
                    {r.baselineSharpe.toFixed(3)}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                        r.isBetterThanBaseline
                          ? "bg-green-100 text-green-700"
                          : "bg-yellow-100 text-yellow-700"
                      }`}
                    >
                      {r.isBetterThanBaseline ? "✓ 优于" : "⚠ 劣于"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

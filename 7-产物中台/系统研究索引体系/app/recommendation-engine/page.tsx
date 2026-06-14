// ============================================================================
// 推荐策略引擎: 总览仪表盘
// ============================================================================

import { PrismaClient } from "@prisma/client";
import { getBaseline } from "@/lib/recommendation-engine/baseline-provider";
import TriggerButton from "./TriggerButton";

const prisma = new PrismaClient();

export const dynamic = "force-dynamic";

async function getDashboardData() {
  const [
    currentStrategy,
    libraryCount,
    recentBacktests,
    recentLogs,
    libraryStats,
  ] = await Promise.all([
    // 当前推荐策略
    prisma.strategy.findFirst({
      where: { type: "RECOMMENDED", status: { in: ["APPROVED", "APPLIED"] } },
      orderBy: { createdAt: "desc" },
    }),

    // 策略库数量
    prisma.strategy.count({ where: { isInLibrary: true, libraryActive: true } }),

    // 最近回测记录
    prisma.strategyBacktestRecord.findMany({
      include: {
        strategy: { select: { name: true, direction: true } },
      },
      orderBy: { backtestDate: "desc" },
      take: 5,
    }),

    // 最近运行日志
    prisma.recommendationEngineLog.findMany({
      orderBy: { runDate: "desc" },
      take: 3,
    }),

    // 策略库统计
    prisma.strategy.groupBy({
      by: ["isInLibrary", "libraryActive", "isBetterThanBaseline"],
      _count: { id: true },
    }),
  ]);

  const recommendedDays = currentStrategy?.recommendedDays ?? 0;
  const daysUntilForced = Math.max(0, 5 - recommendedDays);

  const baseline = getBaseline("v9");

  return {
    currentStrategy,
    recommendedDays,
    daysUntilForced,
    libraryCount,
    recentBacktests,
    recentLogs,
    libraryStats,
    baseline,
  };
}

export default async function RecommendationEnginePage() {
  const data = await getDashboardData();

  return (
    <div className="space-y-6">
      {/* 顶部操作区 */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">引擎状态</h2>
          <p className="text-sm text-gray-500 mt-0.5">
            {data.currentStrategy
              ? `已推荐 ${data.recommendedDays} 天，${data.daysUntilForced > 0 ? `${data.daysUntilForced} 天后强制刷新` : "即将强制刷新"}`
              : "尚未生成推荐策略"}
          </p>
        </div>
        <TriggerButton />
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-4 gap-4">
        {/* 当前推荐 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">当前推荐策略</div>
          <div className="text-lg font-bold text-gray-900 truncate">
            {data.currentStrategy?.name || "—"}
          </div>
          {data.currentStrategy && (
            <div className="flex items-center gap-2 mt-1">
              <span
                className={`text-xs px-1.5 py-0.5 rounded font-medium ${
                  data.currentStrategy.direction === "BUY"
                    ? "bg-red-100 text-red-700"
                    : "bg-green-100 text-green-700"
                }`}
              >
                {data.currentStrategy.direction}
              </span>
              <span
                className={`text-xs px-1.5 py-0.5 rounded ${
                  data.currentStrategy.isBetterThanBaseline
                    ? "bg-green-100 text-green-700"
                    : "bg-yellow-100 text-yellow-700"
                }`}
              >
                {data.currentStrategy.isBetterThanBaseline ? "✓ 优于基线" : "⚠ 基线"}
              </span>
            </div>
          )}
        </div>

        {/* 策略库 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">策略库（活跃）</div>
          <div className="text-2xl font-bold text-blue-600">
            {data.libraryCount}
          </div>
          <div className="text-xs text-gray-400 mt-1">个优于基线的策略</div>
        </div>

        {/* 推荐天数 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">连续推荐</div>
          <div className="text-2xl font-bold text-purple-600">
            {data.recommendedDays}
            <span className="text-sm font-normal text-gray-400 ml-1">天</span>
          </div>
          <div className="text-xs text-gray-400 mt-1">
            {data.daysUntilForced > 0
              ? `${data.daysUntilForced} 天后强制刷新`
              : "⏰ 强制刷新中"}
          </div>
        </div>

        {/* 基线参考 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">v9 基线参考（BTC）</div>
          <div className="text-sm font-mono text-gray-700">
            Sharpe: {data.baseline.referencePerformance.btc.sharpe}
          </div>
          <div className="text-xs text-gray-500">
            MaxDD: {data.baseline.referencePerformance.btc.maxDD}% |{" "}
            Return: {data.baseline.referencePerformance.btc.returnPct}%
          </div>
        </div>
      </div>

      {/* 性能对比 */}
      {data.currentStrategy && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            当前推荐策略 vs 基线
          </h3>
          <div className="grid grid-cols-4 gap-6">
            {[
              {
                label: "Sharpe 比率",
                strategy: data.currentStrategy.backtestSharpe,
                baseline: data.currentStrategy.baselineSharpe,
                higher: true,
              },
              {
                label: "最大回撤",
                strategy: data.currentStrategy.backtestMaxDrawdown,
                baseline: data.currentStrategy.baselineMaxDrawdown,
                higher: false,
              },
              {
                label: "总收益率",
                strategy: data.currentStrategy.backtestTotalReturn,
                baseline: data.currentStrategy.baselineTotalReturn,
                higher: true,
                suffix: "%",
              },
              {
                label: "胜率",
                strategy: data.currentStrategy.backtestWinRate,
                baseline: null,
                higher: true,
                suffix: "%",
              },
            ].map((metric) => (
              <div key={metric.label} className="text-center">
                <div className="text-xs text-gray-500 mb-1">{metric.label}</div>
                <div className="text-xl font-bold text-gray-900">
                  {metric.strategy != null ? metric.strategy.toFixed(2) : "—"}
                  {metric.suffix || ""}
                </div>
                {metric.baseline != null && (
                  <div
                    className={`text-xs mt-1 ${
                      metric.higher
                        ? metric.strategy! >= metric.baseline
                          ? "text-green-600"
                          : "text-red-600"
                        : metric.strategy! <= metric.baseline
                        ? "text-green-600"
                        : "text-red-600"
                    }`}
                  >
                    基线: {metric.baseline.toFixed(2)}
                    {metric.suffix || ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        {/* 最近回测 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            最近回测记录
          </h3>
          {data.recentBacktests.length === 0 ? (
            <div className="text-sm text-gray-400 py-8 text-center">
              暂无回测记录
            </div>
          ) : (
            <div className="space-y-2">
              {data.recentBacktests.map((r) => (
                <div
                  key={r.id}
                  className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">
                      {r.strategy.name}
                    </div>
                    <div className="text-xs text-gray-500">
                      {new Date(r.backtestDate).toLocaleDateString("zh-CN")} ·{" "}
                      {r.backtestPeriod} · {r.baselineVersion}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-4">
                    <span
                      className={`text-xs font-medium ${
                        r.isBetterThanBaseline
                          ? "text-green-600"
                          : "text-yellow-600"
                      }`}
                    >
                      {r.isBetterThanBaseline ? "✓ 优" : "⚠ 平"}
                    </span>
                    <span className="text-xs text-gray-400 font-mono">
                      {r.sharpeRatio.toFixed(3)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 最近运行日志 */}
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">
            最近运行日志
          </h3>
          {data.recentLogs.length === 0 ? (
            <div className="text-sm text-gray-400 py-8 text-center">
              暂无运行日志
            </div>
          ) : (
            <div className="space-y-2">
              {data.recentLogs.map((log) => (
                <div
                  key={log.runId}
                  className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0"
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-gray-500">
                      {new Date(log.runDate).toLocaleString("zh-CN")}
                    </div>
                    <div className="text-xs text-gray-700 mt-0.5 truncate">
                      {log.decisionReason || log.errorMessage || "—"}
                    </div>
                  </div>
                  <span
                    className={`text-xs px-2 py-0.5 rounded ml-2 shrink-0 ${
                      log.status === "success"
                        ? "bg-green-100 text-green-700"
                        : log.status === "failed"
                        ? "bg-red-100 text-red-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {log.status}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

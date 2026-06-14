// ============================================================================
// 推荐策略引擎: 策略库
// ============================================================================

import { PrismaClient } from "@prisma/client";
import type { Metadata } from "next";

const prisma = new PrismaClient();

export const metadata: Metadata = { title: "策略库 | 推荐策略引擎" };
export const dynamic = "force-dynamic";

async function getLibraryData(includeArchived: boolean) {
  const strategies = await prisma.strategy.findMany({
    where: { isInLibrary: true, ...(includeArchived ? {} : { libraryActive: true }) },
    include: { backtestRecords: { orderBy: { backtestDate: "desc" }, take: 1 } },
    orderBy: { libraryScore: "desc" },
  });

  return strategies;
}

export default async function LibraryPage({
  searchParams,
}: {
  searchParams: { includeArchived?: string };
}) {
  const includeArchived = searchParams.includeArchived === "true";
  const strategies = await getLibraryData(includeArchived);

  const active = strategies.filter((s) => s.libraryActive);
  const archived = strategies.filter((s) => !s.libraryActive);

  return (
    <div className="space-y-6">
      {/* 统计 */}
      <div className="grid grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">策略库总数</div>
          <div className="text-2xl font-bold text-blue-600">{strategies.length}</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">活跃策略</div>
          <div className="text-2xl font-bold text-green-600">{active.length}</div>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="text-xs text-gray-500 mb-1">已归档</div>
          <div className="text-2xl font-bold text-gray-400">{archived.length}</div>
        </div>
      </div>

      {/* 过滤 */}
      <div className="flex items-center gap-4">
        <a
          href="/recommendation-engine/library"
          className={`text-sm px-3 py-1.5 rounded-lg border ${
            !includeArchived
              ? "bg-blue-50 border-blue-300 text-blue-700"
              : "bg-white border-gray-200 text-gray-600"
          }`}
        >
          活跃策略
        </a>
        <a
          href="/recommendation-engine/library?includeArchived=true"
          className={`text-sm px-3 py-1.5 rounded-lg border ${
            includeArchived
              ? "bg-blue-50 border-blue-300 text-blue-700"
              : "bg-white border-gray-200 text-gray-600"
          }`}
        >
          全部（包含归档）
        </a>
      </div>

      {/* 策略列表 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {strategies.length === 0 ? (
          <div className="text-sm text-gray-400 py-12 text-center">
            策略库为空（暂无优于基线的策略）
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left text-xs text-gray-600">策略名称</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">方向</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">Regime</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">Sharpe</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">MaxDD</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">收益率</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">评分</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">状态</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">创建时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {strategies.map((s) => (
                <tr key={s.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 font-medium text-gray-900">{s.name}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                        s.direction === "BUY"
                          ? "bg-red-100 text-red-700"
                          : "bg-green-100 text-green-700"
                      }`}
                    >
                      {s.direction}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-600">{s.regime || "—"}</td>
                  <td className="px-4 py-2 font-mono text-gray-900">
                    {s.backtestSharpe?.toFixed(3) ?? "—"}
                  </td>
                  <td
                    className={`px-4 py-2 font-mono ${
                      (s.backtestMaxDrawdown ?? 0) <= (s.baselineMaxDrawdown ?? 999)
                        ? "text-green-600"
                        : "text-red-600"
                    }`}
                  >
                    {s.backtestMaxDrawdown?.toFixed(2) ?? "—"}%
                  </td>
                  <td className="px-4 py-2 font-mono text-gray-900">
                    {s.backtestTotalReturn?.toFixed(2) ?? "—"}%
                  </td>
                  <td className="px-4 py-2 font-mono text-blue-600 font-medium">
                    {s.libraryScore?.toFixed(4) ?? "—"}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`text-xs px-1.5 py-0.5 rounded ${
                        s.libraryActive
                          ? "bg-green-100 text-green-700"
                          : "bg-gray-100 text-gray-500"
                      }`}
                    >
                      {s.libraryActive ? "活跃" : "归档"}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">
                    {new Date(s.createdAt).toLocaleDateString("zh-CN")}
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

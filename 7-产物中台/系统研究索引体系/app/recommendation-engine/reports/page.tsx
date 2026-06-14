// ============================================================================
// 推荐策略引擎: 研报源数据
// ============================================================================

import { readLatestReports } from "@/lib/recommendation-engine/report-reader";

export const dynamic = "force-dynamic";

const PHASE_LABELS: Record<string, { label: string; color: string }> = {
  A1: { label: "侦察", color: "#3b82f6" },
  A2: { label: "第一性原理", color: "#8b5cf6" },
  A3: { label: "推演", color: "#f59e0b" },
};

export default async function ReportsPage() {
  const data = await readLatestReports({ phases: ["A1", "A2", "A3"], days: 7, limit: 30 });

  const byPhase = data.reports.reduce(
    (acc, r) => {
      const phase = r.chain_phase;
      if (!acc[phase]) acc[phase] = [];
      acc[phase].push(r);
      return acc;
    },
    {} as Record<string, typeof data.reports>
  );

  return (
    <div className="space-y-6">
      {/* 统计 */}
      <div className="grid grid-cols-3 gap-4">
        {["A1", "A2", "A3"].map((phase) => {
          const info = PHASE_LABELS[phase];
          const count = byPhase[phase]?.length ?? 0;
          return (
            <div
              key={phase}
              className="bg-white rounded-lg border border-gray-200 p-4"
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ backgroundColor: info.color }}
                />
                <span className="text-sm font-medium text-gray-900">
                  {phase} · {info.label}
                </span>
              </div>
              <div className="text-2xl font-bold text-gray-900">{count}</div>
              <div className="text-xs text-gray-500">份研报（近7天）</div>
            </div>
          );
        })}
      </div>

      {/* 研报列表 */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-200 bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900">
            研报列表（{data.total} 份）
          </h3>
          <p className="text-xs text-gray-500 mt-0.5">
            来源: {data.sourcePath} | 更新: {new Date(data.readAt).toLocaleString("zh-CN")}
          </p>
        </div>

        {data.reports.length === 0 ? (
          <div className="text-sm text-gray-400 py-12 text-center">
            暂无研报数据
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-2 text-left text-xs text-gray-600">阶段</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">标题</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">日期</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">Regime</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">方向</th>
                <th className="px-4 py-2 text-left text-xs text-gray-600">置信度</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {data.reports.map((r, i) => {
                const info = PHASE_LABELS[r.chain_phase] || {
                  label: r.chain_phase,
                  color: "#a1a1aa",
                };
                return (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2">
                      <span
                        className="inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium text-white"
                        style={{ backgroundColor: info.color }}
                      >
                        {r.chain_phase}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-900 truncate max-w-xs">
                      {r.title || r.file}
                    </td>
                    <td className="px-4 py-2 text-gray-500">
                      {r.date ? new Date(r.date).toLocaleDateString("zh-CN") : "—"}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {r.regime || "—"}
                    </td>
                    <td className="px-4 py-2">
                      {r.direction ? (
                        <span
                          className={`text-xs font-medium px-1.5 py-0.5 rounded ${
                            r.direction === "BUY"
                              ? "bg-red-100 text-red-700"
                              : "bg-green-100 text-green-700"
                          }`}
                        >
                          {r.direction}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-gray-600">
                      {r.confidence != null ? `${r.confidence}%` : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

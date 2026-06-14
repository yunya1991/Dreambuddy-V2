import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminStrategyDetail } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminStrategyDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const strategy = await getAdminStrategyDetail(params.id);

  if (!strategy) {
    return (
      <>
        <AdminTopBar title="策略不存在" />
        <main className="p-6 flex-1">
          <div className="text-center text-gray-400 py-20">
            <div className="text-5xl mb-4">😕</div>
            <div>策略 ID: {params.id}</div>
            <a href="/admin/strategies" className="inline-block mt-4 text-sm text-blue-600 hover:underline">
              返回策略列表
            </a>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <AdminTopBar title={`策略详情：${strategy.name}`} subtitle={`类型：${strategy.type}`} />
      <main className="p-6 space-y-6 flex-1">
        <a
          href="/admin/strategies"
          className="text-xs text-gray-600 hover:text-blue-600 transition-colors inline-block mb-2"
        >
          ← 返回策略列表
        </a>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">状态</div>
            <div className="text-sm font-semibold">
              <span
                className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                  strategy.status === "APPLIED" || strategy.status === "applied"
                    ? "bg-green-100 text-green-800"
                    : strategy.status === "PAUSED" || strategy.status === "paused"
                      ? "bg-yellow-100 text-yellow-800"
                      : "bg-gray-100 text-gray-600"
                }`}
              >
                {strategy.status}
              </span>
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">任务数</div>
            <div className="text-sm font-semibold text-gray-900">{strategy.taskCount} 个</div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">执行记录</div>
            <div className="text-sm font-semibold text-gray-900">{strategy.executionCount} 次</div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">基础信息</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-xs text-gray-500">策略 ID</div>
              <div className="font-mono text-gray-700 text-xs">{strategy.id}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">所属用户</div>
              <div className="text-gray-700">
                {strategy.userDisplayName || strategy.userEmail || "未知"}
                {strategy.uid && (
                  <a
                    href={`/admin/users/${encodeURIComponent(strategy.uid)}`}
                    className="text-xs text-blue-600 hover:underline ml-2"
                  >
                    (查看用户)
                  </a>
                )}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">创建时间</div>
              <div className="text-gray-700">{formatDateTime(strategy.createdAt)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">更新时间</div>
              <div className="text-gray-700">{formatDateTime(strategy.updatedAt)}</div>
            </div>
          </div>
          {strategy.description && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <div className="text-xs text-gray-500 mb-1">描述</div>
              <div className="text-sm text-gray-700 whitespace-pre-wrap">{strategy.description}</div>
            </div>
          )}
          {strategy.metadata && (
            <div className="mt-4 pt-4 border-t border-gray-100">
              <div className="text-xs text-gray-500 mb-1">配置数据 (metadata)</div>
              <pre className="text-xs bg-gray-50 p-3 rounded-lg overflow-x-auto text-gray-600 font-mono">
                {JSON.stringify(strategy.metadata, null, 2)}
              </pre>
            </div>
          )}
        </div>

        {strategy.tasks.length > 0 && (
          <div className="bg-white rounded-lg border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">关联任务 ({strategy.tasks.length})</h3>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-left">任务</th>
                    <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-center">状态</th>
                    <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {strategy.tasks.map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2 text-sm text-gray-700">{t.name}</td>
                      <td className="px-4 py-2 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                          {t.status}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-500">{formatDateTime(t.createdAt)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </>
  );
}

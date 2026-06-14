import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminStrategyList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminStrategiesPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";
  const status = typeof searchParams.status === "string" ? searchParams.status : "";

  const { items, total } = await getAdminStrategyList(page, pageSize, search, status);

  return (
    <>
      <AdminTopBar title="策略管理" subtitle={`共 ${total} 个策略`} />
      <main className="p-6 flex-1">
        <div className="mb-4 flex items-center gap-2">
          <form className="flex items-center gap-2 flex-1">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索策略名称或描述..."
              className="flex-1 px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
            />
            {status && <input type="hidden" name="status" value={status} />}
            <button
              type="submit"
              className="px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700"
            >
              搜索
            </button>
          </form>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">策略</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">类型</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">状态</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">更新时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-gray-400 text-sm">
                      暂无策略数据
                    </td>
                  </tr>
                ) : (
                  items.map((s) => (
                    <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <a
                          href={`/admin/strategies/${encodeURIComponent(s.id)}`}
                          className="font-medium text-gray-900 hover:text-blue-600 text-sm"
                        >
                          {s.name}
                        </a>
                        {s.description && (
                          <div className="text-xs text-gray-500 mt-0.5 truncate max-w-md">
                            {s.description}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">{s.type}</td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                            s.status === "APPLIED" || s.status === "applied"
                              ? "bg-green-100 text-green-800"
                              : s.status === "PAUSED" || s.status === "paused"
                                ? "bg-yellow-100 text-yellow-800"
                                : "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {s.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {s.userDisplayName || s.userEmail || "未知"}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">{formatDateTime(s.createdAt)}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{formatDateTime(s.updatedAt)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {total > pageSize && (
            <div className="flex items-center justify-between px-6 py-3 border-t border-gray-200 bg-gray-50">
              <div className="text-xs text-gray-500">
                第 {page} / {Math.ceil(total / pageSize)} 页
              </div>
              <div className="flex items-center gap-2">
                {page > 1 && (
                  <a
                    href={`/admin/strategies?page=${page - 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    ← 上一页
                  </a>
                )}
                {page < Math.ceil(total / pageSize) && (
                  <a
                    href={`/admin/strategies?page=${page + 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    下一页 →
                  </a>
                )}
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}

import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminTaskList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminTasksPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";
  const status = typeof searchParams.status === "string" ? searchParams.status : "";

  const { items, total } = await getAdminTaskList(page, pageSize, search, status);

  return (
    <>
      <AdminTopBar title="任务监控" subtitle={`共 ${total} 个任务`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索任务名称..."
              className="flex-1 px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
            />
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
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">任务</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">所属策略</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">状态</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">
                      暂无任务数据
                    </td>
                  </tr>
                ) : (
                  items.map((t) => (
                    <tr key={t.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-700 font-medium">{t.name}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {t.strategyId && (
                          <a
                            href={`/admin/strategies/${encodeURIComponent(t.strategyId)}`}
                            className="text-blue-600 hover:underline"
                          >
                            {t.strategyName || "查看策略"}
                          </a>
                        )}
                        {!t.strategyId && <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                          {t.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {t.uid && (
                          <a
                            href={`/admin/users/${encodeURIComponent(t.uid)}`}
                            className="text-blue-600 hover:underline"
                          >
                            {t.userDisplayName || t.userEmail || t.uid}
                          </a>
                        )}
                        {!t.uid && <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{formatDateTime(t.createdAt)}</td>
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
                    href={`/admin/tasks?page=${page - 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    ← 上一页
                  </a>
                )}
                {page < Math.ceil(total / pageSize) && (
                  <a
                    href={`/admin/tasks?page=${page + 1}${
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

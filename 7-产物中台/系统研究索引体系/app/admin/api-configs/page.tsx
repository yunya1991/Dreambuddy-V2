import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminApiConfigList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminApiConfigsPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";

  const { items, total } = await getAdminApiConfigList(page, pageSize, search);

  return (
    <>
      <AdminTopBar title="API 配置" subtitle={`共 ${total} 个配置`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索服务商/类型..."
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
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">服务商</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">类型</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-gray-400 text-sm">
                      暂无 API 配置
                    </td>
                  </tr>
                ) : (
                  items.map((c) => (
                    <tr key={c.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-700 font-medium">
                        {c.provider || "—"}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.type || "—"}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">
                        {c.uid && (
                          <a
                            href={`/admin/users/${encodeURIComponent(c.uid)}`}
                            className="text-blue-600 hover:underline"
                          >
                            {c.userDisplayName || c.userEmail || c.uid}
                          </a>
                        )}
                        {!c.uid && <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">
                        {c.createdAt ? formatDateTime(c.createdAt) : "—"}
                      </td>
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
                    href={`/admin/api-configs?page=${page - 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    ← 上一页
                  </a>
                )}
                {page < Math.ceil(total / pageSize) && (
                  <a
                    href={`/admin/api-configs?page=${page + 1}${
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

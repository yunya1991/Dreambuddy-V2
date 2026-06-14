import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminGenericList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminGenericPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";

  const { items, total } = await getAdminGenericList(page, pageSize, search);

  return (
    <>
      <AdminTopBar title="其他数据" subtitle={`共 ${total} 条记录`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索记录 ID / 关键字..."
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
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">类型</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">ID</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">标题 / 说明</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-gray-400 text-sm">
                      暂无数据
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={`${item.type}-${String(item.id)}`} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-purple-50 text-purple-700">
                          {item.type}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-600">
                        {String(item.id).slice(0, 16)}
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-700">{item.title || "—"}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">
                        {item.createdAt ? formatDateTime(item.createdAt) : "—"}
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
                    href={`/admin/other?page=${page - 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    ← 上一页
                  </a>
                )}
                {page < Math.ceil(total / pageSize) && (
                  <a
                    href={`/admin/other?page=${page + 1}${
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

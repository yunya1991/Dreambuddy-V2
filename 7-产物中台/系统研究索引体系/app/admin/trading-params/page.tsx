import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminTradingParamsList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminTradingParamsPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";

  const { items, total } = await getAdminTradingParamsList(page, pageSize, search);

  return (
    <>
      <AdminTopBar title="交易参数" subtitle={`共 ${total} 条记录`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索用户/交易对..."
              className="flex-1 px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:border-blue-400"
            />
            <button type="submit" className="px-4 py-2 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700">
              搜索
            </button>
          </form>
        </div>
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">状态</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-right">今日交易</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-right">累计交易</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">暂无交易参数</td></tr>
                ) : (
                  items.map((tp) => (
                    <tr key={String(tp.id)} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-800">
                        {tp.userDisplayName || tp.userEmail || "未知用户"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                          {tp.status || "unknown"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right text-sm text-gray-800">{Number(tp.todayTradeCount || 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-right text-sm text-gray-800">{Number(tp.totalTradeCount || 0).toLocaleString()}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">
                        {tp.createdAt ? formatDateTime(tp.createdAt) : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </>
  );
}

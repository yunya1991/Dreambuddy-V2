import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminChannelList } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";
import { evaluateWriteGate } from "@/lib/admin/gate";
import { RowActionButton } from "@/components/admin/write/RowActionButton";
import { CHANNEL_UPDATE_ACTION } from "@/lib/admin/constants";

export const dynamic = "force-dynamic";

export default async function AdminChannelsPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";

  const { items, total } = await getAdminChannelList(page, pageSize, search);
  const writeEnabled = evaluateWriteGate().enabled;

  return (
    <>
      <AdminTopBar title="渠道配置" subtitle={`共 ${total} 条记录`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索..."
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
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">名称</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">类型</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">所属用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">创建时间</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr><td colSpan={5} className="px-4 py-12 text-center text-gray-400 text-sm">暂无渠道配置</td></tr>
                ) : (
                  items.map((c) => (
                    <tr key={String(c.id)} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-sm text-gray-800">{c.name || "未命名"}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.type || c.provider || "—"}</td>
                      <td className="px-4 py-3 text-xs text-gray-600">{c.userDisplayName || c.userEmail || "—"}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{c.createdAt ? formatDateTime(c.createdAt) : "—"}</td>
                      <td className="px-4 py-3">
                        {c.isOnline !== undefined && c.updatedAt ? (
                          <RowActionButton
                            label={c.isOnline ? "下线渠道" : "上线渠道"}
                            endpoint={`/api/admin/channels/${encodeURIComponent(String(c.id))}`}
                            method="PATCH"
                            level="L0"
                            payload={{
                              isOnline: !c.isOnline,
                              expectedUpdatedAt: c.updatedAt,
                            }}
                            confirmText={`确认${c.isOnline ? "下线" : "上线"}渠道「${c.name || "未命名"}」？立即生效并写入审计。`}
                            danger={c.isOnline}
                            writeEnabled={writeEnabled}
                          />
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
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

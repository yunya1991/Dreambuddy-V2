import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminUserList } from "@/lib/admin-queries";
import { formatDateTime, formatRelativeTime } from "@/lib/utils/admin-format";
import { evaluateWriteGate } from "@/lib/admin/gate";
import { UnlockUserButton } from "@/components/admin/write/UnlockUserButton";
import { RowActionButton } from "@/components/admin/write/RowActionButton";
import { USER_ROLE_ACTION } from "@/lib/admin/constants";

export const dynamic = "force-dynamic";

export default async function AdminUsersPage({
  searchParams,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const page = Number(searchParams.page) || 1;
  const pageSize = 20;
  const search = typeof searchParams.search === "string" ? searchParams.search : "";

  const { items, total } = await getAdminUserList(page, pageSize, search);
  const writeEnabled = evaluateWriteGate().enabled;

  return (
    <>
      <AdminTopBar title="用户管理" subtitle={`共 ${total} 个用户`} />
      <main className="p-6 flex-1">
        <div className="mb-4">
          <form className="flex items-center gap-2">
            <input
              type="text"
              name="search"
              defaultValue={search}
              placeholder="搜索邮箱或用户名..."
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
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">用户</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">验证状态</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">角色</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">策略数</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-center">API配置</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">注册时间</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">最近登录</th>
                  <th className="px-4 py-3 text-xs font-semibold text-gray-600 text-left">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-gray-400 text-sm">
                      暂无用户数据
                    </td>
                  </tr>
                ) : (
                  items.map((u) => (
                    <tr key={u.uid} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <a
                          href={`/admin/users/${encodeURIComponent(u.uid)}`}
                          className="font-medium text-gray-900 hover:text-blue-600"
                        >
                          {u.displayName}
                        </a>
                        <div className="text-xs text-gray-500 mt-0.5">{u.email}</div>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span
                          className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
                            u.emailVerified
                              ? "bg-green-100 text-green-800"
                              : "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {u.emailVerified ? "已验证" : "未验证"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                          {u.role}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center text-sm">{u.strategyCount}</td>
                      <td className="px-4 py-3 text-center text-sm">{u.apiConfigCount}</td>
                      <td className="px-4 py-3">
                        <div className="text-xs text-gray-700">{formatDateTime(u.createdAt)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-gray-500">
                          {u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "从未登录"}
                        </span>
                      </td>
                      <td className="px-4 py-3 space-y-2">
                        <UnlockUserButton
                          uid={u.uid}
                          expectedUpdatedAt={u.updatedAt}
                          locked={!!u.lockedUntil && new Date(u.lockedUntil) > new Date()}
                          writeEnabled={writeEnabled}
                        />
                        <RowActionButton
                          label={u.role === "ADMIN" ? "降权 → FREE" : "提权 → ADMIN"}
                          endpoint={`/api/admin/users/${encodeURIComponent(u.uid)}`}
                          action={USER_ROLE_ACTION}
                          targetId={u.uid}
                          level="L0"
                          payload={{
                            role: u.role === "ADMIN" ? "FREE" : "ADMIN",
                            expectedUpdatedAt: u.updatedAt,
                          }}
                          confirmText={
                            u.role === "ADMIN"
                              ? `确认将 ${u.email} 降权为 FREE？该操作立即生效并写入审计。`
                              : `确认将 ${u.email} 提权为 ADMIN？提权将获得管理台全部写权限，并写入审计。`
                          }
                          danger={u.role === "ADMIN"}
                          writeEnabled={writeEnabled}
                        />
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
                    href={`/admin/users?page=${page - 1}${
                      search ? `&search=${encodeURIComponent(search)}` : ""
                    }`}
                    className="px-3 py-1.5 text-xs bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
                  >
                    ← 上一页
                  </a>
                )}
                {page < Math.ceil(total / pageSize) && (
                  <a
                    href={`/admin/users?page=${page + 1}${
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

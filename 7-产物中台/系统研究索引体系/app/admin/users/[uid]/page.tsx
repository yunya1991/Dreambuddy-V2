import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminUserDetail } from "@/lib/admin-queries";
import { formatDateTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminUserDetailPage({
  params,
}: {
  params: { uid: string };
}) {
  const user = await getAdminUserDetail(params.uid);

  if (!user) {
    return (
      <>
        <AdminTopBar title="用户不存在" />
        <main className="p-6 flex-1">
          <div className="text-center text-gray-400 py-20">
            <div className="text-5xl mb-4">😕</div>
            <div>用户 UID: {params.uid}</div>
            <a href="/admin/users" className="inline-block mt-4 text-sm text-blue-600 hover:underline">
              返回用户列表
            </a>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <AdminTopBar title={`用户详情：${user.displayName}`} subtitle={user.email} />
      <main className="p-6 space-y-6 flex-1">
        <a
          href="/admin/users"
          className="text-xs text-gray-600 hover:text-blue-600 transition-colors inline-block mb-2"
        >
          ← 返回用户列表
        </a>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">邮箱验证</div>
            <div
              className={`text-sm font-semibold ${
                user.emailVerified ? "text-green-700" : "text-gray-600"
              }`}
            >
              {user.emailVerified ? "✓ 已验证" : "未验证"}
            </div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">用户策略</div>
            <div className="text-sm font-semibold text-gray-900">{user.strategyCount} 个</div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">执行记录</div>
            <div className="text-sm font-semibold text-gray-900">{user.totalExecutions} 次</div>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="text-xs text-gray-500 mb-1">API配置</div>
            <div className="text-sm font-semibold text-gray-900">{user.apiConfigCount} 个</div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">基础信息</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
            <div>
              <div className="text-xs text-gray-500">用户 UID</div>
              <div className="font-mono text-gray-700 text-xs">{user.uid}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">邮箱</div>
              <div className="text-gray-700">{user.email}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">注册时间</div>
              <div className="text-gray-700">{formatDateTime(user.createdAt)}</div>
            </div>
            <div>
              <div className="text-xs text-gray-500">最近登录</div>
              <div className="text-gray-700">
                {user.lastLoginAt ? formatDateTime(user.lastLoginAt) : "从未登录"}
              </div>
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">策略列表</h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-left">策略名称</th>
                  <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-left">类型</th>
                  <th className="px-4 py-2 text-xs font-semibold text-gray-600 text-center">状态</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {user.strategies.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-8 text-center text-gray-400 text-sm">
                      该用户暂无策略
                    </td>
                  </tr>
                ) : (
                  user.strategies.map((s) => (
                    <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-2">
                        <a
                          href={`/admin/strategies/${encodeURIComponent(s.id)}`}
                          className="font-medium text-blue-600 hover:underline text-sm"
                        >
                          {s.name}
                        </a>
                      </td>
                      <td className="px-4 py-2 text-xs text-gray-600">{s.type}</td>
                      <td className="px-4 py-2 text-center">
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

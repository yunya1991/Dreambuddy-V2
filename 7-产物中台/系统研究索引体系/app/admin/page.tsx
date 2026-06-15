import { AdminTopBar } from "@/components/admin/AdminTopBar";
import { getAdminUserList, getAdminStrategyList, getAdminExecutionList, getAdminTaskList } from "@/lib/admin-queries";
import { formatDateTime, formatRelativeTime } from "@/lib/utils/admin-format";

export const dynamic = "force-dynamic";

export default async function AdminDashboardPage() {
  // 汇总指标
  const [usersRes, strategiesRes, tasksRes, executionsRes] = await Promise.all([
    getAdminUserList(1, 10),
    getAdminStrategyList(1, 10000),
    getAdminTaskList(1, 10000),
    getAdminExecutionList(1, 10000),
  ]);

  const stats = {
    totalUsers: usersRes.total,
    totalStrategies: strategiesRes.total,
    totalTasks: tasksRes.total,
    totalExecutions: executionsRes.total,
  };

  // 状态分布（策略）
  const strategyStatusMap: Record<string, number> = {};
  for (const s of strategiesRes.items) {
    const key = s.status || "unknown";
    strategyStatusMap[key] = (strategyStatusMap[key] || 0) + 1;
  }

  // 状态分布（执行记录）
  const executionStatusMap: Record<string, number> = {};
  for (const e of executionsRes.items) {
    const key = e.status || "unknown";
    executionStatusMap[key] = (executionStatusMap[key] || 0) + 1;
  }

  // 近期活跃（按用户策略数排序的用户）
  const topUsers = [...usersRes.items]
    .sort((a, b) => (b.strategyCount + b.apiConfigCount) - (a.strategyCount + a.apiConfigCount))
    .slice(0, 5);

  // 最近策略
  const recentStrategies = strategiesRes.items.slice(0, 8);
  const recentExecutions = executionsRes.items.slice(0, 8);

  const StatCard = ({ label, value, link, tone = "default" }: { label: string; value: string | number; link: string; tone?: "default" | "blue" | "green" | "purple" }) => {
    const tones: Record<string, string> = {
      default: "from-gray-50 to-white border-gray-200 text-gray-700",
      blue: "from-blue-50 to-white border-blue-100 text-blue-700",
      green: "from-green-50 to-white border-green-100 text-green-700",
      purple: "from-purple-50 to-white border-purple-100 text-purple-700",
    };
    return (
      <a
        href={link}
        className={`bg-gradient-to-br ${tones[tone]} border rounded-xl p-5 hover:shadow-md transition-all block`}
      >
        <div className="text-sm font-medium opacity-80">{label}</div>
        <div className="mt-2 text-3xl font-bold">{value}</div>
        <div className="mt-2 text-xs opacity-60">查看详情 →</div>
      </a>
    );
  };

  return (
    <>
      <AdminTopBar title="数据中台" subtitle="业务数据总览（只读模式）" />
      <main className="p-6 space-y-6 flex-1">
        {/* 核心指标 */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard label="总用户数" value={stats.totalUsers} link="/admin/users" tone="blue" />
          <StatCard label="总策略数" value={stats.totalStrategies} link="/admin/strategies" tone="green" />
          <StatCard label="总任务数" value={stats.totalTasks} link="/admin/tasks" tone="purple" />
          <StatCard label="总执行次数" value={stats.totalExecutions} link="/admin/executions" tone="default" />
        </div>

        {/* 两列布局 */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* 策略状态分布 */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">策略状态分布</h3>
            <div className="space-y-3">
              {Object.keys(strategyStatusMap).length === 0 ? (
                <p className="text-sm text-gray-400">暂无策略数据</p>
              ) : (
                Object.entries(strategyStatusMap)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => {
                    const pct = stats.totalStrategies > 0 ? Math.round((count / stats.totalStrategies) * 100) : 0;
                    return (
                      <div key={status}>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span className="font-medium text-gray-700">{status}</span>
                          <span className="text-gray-500">
                            {count} ({pct}%)
                          </span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-blue-400 to-blue-600 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })
              )}
            </div>
          </div>

          {/* 执行记录状态分布 */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-900 mb-4">执行记录状态分布</h3>
            <div className="space-y-3">
              {Object.keys(executionStatusMap).length === 0 ? (
                <p className="text-sm text-gray-400">暂无执行记录</p>
              ) : (
                Object.entries(executionStatusMap)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => {
                    const pct = stats.totalExecutions > 0 ? Math.round((count / stats.totalExecutions) * 100) : 0;
                    return (
                      <div key={status}>
                        <div className="flex items-center justify-between text-xs mb-1">
                          <span className="font-medium text-gray-700">{status}</span>
                          <span className="text-gray-500">
                            {count} ({pct}%)
                          </span>
                        </div>
                        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-green-400 to-teal-500 rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })
              )}
            </div>
          </div>
        </div>

        {/* 快速入口 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">快速入口</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <a href="/admin/users" className="p-4 rounded-lg border border-gray-100 hover:border-blue-300 hover:bg-blue-50/50 transition-all">
              <div className="text-2xl mb-1">👥</div>
              <div className="text-sm font-medium text-gray-900">用户管理</div>
              <div className="text-xs text-gray-500 mt-1">共 {stats.totalUsers} 个用户</div>
            </a>
            <a href="/admin/strategies" className="p-4 rounded-lg border border-gray-100 hover:border-green-300 hover:bg-green-50/50 transition-all">
              <div className="text-2xl mb-1">📈</div>
              <div className="text-sm font-medium text-gray-900">策略管理</div>
              <div className="text-xs text-gray-500 mt-1">共 {stats.totalStrategies} 个策略</div>
            </a>
            <a href="/admin/tasks" className="p-4 rounded-lg border border-gray-100 hover:border-purple-300 hover:bg-purple-50/50 transition-all">
              <div className="text-2xl mb-1">⚙️</div>
              <div className="text-sm font-medium text-gray-900">任务监控</div>
              <div className="text-xs text-gray-500 mt-1">共 {stats.totalTasks} 个任务</div>
            </a>
            <a href="/admin/executions" className="p-4 rounded-lg border border-gray-100 hover:border-amber-300 hover:bg-amber-50/50 transition-all">
              <div className="text-2xl mb-1">📋</div>
              <div className="text-sm font-medium text-gray-900">执行记录</div>
              <div className="text-xs text-gray-500 mt-1">共 {stats.totalExecutions} 条记录</div>
            </a>
          </div>
        </div>

        {/* 活跃用户 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">活跃用户 Top 5</h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-100">
                <tr className="text-xs text-gray-500 uppercase">
                  <th className="text-left font-semibold py-2 pl-2">用户</th>
                  <th className="text-center font-semibold py-2">策略数</th>
                  <th className="text-center font-semibold py-2">API 配置</th>
                  <th className="text-left font-semibold py-2 pr-2">最近登录</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {topUsers.length === 0 ? (
                  <tr><td colSpan={4} className="py-8 text-center text-gray-400 text-sm">暂无用户数据</td></tr>
                ) : topUsers.map((u) => (
                  <tr key={u.uid} className="hover:bg-gray-50 transition-colors">
                    <td className="py-3 pl-2">
                      <a href={`/admin/users/${encodeURIComponent(u.uid)}`} className="font-medium text-gray-900 hover:text-blue-600 text-sm">
                        {u.displayName}
                      </a>
                      <div className="text-xs text-gray-500">{u.email}</div>
                    </td>
                    <td className="py-3 text-center text-sm text-gray-700">{u.strategyCount}</td>
                    <td className="py-3 text-center text-sm text-gray-700">{u.apiConfigCount}</td>
                    <td className="py-3 pr-2 text-xs text-gray-500">
                      {u.lastLoginAt ? formatDateTime(u.lastLoginAt) : "从未登录"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* 最近策略 */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h3 className="text-sm font-semibold text-gray-900 mb-4">最近创建的策略</h3>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-100">
                <tr className="text-xs text-gray-500 uppercase">
                  <th className="text-left font-semibold py-2 pl-2">策略</th>
                  <th className="text-left font-semibold py-2">类型</th>
                  <th className="text-center font-semibold py-2">状态</th>
                  <th className="text-left font-semibold py-2">所属用户</th>
                  <th className="text-left font-semibold py-2 pr-2">创建时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {recentStrategies.length === 0 ? (
                  <tr><td colSpan={5} className="py-8 text-center text-gray-400 text-sm">暂无策略数据</td></tr>
                ) : recentStrategies.map((s) => (
                  <tr key={s.id} className="hover:bg-gray-50 transition-colors">
                    <td className="py-3 pl-2">
                      <a href={`/admin/strategies/${encodeURIComponent(s.id)}`} className="font-medium text-gray-900 hover:text-blue-600 text-sm">
                        {s.name}
                      </a>
                    </td>
                    <td className="py-3 text-xs text-gray-600">{s.type}</td>
                    <td className="py-3 text-center">
                      <span className="inline-block px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                        {s.status}
                      </span>
                    </td>
                    <td className="py-3 text-xs text-gray-600">{s.userDisplayName || s.userEmail || "—"}</td>
                    <td className="py-3 pr-2 text-xs text-gray-500">{formatDateTime(s.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </>
  );
}

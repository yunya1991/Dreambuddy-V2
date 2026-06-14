import Link from "next/link";

interface AdminNavItem {
  href: string;
  label: string;
  icon: string;
  group?: string;
}

const navItems: AdminNavItem[] = [
  { href: "/admin", label: "总览", icon: "📊", group: "监控" },
  { href: "/admin/users", label: "用户", icon: "👤", group: "监控" },
  { href: "/admin/strategies", label: "策略", icon: "🎯", group: "监控" },
  { href: "/admin/tasks", label: "任务", icon: "📋", group: "监控" },
  { href: "/admin/executions", label: "执行记录", icon: "📜", group: "监控" },
  { href: "/admin/api-configs", label: "API 配置", icon: "🔑", group: "配置" },
  { href: "/admin/trading-params", label: "交易参数", icon: "💰", group: "配置" },
  { href: "/admin/channels", label: "通信渠道", icon: "📡", group: "配置" },
  { href: "/admin/credits", label: "积分管理", icon: "💎", group: "财务" },
  { href: "/admin/orders", label: "充值订单", icon: "📦", group: "财务" },
  { href: "/admin/other", label: "数据沉淀", icon: "📂", group: "系统" },
];

export function AdminSidebar({ currentPath }: { currentPath: string }) {
  const groups: string[] = [];
  for (const item of navItems) {
    const g = item.group || "其他";
    if (groups.indexOf(g) === -1) groups.push(g);
  }

  return (
    <aside className="w-60 bg-white border-r border-gray-200 flex flex-col min-h-screen">
      <div className="p-4 border-b border-gray-200">
        <Link href="/admin" className="block">
          <div className="font-bold text-lg text-gray-900">Dream 管理系统</div>
          <div className="text-xs text-gray-500 mt-1">业务数据中台 v1.0</div>
        </Link>
      </div>

      <nav className="flex-1 p-3 space-y-4 overflow-y-auto">
        {groups.map((group) => (
          <div key={group}>
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide px-2 mb-2">
              {group}
            </div>
            <div className="space-y-1">
              {navItems
                .filter((item) => (item.group || "其他") === group)
                .map((item) => {
                  const isActive =
                    item.href === "/admin"
                      ? currentPath === "/admin" || currentPath === "/admin/"
                      : currentPath === item.href || currentPath.startsWith(item.href + "/");
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                        isActive
                          ? "bg-blue-50 text-blue-700 font-medium"
                          : "text-gray-700 hover:bg-gray-50"
                      }`}
                    >
                      <span className="text-base">{item.icon}</span>
                      <span>{item.label}</span>
                    </Link>
                  );
                })}
            </div>
          </div>
        ))}
      </nav>

      <div className="p-3 border-t border-gray-200 text-xs text-gray-500">
        <div className="flex items-center gap-2">
          <span>🗺️</span>
          <Link href="/ui-map" className="hover:text-blue-600 transition-colors">
            返回 UI Map 导航
          </Link>
        </div>
      </div>
    </aside>
  );
}

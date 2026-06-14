export function formatDateTime(date: Date | string | null | undefined): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function formatDate(date: Date | string | null | undefined): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function formatRelativeTime(date: Date | string | null | undefined): string {
  if (!date) return "—";
  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return "—";
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff} 秒前`;
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
  if (diff < 86400 * 365) return `${Math.floor(diff / (86400 * 30))} 个月前`;
  return `${Math.floor(diff / (86400 * 365))} 年前`;
}

export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return n.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCurrency(n: number | null | undefined, symbol = "¥"): string {
  if (n === null || n === undefined || isNaN(n)) return "—";
  return `${symbol}${n.toLocaleString("zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function truncate(str: string | null | undefined, maxLen = 50): string {
  if (!str) return "—";
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen) + "…";
}

export function getStatusLabel(status: string | null | undefined): string {
  if (!status) return "未知";
  const map: Record<string, string> = {
    active: "活跃",
    paused: "已暂停",
    stopped: "已停止",
    completed: "已完成",
    pending: "待处理",
    processing: "处理中",
    success: "成功",
    failed: "失败",
    cancelled: "已取消",
    expired: "已过期",
    applied: "已应用",
    draft: "草稿",
    verified: "已验证",
    unverified: "未验证",
    used: "已使用",
    created: "已创建",
  };
  return map[status] || status;
}

export function getStatusBadgeClass(status: string | null | undefined): string {
  const s = status || "";
  const success = ["active", "completed", "success", "verified", "applied", "used"];
  const warning = ["pending", "processing", "paused", "created"];
  const danger = ["failed", "stopped", "cancelled", "expired", "unverified"];
  const info = ["draft"];
  if (success.includes(s)) return "bg-green-100 text-green-800";
  if (warning.includes(s)) return "bg-yellow-100 text-yellow-800";
  if (danger.includes(s)) return "bg-red-100 text-red-800";
  if (info.includes(s)) return "bg-blue-100 text-blue-800";
  return "bg-gray-100 text-gray-800";
}

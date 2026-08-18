"use client";

import { useEffect, useState } from "react";

interface Segment {
  id: string;
  name: string;
  role: "FREE" | "PRO" | "ADMIN";
  count: number;
  description: string;
  color: string;
}

interface UserStats {
  total: number;
  byRole: { FREE: number; PRO: number; ADMIN: number };
}

const ROLE_COLORS: Record<string, string> = {
  FREE:  "#6366f1",
  PRO:   "#f59e0b",
  ADMIN: "#ef4444",
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  FREE:  "基础功能用户，可使用市场数据与分析",
  PRO:   "高级功能用户，可使用全量 AI 策略与执行",
  ADMIN: "系统管理员，可配置全局参数",
};

export default function SegmentsPage() {
  const [stats, setStats] = useState<UserStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/market/segments")
      .then(r => r.json())
      .then(json => {
        if (json.success) setStats(json.data);
        else setError(json.error ?? "加载失败");
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const segments: Segment[] = stats ? [
    { id: "free",  name: "免费用户",  role: "FREE",  count: stats.byRole.FREE,  color: ROLE_COLORS.FREE,  description: ROLE_DESCRIPTIONS.FREE  },
    { id: "pro",   name: "专业用户",  role: "PRO",   count: stats.byRole.PRO,   color: ROLE_COLORS.PRO,   description: ROLE_DESCRIPTIONS.PRO   },
    { id: "admin", name: "管理员",    role: "ADMIN", count: stats.byRole.ADMIN, color: ROLE_COLORS.ADMIN, description: ROLE_DESCRIPTIONS.ADMIN },
  ] : [];

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold mb-2">用户分层</h1>
        <p className="text-gray-400 text-sm mb-8">按角色分层的用户分布统计</p>

        {error && (
          <div className="rounded-lg bg-red-900/30 border border-red-700 p-4 mb-6 text-sm text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[0,1,2].map(i => <div key={i} className="h-32 rounded-xl bg-gray-900 animate-pulse" />)}
          </div>
        )}

        {stats && (
          <>
            {/* Total */}
            <div className="rounded-xl bg-gray-900 border border-gray-800 p-6 mb-6 flex items-center justify-between">
              <div>
                <p className="text-gray-400 text-sm">总用户数</p>
                <p className="text-4xl font-bold text-white mt-1">{stats.total.toLocaleString()}</p>
              </div>
              <div className="text-5xl opacity-20">👥</div>
            </div>

            {/* Segment cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {segments.map(seg => (
                <div
                  key={seg.id}
                  className="rounded-xl border p-5 flex flex-col gap-3"
                  style={{ borderColor: seg.color + "44", backgroundColor: "#111827" }}
                >
                  <div className="flex items-center justify-between">
                    <span
                      className="text-xs font-semibold px-2 py-0.5 rounded"
                      style={{ backgroundColor: seg.color + "22", color: seg.color }}
                    >
                      {seg.role}
                    </span>
                    <span className="text-2xl font-bold" style={{ color: seg.color }}>
                      {seg.count}
                    </span>
                  </div>
                  <div>
                    <h3 className="text-sm font-medium text-white">{seg.name}</h3>
                    <p className="text-xs text-gray-500 mt-1">{seg.description}</p>
                  </div>
                  <div className="mt-auto">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-gray-800">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: stats.total > 0 ? `${(seg.count / stats.total * 100).toFixed(1)}%` : "0%",
                            backgroundColor: seg.color,
                          }}
                        />
                      </div>
                      <span className="text-xs text-gray-400">
                        {stats.total > 0 ? (seg.count / stats.total * 100).toFixed(1) : 0}%
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
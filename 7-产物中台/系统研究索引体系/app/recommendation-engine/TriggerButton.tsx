"use client";

// ============================================================================
// 推荐策略引擎: 手动触发按钮
// ============================================================================

"use strict";

import { useState } from "react";

export default function TriggerButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{
    success: boolean;
    message?: string;
    error?: string;
  } | null>(null);

  const handleTrigger = async (force: boolean) => {
    setLoading(true);
    setResult(null);

    try {
      const resp = await fetch("/api/recommendation-engine/trigger", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force }),
      });
      const data = await resp.json();

      setResult({
        success: data.success,
        message: data.message || data.error,
      });
    } catch (e) {
      setResult({
        success: false,
        error: "触发失败，请检查引擎服务",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center gap-3">
      {/* 触发结果提示 */}
      {result && (
        <div
          className={`text-sm px-3 py-1.5 rounded-lg ${
            result.success
              ? "bg-green-50 text-green-700 border border-green-200"
              : "bg-red-50 text-red-700 border border-red-200"
          }`}
        >
          {result.message}
        </div>
      )}

      {/* 正常触发 */}
      <button
        onClick={() => handleTrigger(false)}
        disabled={loading}
        className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        {loading ? "运行中..." : "⚡ 手动触发"}
      </button>

      {/* 强制刷新 */}
      <button
        onClick={() => handleTrigger(true)}
        disabled={loading}
        className="px-4 py-2 text-sm bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 transition-colors"
      >
        {loading ? "运行中..." : "🔄 强制刷新"}
      </button>
    </div>
  );
}

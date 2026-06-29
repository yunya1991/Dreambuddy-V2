"use client";

import React, { useState } from "react";
import {
  formatTokenAmount,
  getLevelColor,
  getLevelLabel,
  getLevelBgColor,
} from "@/lib/token-monitor";
import type {
  TokenMonitorState,
  TokenMonitorConfig,
} from "@/lib/token-monitor";
import { TokenMonitorBadge } from "./TokenMonitorBadge";

interface TokenMonitorPanelProps {
  state: TokenMonitorState;
  config: TokenMonitorConfig;
  onCheckNow: () => Promise<void>;
  onPause: () => void;
  onResume: () => void;
  onUpdateConfig: (config: Partial<TokenMonitorConfig>) => void;
  onTriggerDowngrade?: () => void;
  onTriggerRecovery?: () => void;
}

export function TokenMonitorPanel({
  state,
  config,
  onCheckNow,
  onPause,
  onResume,
  onUpdateConfig,
  onTriggerDowngrade,
  onTriggerRecovery,
}: TokenMonitorPanelProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [isChecking, setIsChecking] = useState(false);

  const handleCheckNow = async () => {
    setIsChecking(true);
    try {
      await onCheckNow();
    } finally {
      setTimeout(() => setIsChecking(false), 500);
    }
  };

  const formatTime = (ts: number) => {
    if (!ts) return "从未";
    const d = new Date(ts);
    return d.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const formatDuration = (ms: number) => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} 分钟`;
    const hours = Math.floor(minutes / 60);
    return `${hours} 小时 ${minutes % 60} 分`;
  };

  const downgradeDuration = state.isDowngraded && state.downgradedAt
    ? formatDuration(Date.now() - state.downgradedAt)
    : null;

  return (
    <div
      className="rounded-xl p-5 w-full"
      style={{
        backgroundColor: "#121212",
        border: "1px solid #2a2a2a",
      }}
    >
      {/* 标题行 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ backgroundColor: "rgba(59, 130, 246, 0.15)" }}
          >
            <span className="text-blue-400">⚡</span>
          </div>
          <div>
            <h3 className="text-white font-semibold text-base">Token 监控</h3>
            <p className="text-gray-500 text-xs">
              自动监测余额，低余额时自动降级到经典指标系统
            </p>
          </div>
        </div>
        <TokenMonitorBadge state={state} showBalance={false} size="sm" />
      </div>

      {/* 主余额显示 */}
      <div className="mb-5">
        <div className="flex items-baseline gap-2 mb-2">
          <span
            className={`text-3xl font-bold tabular-nums ${getLevelColor(state.level)}`}
          >
            {formatTokenAmount(state.balance)}
          </span>
          <span className="text-gray-500 text-sm">tokens</span>
        </div>

        {/* 进度条 */}
        <div className="w-full h-2 rounded-full bg-gray-800 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${getLevelBgColor(state.level)}`}
            style={{
              width: `${Math.min(100, (state.balance / (config.dailyQuota || 50000)) * 100)}%`,
            }}
          />
        </div>

        <div className="flex justify-between mt-1.5 text-xs text-gray-500">
          <span>状态：{getLevelLabel(state.level)}</span>
          <span>
            {config.dailyQuota
              ? `${((state.balance / config.dailyQuota) * 100).toFixed(1)}%`
              : "绝对额度"}
          </span>
        </div>
      </div>

      {/* 自动降级状态 */}
      <div
        className="rounded-lg p-3 mb-4"
        style={{
          backgroundColor: state.isDowngraded
            ? "rgba(239, 68, 68, 0.1)"
            : "rgba(34, 197, 94, 0.08)",
          border: state.isDowngraded
            ? "1px solid rgba(239, 68, 68, 0.3)"
            : "1px solid rgba(34, 197, 94, 0.2)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">
              {state.isDowngraded ? "⚠️" : "✅"}
            </span>
            <div>
              <div
                className={`text-sm font-medium ${
                  state.isDowngraded ? "text-red-400" : "text-green-400"
                }`}
              >
                {state.isDowngraded
                  ? "已降级到经典指标系统"
                  : "大模型正常运行中"}
              </div>
              <div className="text-xs text-gray-500 mt-0.5">
                {state.isDowngraded
                  ? `已降级 ${downgradeDuration}，充值后自动恢复`
                  : "AI 驱动交易，监控运行中"}
              </div>
            </div>
          </div>

          {/* 自动降级开关 */}
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="text-xs text-gray-400">自动降级</span>
            <input
              type="checkbox"
              checked={state.autoDowngradeEnabled}
              onChange={(e) =>
                onUpdateConfig({ autoDowngradeEnabled: e.target.checked })
              }
              className="w-4 h-4 accent-blue-500"
            />
          </label>
        </div>
      </div>

      {/* 统计信息 */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        <StatItem
          label="累计消耗"
          value={formatTokenAmount(state.totalSpent)}
          color="text-gray-300"
        />
        <StatItem
          label="累计获取"
          value={formatTokenAmount(state.totalEarned)}
          color="text-green-400"
        />
        <StatItem
          label="检查次数"
          value={state.checkCount.toString()}
          color="text-blue-400"
        />
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center gap-2 mb-3">
        <button
          onClick={handleCheckNow}
          disabled={isChecking || state.status !== "running"}
          className="flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          style={{
            backgroundColor: "rgba(59, 130, 246, 0.15)",
            color: "#60a5fa",
            border: "1px solid rgba(59, 130, 246, 0.3)",
          }}
        >
          {isChecking ? "检查中..." : "立即检查"}
        </button>

        {state.status === "running" ? (
          <button
            onClick={onPause}
            className="py-2 px-3 rounded-lg text-sm font-medium transition-all"
            style={{
              backgroundColor: "rgba(156, 163, 175, 0.15)",
              color: "#9ca3af",
              border: "1px solid rgba(156, 163, 175, 0.3)",
            }}
          >
            暂停
          </button>
        ) : (
          <button
            onClick={onResume}
            className="py-2 px-3 rounded-lg text-sm font-medium transition-all"
            style={{
              backgroundColor: "rgba(34, 197, 94, 0.15)",
              color: "#4ade80",
              border: "1px solid rgba(34, 197, 94, 0.3)",
            }}
          >
            恢复
          </button>
        )}

        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="py-2 px-3 rounded-lg text-sm font-medium transition-all"
          style={{
            backgroundColor: "rgba(75, 85, 99, 0.2)",
            color: "#9ca3af",
            border: "1px solid rgba(75, 85, 99, 0.3)",
          }}
        >
          {showAdvanced ? "收起" : "高级"}
        </button>
      </div>

      {/* 最后检查时间 */}
      <div className="text-xs text-gray-600 text-center">
        最后检查：{formatTime(state.lastChecked)}
        {state.lastError && (
          <span className="text-red-500 ml-2">错误: {state.lastError}</span>
        )}
      </div>

      {/* 高级设置 */}
      {showAdvanced && (
        <div
          className="mt-4 pt-4 border-t"
          style={{ borderColor: "#2a2a2a" }}
        >
          <h4 className="text-sm font-medium text-gray-300 mb-3">高级设置</h4>

          <div className="space-y-3">
            {/* 检查间隔 */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                检查间隔：{config.checkIntervalMs / 1000 / 60} 分钟
              </label>
              <input
                type="range"
                min="1"
                max="30"
                step="1"
                value={config.checkIntervalMs / 1000 / 60}
                onChange={(e) =>
                  onUpdateConfig({
                    checkIntervalMs: parseInt(e.target.value) * 60 * 1000,
                  })
                }
                className="w-full accent-blue-500"
              />
            </div>

            {/* 低余额阈值 */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                低余额阈值：{config.lowBalanceThreshold}%
              </label>
              <input
                type="range"
                min="1"
                max="50"
                step="1"
                value={config.lowBalanceThreshold}
                onChange={(e) =>
                  onUpdateConfig({
                    lowBalanceThreshold: parseInt(e.target.value),
                  })
                }
                className="w-full accent-orange-500"
              />
            </div>

            {/* 恢复阈值 */}
            <div>
              <label className="text-xs text-gray-400 block mb-1">
                恢复阈值：{config.recoveryThreshold}%
              </label>
              <input
                type="range"
                min="10"
                max="80"
                step="5"
                value={config.recoveryThreshold}
                onChange={(e) =>
                  onUpdateConfig({
                    recoveryThreshold: parseInt(e.target.value),
                  })
                }
                className="w-full accent-green-500"
              />
            </div>

            {/* 测试按钮（开发用） */}
            {(onTriggerDowngrade || onTriggerRecovery) && (
              <div className="flex gap-2 pt-2">
                {onTriggerDowngrade && (
                  <button
                    onClick={onTriggerDowngrade}
                    className="flex-1 py-1.5 px-2 rounded text-xs font-medium"
                    style={{
                      backgroundColor: "rgba(239, 68, 68, 0.15)",
                      color: "#f87171",
                      border: "1px solid rgba(239, 68, 68, 0.3)",
                    }}
                  >
                    测试：触发降级
                  </button>
                )}
                {onTriggerRecovery && (
                  <button
                    onClick={onTriggerRecovery}
                    className="flex-1 py-1.5 px-2 rounded text-xs font-medium"
                    style={{
                      backgroundColor: "rgba(34, 197, 94, 0.15)",
                      color: "#4ade80",
                      border: "1px solid rgba(34, 197, 94, 0.3)",
                    }}
                  >
                    测试：恢复 AI
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function StatItem({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div
      className="rounded-lg p-3 text-center"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      <div className={`text-lg font-bold tabular-nums ${color}`}>{value}</div>
      <div className="text-xs text-gray-500 mt-0.5">{label}</div>
    </div>
  );
}

export default TokenMonitorPanel;

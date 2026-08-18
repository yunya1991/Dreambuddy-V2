"use client";

import React, { useState, useEffect, useCallback } from "react";
import Resistance3DDisplay, { Resistance3D } from "./fundamental/Resistance3DDisplay";
import SignalBadge, { TradingSignal } from "./fundamental/SignalBadge";
import ModuleCard, { AnalysisModule } from "./fundamental/ModuleCard";

interface OverallData {
  resistance_3d: Resistance3D;
  signal: TradingSignal;
  module_scores: {
    news: number;
    flow: number;
    sentiment: number;
    macro: number;
  };
}

interface Snapshot {
  ts: string;
  overall: OverallData;
  modules: {
    news: AnalysisModule;
    flow: AnalysisModule;
    sentiment: AnalysisModule;
    macro: AnalysisModule;
    [key: string]: AnalysisModule;
  };
}

function toNum(v: any, def = 0): number {
  if (typeof v === "number" && isFinite(v)) return v;
  if (typeof v === "string" && v.trim()) {
    const n = parseFloat(v);
    return isFinite(n) ? n : def;
  }
  return def;
}

function dirColorFromScore(v: number): string {
  if (v > 0.1) return "#22c55e";
  if (v < -0.1) return "#ef4444";
  return "#eab308";
}

function moduleLabel(name: string): string {
  const labels: Record<string, string> = {
    news: "📰 新闻",
    flow: "💵 资金流",
    sentiment: "📈 情绪",
    macro: "🌐 宏观",
  };
  return labels[name] || name;
}

function ModuleScoreBar({
  label,
  score,
  color,
}: {
  label: string;
  score: number;
  color: string;
}) {
  const pct = ((score + 1) / 2) * 100;
  const widthPct = Math.abs(pct - 50);
  const leftPct = score >= 0 ? 50 : 50 - widthPct;

  return (
    <div className="mb-2 last:mb-0">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-[#9ca3af]">{label}</span>
        <span className="text-xs font-mono" style={{ color, opacity: 0.9 }}>
          {score >= 0 ? "+" : ""}
          {score.toFixed(3)}
        </span>
      </div>
      <div
        className="relative bg-[#1f1f1f] rounded-full overflow-hidden"
        style={{ height: 3 }}
      >
        <div
          className="absolute top-0 bottom-0"
          style={{ left: "50%", width: 1, backgroundColor: "#3f3f3f" }}
        />
        <div
          className="absolute top-0 bottom-0 rounded-full"
          style={{
            left: `${leftPct}%`,
            width: `${widthPct}%`,
            backgroundColor: color,
            opacity: 0.75,
          }}
        />
      </div>
    </div>
  );
}

export default function FundamentalPanel() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/fundamental/snapshot", {
        cache: "no-store",
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: Snapshot = await res.json();
      if (data && data.overall) {
        setSnapshot(data);
        setLastUpdated(new Date().toLocaleString("zh-CN"));
      } else {
        throw new Error("数据格式不正确");
      }
    } catch (e: any) {
      setError(`无法连接后端服务`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 120_000);
    return () => clearInterval(timer);
  }, [loadData]);

  // 将后端返回的原始数据映射到组件期望的结构
  const moduleToAnalysisModule = (raw: any, key: string): any => {
    const r3d = raw?.resistance_3d || {};
    const rawMetrics = raw?.metrics || {};
    const rawEvents = raw?.events || [];
    const rawSignals = raw?.signals || [];

    // 从 resistance_3d 派生简单指标
    const dirScore = toNum(r3d.direction_score);
    const vel = toNum(r3d.velocity);
    const acc = toNum(r3d.acceleration);
    const conf = toNum(r3d.confidence);

    // 派生 heat/sentiment/flow 指标（从 resistance_3d 推算）
    const heatScore = Math.min(1, Math.max(0, (Math.abs(vel) + Math.abs(acc)) / 2));
    const sentIdx = dirScore;
    const flowIdx = vel;

    // 派生简单事件计数（过滤掉非简单类型的字段）
    let eventCount = 0;
    if (Array.isArray(rawEvents)) {
      eventCount = rawEvents.length;
    } else if (typeof rawMetrics?.count === "number") {
      eventCount = rawMetrics.count;
    }

    // 压力级别派生
    const stressScore = Math.abs(vel) + Math.abs(acc);
    const stressLevel =
      stressScore > 1.0 ? "高" : stressScore > 0.5 ? "中" : "低";

    // 将 events 数组映射到 TimelineEvent 格式
    const timeline = rawEvents.map((e: any, i: number) => ({
      id: e.id || `${key}_ev_${i}`,
      timestamp: e.timestamp || e.published_at || raw.ts || new Date().toISOString(),
      title: e.title || e.content || `事件 #${i + 1}`,
      sentiment: toNum(e.sentiment, dirScore),
      category: e.category || e.query || key,
      impact_score: toNum(e.impact_score, heatScore * 100),
      source: e.source,
    }));

    // 信号映射（确保有字段）
    const signals = rawSignals.length > 0
      ? rawSignals.map((s: any) => ({
          type: s.type || "hold",
          strength: toNum(s.strength, 0.5),
          reason: s.reason || "",
          horizon: s.horizon || "short",
          confidence: toNum(s.confidence, conf),
          factors: s.factors || [],
          id: s.id,
          created_at: s.created_at,
        }))
      : [
          {
            type: dirScore > 0.2 ? "buy" : dirScore < -0.2 ? "sell" : "hold",
            strength: Math.abs(dirScore),
            reason: r3d.trend_summary || "",
            horizon: "short",
            confidence: conf,
          },
        ];

    return {
      name: key,
      ts: raw?.ts,
      resistance_3d: r3d,
      metrics: {
        event_count: eventCount,
        heat_score: heatScore,
        sentiment_index: sentIdx,
        flow_index: flowIdx,
        narrative_consensus: dirScore,
        stress_level: stressLevel,
      },
      signals: signals,
      timeline: timeline,
    };
  };

  const modulesList = snapshot?.modules
    ? (["news", "flow", "sentiment", "macro"] as const)
        .filter((k) => snapshot.modules[k] && snapshot.modules[k].resistance_3d)
        .map((k) => ({
          key: k,
          data: moduleToAnalysisModule(snapshot.modules[k], k),
        }))
    : [];

  const handleReturnToDashboard = () => {
    window.location.href = "/dashboard";
  };

  return (
    <div
      className="min-h-0 overflow-y-auto flex-1"
      style={{ backgroundColor: "#0d0d0d", color: "#e0e0e0", padding: 20 }}
    >
      <div
        className="flex items-center justify-between mb-4 flex-wrap gap-2"
      >
        <div className="flex items-center gap-3">
          <button
            onClick={handleReturnToDashboard}
            className="px-3 py-1.5 rounded-md text-sm text-white transition hover:opacity-80"
            style={{ backgroundColor: "#1f2937" }}
            title="返回对话窗口主页面"
          >
            ← 返回主界面
          </button>
          <h2 className="text-xl font-bold text-white mb-0">
            🧭 基本面分析 V2
          </h2>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-[#8a8a8a]">🕐 {lastUpdated}</span>
          )}
          {snapshot?.ts && (
            <span className="text-xs text-[#6b7280] font-mono">
              {snapshot.ts.replace("T", " ").replace("Z", " UTC")}
            </span>
          )}
          <button
            onClick={loadData}
            disabled={loading}
            className="px-3 py-1.5 rounded-md text-sm text-white transition disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              backgroundColor: loading ? "#374151" : "#0066ff",
            }}
            onMouseEnter={(e) => {
              if (!loading) e.currentTarget.style.backgroundColor = "#0052cc";
            }}
            onMouseLeave={(e) => {
              if (!loading) e.currentTarget.style.backgroundColor = "#0066ff";
            }}
          >
            {loading ? "加载中..." : "🔄 刷新"}
          </button>
        </div>
      </div>

      {error && !snapshot && (
        <div
          className="mb-4 p-3 rounded-md text-sm"
          style={{
            backgroundColor: "#2a1a1a",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#fca5a5",
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {loading && !snapshot && (
        <div className="flex items-center justify-center py-20">
          <div className="text-[#6b7280] text-sm">加载中...</div>
        </div>
      )}

      {snapshot && (
        <>
          <div
            className="rounded-xl mb-4 grid gap-4"
            style={{
              backgroundColor: "#1a1a1a",
              border: "1px solid #2a2a2a",
              padding: 16,
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
            }}
          >
            <div>
              <div className="text-sm font-semibold text-white mb-2">
                🧭 综合三维
              </div>
              <Resistance3DDisplay
                data={snapshot.overall.resistance_3d}
                size="md"
              />
            </div>

            <div>
              <div className="text-sm font-semibold text-white mb-2">
                🎯 综合信号
              </div>
              <SignalBadge signal={snapshot.overall.signal} size="md" />
            </div>

            <div>
              <div className="text-sm font-semibold text-white mb-2">
                📊 模块得分雷达
              </div>
              <div
                className="rounded-lg"
                style={{ backgroundColor: "#121212", padding: 16 }}
              >
                {Object.entries(snapshot.overall.module_scores || {}).map(
                  ([key, value]) => {
                    const score = toNum(value);
                    return (
                      <ModuleScoreBar
                        key={key}
                        label={moduleLabel(key)}
                        score={score}
                        color={dirColorFromScore(score)}
                      />
                    );
                  }
                )}
              </div>
            </div>
          </div>

          {modulesList.length > 0 && (
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fit, minmax(320px, 1fr))",
              }}
            >
              {modulesList.map(({ key, data }) => (
                <ModuleCard
                  key={key}
                  module={{
                    ...data,
                    name: data.name || key,
                  }}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

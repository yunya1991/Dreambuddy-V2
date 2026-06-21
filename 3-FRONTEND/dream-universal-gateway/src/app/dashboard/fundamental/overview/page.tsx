"use client";

import React, { useState, useEffect, useCallback } from "react";
import CompositeDashboard from "../components/CompositeDashboard";
import SignalCard from "../components/SignalCard";
import MetricsGrid from "../components/MetricsGrid";
import ResistanceChart from "../components/ResistanceChart";

interface TopSignal {
  type: string;
  reason: string;
  strength?: number;
  confidence?: number;
  module?: string;
}

interface CompositeSection {
  score: number;
  confidence: number;
  strength: number;
  recommendation: string;
  reasons: string[];
  module_consensus: Record<string, string>;
  cross_module_validation: {
    consistency_score: number;
    divergent_modules: string[];
  };
  best_opportunities: Array<{ module: string; signal: string; reason: string; strength: number }>;
  risk_warnings: string[];
  top_signals: TopSignal[];
  avg_velocity?: number;
  avg_acceleration?: number;
  timeseries?: Array<{
    ts: string;
    direction_score: number;
    velocity?: number;
    acceleration?: number;
  }>;
}

interface CompositeData {
  ts: string;
  composite: CompositeSection;
  summary?: string;
  module_count?: number;
  modules_used?: string[];
}

interface Resistance3D {
  direction: "up" | "down" | "neutral";
  direction_score: number;
  velocity: number;
  acceleration: number;
  confidence: number;
  data_points: number;
  trend_summary?: string;
}

interface TradingSignal {
  id?: string;
  type: string;
  strength?: number;
  confidence?: number;
  reason?: string;
  horizon?: string;
  factors?: string[];
  created_at?: string;
}

interface TimeseriesPoint {
  ts: string;
  direction_score: number;
  velocity: number;
  acceleration: number;
  sentiment?: number;
  event_count?: number;
}

interface ModuleSnapshot {
  module: string;
  ts: string;
  resistance_3d: Resistance3D;
  signals: TradingSignal[];
  metrics: Record<string, number | string>;
  timeseries: TimeseriesPoint[];
}

interface OverallData {
  resistance_3d: Resistance3D;
  signal?: TradingSignal;
  signals?: TradingSignal[];
  module_scores?: Record<string, number>;
  timeseries?: TimeseriesPoint[];
}

interface Snapshot {
  ts: string;
  overall: OverallData;
  modules: Record<string, ModuleSnapshot>;
}

const BASE_MODULES: Array<{ key: string; label: string; emoji: string }> = [
  { key: "news", label: "新闻", emoji: "📰" },
  { key: "flow", label: "资金流", emoji: "💵" },
  { key: "sentiment", label: "情绪", emoji: "📈" },
  { key: "macro", label: "宏观", emoji: "🌐" },
];

const directionColor = (dir: string | undefined): string => {
  if (!dir) return "#eab308";
  const d = dir.toLowerCase();
  if (d === "up" || d === "bullish" || d === "看涨") return "#22c55e";
  if (d === "down" || d === "bearish" || d === "看跌") return "#ef4444";
  return "#eab308";
};

const scoreColor = (score: number): string => {
  if (score > 0.1) return "#22c55e";
  if (score < -0.1) return "#ef4444";
  return "#eab308";
};

const normalizeType = (type: string): string => {
  const t = (type || "").toLowerCase().trim();
  const map: Record<string, string> = {
    强烈买入: "strong_buy",
    强买: "strong_buy",
    买入: "buy",
    观望: "hold",
    中性: "hold",
    neutral: "hold",
    减仓: "reduce",
    卖出: "sell",
    强卖: "strong_sell",
    强烈卖出: "strong_sell",
    风险: "risk_alert",
  };
  return map[t] || map[type] || t || "hold";
};

function deriveModuleTimeseries(raw: any): TimeseriesPoint[] {
  const ts = raw?.timeseries || [];
  if (Array.isArray(ts) && ts.length > 0) {
    return ts
      .filter((p: any) => p && (typeof p.value === "number" || typeof p.direction_score === "number"))
      .map((p: any, i: number) => ({
        ts: p.timestamp || p.ts || new Date(Date.now() - (ts.length - i) * 3600000).toISOString(),
        direction_score: p.direction_score ?? p.value ?? 0,
        velocity: p.velocity ?? 0,
        acceleration: p.acceleration ?? 0,
        sentiment: p.sentiment ?? (p.direction_score ?? 0),
        event_count: p.event_count ?? 0,
      }));
  }
  const r3d = raw?.resistance_3d || {};
  return [{
    ts: raw?.ts || new Date().toISOString(),
    direction_score: typeof r3d.direction_score === "number" ? r3d.direction_score : 0,
    velocity: typeof r3d.velocity === "number" ? r3d.velocity : 0,
    acceleration: typeof r3d.acceleration === "number" ? r3d.acceleration : 0,
    sentiment: typeof r3d.direction_score === "number" ? r3d.direction_score : 0,
    event_count: 0,
  }];
}

function ModuleCard({
  label,
  emoji,
  snapshot,
  consensus,
}: {
  label: string;
  emoji: string;
  snapshot: ModuleSnapshot | null;
  consensus?: string;
}) {
  if (!snapshot || !snapshot.resistance_3d) {
    return (
      <div
        style={{
          backgroundColor: "#1a1a1a",
          border: "1px solid #2a2a2a",
          borderRadius: 12,
          padding: 20,
        }}
      >
        <div style={{ fontSize: 13, color: "#e0e0e0", marginBottom: 8, fontWeight: 600 }}>
          {emoji} {label}
        </div>
        <div style={{ fontSize: 13, color: "#6b7280" }}>暂无数据</div>
      </div>
    );
  }

  const r3d = snapshot.resistance_3d;
  const dirColor = directionColor(consensus || r3d.direction);
  const score = r3d.direction_score;

  const firstSignal =
    (snapshot.signals && snapshot.signals[0]) || null;

  const metrics: Record<string, number | string> = {};
  const rawScore = typeof score === "number" && isFinite(score) ? score : 0;
  const vel = typeof r3d.velocity === "number" && isFinite(r3d.velocity) ? r3d.velocity : 0;
  const acc = typeof r3d.acceleration === "number" && isFinite(r3d.acceleration) ? r3d.acceleration : 0;
  const confVal = typeof r3d.confidence === "number" && isFinite(r3d.confidence) ? r3d.confidence : 0.5;

  metrics["方向得分"] = Number(rawScore.toFixed(3));
  metrics["置信度"] = `${(confVal * 100).toFixed(0)}%`;
  metrics["速度"] = Number(vel.toFixed(3));
  metrics["加速度"] = Number(acc.toFixed(3));

  const highlight: Record<string, "up" | "down" | "neutral"> = {
    方向得分: score > 0.1 ? "up" : score < -0.1 ? "down" : "neutral",
  };

  const rawMetrics = snapshot.metrics || {};
  const extraKeys = Object.keys(rawMetrics).slice(0, 2);
  extraKeys.forEach((k) => {
    metrics[k] = rawMetrics[k];
  });

  return (
    <div
      style={{
        backgroundColor: "#1a1a1a",
        border: "1px solid #2a2a2a",
        borderRadius: 12,
        padding: 20,
        display: "flex",
        flexDirection: "column",
        gap: 16,
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: 4,
          backgroundColor: dirColor,
        }}
      />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>{emoji}</span>
          <span style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0" }}>{label}</span>
        </div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: "3px 8px",
            borderRadius: 4,
            backgroundColor: dirColor + "22",
            color: dirColor,
          }}
        >
          {consensus || (r3d.direction === "up" ? "看涨" : r3d.direction === "down" ? "看跌" : "中性")}
        </div>
      </div>

      <MetricsGrid metrics={metrics} columns={2} highlight={highlight} />

      {firstSignal && firstSignal.reason && (
        <div
          style={{
            backgroundColor: "#0d0d0d",
            border: "1px solid #2a2a2a",
            borderRadius: 8,
            padding: "10px 12px",
          }}
        >
          <div style={{ fontSize: 11, color: "#8a8a8a", marginBottom: 4 }}>TOP 信号</div>
          <div style={{ fontSize: 13, color: "#e0e0e0", lineHeight: 1.5 }}>
            {firstSignal.reason}
          </div>
        </div>
      )}

      <div
        style={{
          height: 4,
          borderRadius: 2,
          backgroundColor: dirColor,
          opacity: 0.6,
        }}
      />
    </div>
  );
}

export default function OverviewPage() {
  const [composite, setComposite] = useState<CompositeData | null>(null);
  const [moduleSnapshots, setModuleSnapshots] = useState<Record<string, ModuleSnapshot>>({});
  const [snapshotFallback, setSnapshotFallback] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);

    let compositeOk = false;
    let compositeData: CompositeData | null = null;
    let snapshotData: Snapshot | null = null;
    const modules: Record<string, ModuleSnapshot> = {};

    try {
      const compositeRes = await fetch("/api/fundamental/composite-signal", {
        cache: "no-store",
      });
      if (compositeRes.ok) {
        const body = await compositeRes.json();
        if (body && body.composite && !body.error) {
          compositeData = body as CompositeData;
          compositeOk = true;
        }
      }
    } catch (e) {
      // ignore
    }

    try {
      const snapshotRes = await fetch("/api/fundamental/snapshot", {
        cache: "no-store",
      });
      if (snapshotRes.ok) {
        const body = await snapshotRes.json();
        if (body && body.overall && !body.error) {
          snapshotData = body as Snapshot;
        }
      }
    } catch (e) {
      // ignore
    }

    for (const m of BASE_MODULES) {
      try {
        const res = await fetch(`/api/fundamental/${m.key}/snapshot`, { cache: "no-store" });
        if (res.ok) {
          const body = await res.json();
          if (body && body.resistance_3d && !body.error) {
            modules[m.key] = body as ModuleSnapshot;
          }
        }
      } catch (e) {
        // ignore
      }
    }

    if (snapshotData && snapshotData.modules) {
      BASE_MODULES.forEach((m) => {
        if (!modules[m.key] && snapshotData!.modules[m.key]) {
          modules[m.key] = snapshotData!.modules[m.key];
        }
      });
    }

    if (compositeOk) {
      setComposite(compositeData);
    } else if (snapshotData) {
      const r3d = snapshotData.overall.resistance_3d;
      const dirScore = r3d.direction_score || 0;
      const rec =
        dirScore >= 0.3 ? "强烈买入" :
        dirScore >= 0.1 ? "买入" :
        dirScore <= -0.3 ? "强烈卖出" :
        dirScore <= -0.1 ? "卖出" : "观望";

      const topSignals: TopSignal[] = [];
      const overallSignals = snapshotData.overall.signals || (snapshotData.overall.signal ? [snapshotData.overall.signal] : []);
      overallSignals.forEach((s) => {
        if (s && s.reason) {
          topSignals.push({
            type: normalizeType(s.type),
            reason: s.reason,
            strength: s.strength,
            confidence: s.confidence,
          });
        }
      });
      BASE_MODULES.forEach((m) => {
        const mod = modules[m.key] || snapshotData!.modules[m.key];
        if (mod && mod.signals && mod.signals[0] && mod.signals[0].reason) {
          const sig = mod.signals[0];
          topSignals.push({
            type: normalizeType(sig.type),
            reason: sig.reason,
            strength: sig.strength,
            confidence: sig.confidence,
            module: m.label,
          });
        }
      });

      const consistency =
        Math.max(
          0,
          Math.min(
            100,
            100 -
              BASE_MODULES.reduce((acc, m) => {
                const mod = modules[m.key] || snapshotData!.modules[m.key];
                return acc + Math.abs((mod?.resistance_3d?.direction_score || 0) - dirScore);
              }, 0) * 50
          )
        );

      setComposite({
        ts: snapshotData.ts || new Date().toISOString(),
        summary: snapshotData.overall.resistance_3d.trend_summary || "基于 4 个基础模块信号聚合生成的综合信号。",
        composite: {
          score: dirScore,
          confidence: r3d.confidence || 0.5,
          strength: Math.round(Math.abs(dirScore) * 100),
          recommendation: rec,
          reasons: [
            `综合方向得分 ${dirScore.toFixed(3)}`,
            `模块速度 ${(r3d.velocity || 0).toFixed(3)}，加速度 ${(r3d.acceleration || 0).toFixed(3)}`,
            "模块信号聚合推导",
          ],
          module_consensus: {},
          cross_module_validation: {
            consistency_score: consistency,
            divergent_modules: [],
          },
          best_opportunities: [],
          risk_warnings: [],
          top_signals: topSignals.slice(0, 6),
          avg_velocity: r3d.velocity,
          avg_acceleration: r3d.acceleration,
          timeseries: snapshotData.overall.timeseries || undefined,
        },
        module_count: BASE_MODULES.length,
        modules_used: BASE_MODULES.map((m) => m.key),
      });
      setSnapshotFallback(snapshotData);
    }

    setModuleSnapshots(modules);

    if (!compositeData && !snapshotData) {
      setError("无法获取基本面综合信号，请稍后重试");
    } else {
      setLastUpdated(new Date().toLocaleString("zh-CN"));
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 120_000);
    return () => clearInterval(timer);
  }, [loadData]);

  const handleReturnToDashboard = () => {
    window.location.href = "/dashboard";
  };

  const chartTimeseries = (() => {
    const compositeTs = composite?.composite?.timeseries;
    if (compositeTs && compositeTs.length > 0) {
      return compositeTs.map((p) => ({
        ts: p.ts,
        direction_score: p.direction_score,
        velocity: typeof p.velocity === "number" ? p.velocity : 0,
        acceleration: typeof p.acceleration === "number" ? p.acceleration : 0,
      }));
    }
    const points: TimeseriesPoint[] = [];
    for (const m of BASE_MODULES) {
      const mod = moduleSnapshots[m.key];
      const ts = deriveModuleTimeseries(mod);
      ts.forEach((p) => {
        points.push({
          ts: p.ts,
          direction_score: p.direction_score,
          velocity: p.velocity,
          acceleration: p.acceleration,
        });
      });
    }
    if (points.length === 0) return [];
    const byTs: Record<string, { sum: number; count: number; vSum: number; aSum: number }> = {};
    points.forEach((p) => {
      const key = p.ts;
      if (!byTs[key]) byTs[key] = { sum: 0, count: 0, vSum: 0, aSum: 0 };
      byTs[key].sum += p.direction_score;
      byTs[key].vSum += p.velocity;
      byTs[key].aSum += p.acceleration;
      byTs[key].count += 1;
    });
    return Object.keys(byTs)
      .sort()
      .map((ts) => ({
        ts,
        direction_score: byTs[ts].sum / byTs[ts].count,
        velocity: byTs[ts].vSum / byTs[ts].count,
        acceleration: byTs[ts].aSum / byTs[ts].count,
      }));
  })();

  const aggregatedTopSignals: TopSignal[] = (() => {
    const fromComposite = composite?.composite?.top_signals || [];
    if (fromComposite.length > 0) return fromComposite;
    const out: TopSignal[] = [];
    for (const m of BASE_MODULES) {
      const mod = moduleSnapshots[m.key];
      const sig = mod?.signals?.[0];
      if (sig && sig.reason) {
        out.push({
          type: normalizeType(sig.type),
          reason: sig.reason,
          strength: sig.strength,
          confidence: sig.confidence,
          module: m.label,
        });
      }
    }
    return out;
  })();

  return (
    <div
      className="flex flex-col h-full"
      style={{ backgroundColor: "#0d0d0d", minHeight: "100vh" }}
    >
      <div
        className="flex items-center justify-between px-6 py-4 border-b"
        style={{ borderColor: "#2a2a2a", backgroundColor: "#1a1a1a" }}
      >
        <div className="flex items-center gap-3">
          <button
            onClick={handleReturnToDashboard}
            className="px-3 py-1.5 rounded-md text-sm text-white transition hover:opacity-80"
            style={{ backgroundColor: "#374151" }}
          >
            ← 返回主界面
          </button>
          <h1 className="text-lg font-semibold text-white">📊 基本面分析总览</h1>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdated && (
            <span className="text-xs text-[#8a8a8a]">🕐 {lastUpdated}</span>
          )}
          <button
            onClick={loadData}
            disabled={loading}
            className="px-3 py-1.5 rounded-md text-sm text-white transition disabled:opacity-50"
            style={{ backgroundColor: loading ? "#374151" : "#3b82f6" }}
          >
            {loading ? "加载中..." : "🔄 刷新"}
          </button>
        </div>
      </div>

      {error && !composite && (
        <div
          className="m-6 p-4 rounded-md"
          style={{
            backgroundColor: "#2a1a1a",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "#fca5a5",
          }}
        >
          ⚠️ {error}
        </div>
      )}

      {loading && !composite && (
        <div className="flex items-center justify-center flex-1">
          <div className="text-[#6b7280] text-sm">加载中...</div>
        </div>
      )}

      {composite && (
        <div
          className="flex-1 overflow-y-auto"
          style={{ padding: 20, display: "flex", flexDirection: "column", gap: 20 }}
        >
          {/* 区 A - 综合信号仪表盘 */}
          <CompositeDashboard
            score={composite.composite.score}
            confidence={composite.composite.confidence}
            strength={composite.composite.strength}
            recommendation={composite.composite.recommendation}
            reasons={composite.composite.reasons}
            consistency={composite.composite.cross_module_validation.consistency_score}
            divergentModules={composite.composite.cross_module_validation.divergent_modules}
            topSignals={composite.composite.top_signals}
            riskWarnings={composite.composite.risk_warnings}
            summary={composite.summary}
            updatedAt={lastUpdated || composite.ts}
          />

          {/* 区 B - 四大模块卡片 2x2 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, 1fr)",
              gap: 16,
            }}
          >
            {BASE_MODULES.map((m) => {
              const mod = moduleSnapshots[m.key] || null;
              const consensus = composite.composite.module_consensus?.[m.key];
              return (
                <ModuleCard
                  key={m.key}
                  label={m.label}
                  emoji={m.emoji}
                  snapshot={mod}
                  consensus={consensus}
                />
              );
            })}
          </div>

          {/* 区 C - 综合精选信号 */}
          <SignalCard signals={aggregatedTopSignals} title="📋 综合精选信号" maxItems={6} />

          {/* 区 D - 三维度趋势图 */}
          <div
            style={{
              backgroundColor: "#1a1a1a",
              border: "1px solid #2a2a2a",
              borderRadius: 12,
              padding: 20,
            }}
          >
            <div
              style={{
                fontSize: 14,
                fontWeight: 600,
                color: "#e0e0e0",
                marginBottom: 12,
              }}
            >
              📈 三维度趋势（综合方向得分 / 速度 / 加速度）
            </div>
            {chartTimeseries.length > 1 ? (
              <ResistanceChart timeseries={chartTimeseries} />
            ) : (
              <div
                style={{
                  backgroundColor: "#0d0d0d",
                  border: "1px solid #2a2a2a",
                  borderRadius: 8,
                  minHeight: 300,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#6b7280",
                  fontSize: 13,
                }}
              >
                暂无趋势数据
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

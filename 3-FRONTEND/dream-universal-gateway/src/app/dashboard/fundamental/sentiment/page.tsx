'use client';
import React, { useState, useEffect, useCallback } from "react";
import ResearchHeader from "../components/ResearchHeader";
import ResistanceChart from "../components/ResistanceChart";
import MetricsGrid from "../components/MetricsGrid";
import SignalCard from "../components/SignalCard";
import GaugeDisplay from "../components/GaugeDisplay";
import EventTimeline from "../components/EventTimeline";
import SentimentHeatmap from "../components/SentimentHeatmap";

const MODULE = "sentiment";
const ENDPOINT = `/api/fundamental/${MODULE}/snapshot`;

interface Snapshot {
  module: string;
  ts: string;
  resistance_3d: {
    direction: "up" | "down" | "neutral";
    direction_score: number;
    velocity: number;
    acceleration: number;
    confidence: number;
    data_points: number;
    trend_summary: string;
  };
  signals: Array<{
    type: string;
    strength: number;
    confidence: number;
    reason: string;
    horizon?: string;
    factors?: string[];
  }>;
  metrics: { core: Record<string, any>; breakdown: Record<string, any> };
  metrics_flat: Record<string, number | string>;
  events: Array<{
    title: string;
    content?: string;
    category?: string;
    impact_score?: number;
    sentiment?: number;
    source?: string;
    published_at?: string;
    timestamp?: string;
  }>;
  timeseries: Array<{
    timestamp?: string;
    ts?: string;
    value?: number;
    direction_score?: number;
    velocity?: number;
    acceleration?: number;
  }>;
  heatmap_data?: Array<{
    category: string;
    score: number;
    label?: string;
  }>;
}

const displayNames: Record<string, string> = {
  sentiment_index: "情绪指数",
  fear_greed_index: "恐惧贪婪",
  narrative_heat: "叙事热度",
  consensus_level: "共识强度",
  reversal_risk: "反转风险",
  social_volume: "社交量",
  contrarian_signal: "反向操作信号",
  market_psychology: "市场心理",
  twitter_sentiment: "Twitter情绪",
  reddit_sentiment: "Reddit情绪",
  news_sentiment: "新闻情绪",
  search_trend: "搜索热度",
};

const normalizeTs = (arr: any[]) =>
  arr?.map((p, i) => ({
    ts: p.ts || p.timestamp || new Date(Date.now() - (arr.length - i) * 3600000).toISOString(),
    direction_score: typeof p.direction_score === "number" ? p.direction_score : (p.value ?? 0),
    velocity: typeof p.velocity === "number" ? p.velocity : 0,
    acceleration: typeof p.acceleration === "number" ? p.acceleration : 0,
  })) || [];

const normalizeEvents = (events: any[]) =>
  events?.map((e, i) => ({
    id: e.id || `ev-${i}`,
    timestamp: e.timestamp || e.published_at || new Date().toISOString(),
    title: e.title || "未命名事件",
    category: e.category || "通用",
    sentiment: typeof e.sentiment === "number" ? e.sentiment : 0,
    impact_score: typeof e.impact_score === "number" ? e.impact_score : 0,
    source: e.source || "-",
  })) || [];

function toNum(v: any): number {
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const parsed = parseFloat(v);
    return isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

export default function SentimentPage() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(ENDPOINT, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result: Snapshot = await res.json();
      setData(result);
      setLastUpdated(new Date().toLocaleString("zh-CN"));
    } catch {
      setError("无法连接后端服务");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
    const timer = setInterval(loadData, 120000);
    return () => clearInterval(timer);
  }, [loadData]);

  const flat = data?.metrics_flat || {};

  const fgValue =
    flat.fear_greed_index !== undefined
      ? Math.round(toNum(flat.fear_greed_index))
      : Math.round(toNum(flat.sentiment_index));

  const fgLabel =
    fgValue >= 80 ? "极度贪婪" :
    fgValue >= 60 ? "贪婪" :
    fgValue >= 40 ? "中性" :
    fgValue >= 20 ? "恐惧" : "极度恐惧";

  const fgColor =
    fgValue >= 80 ? "#22c55e" :
    fgValue >= 60 ? "#4ade80" :
    fgValue >= 40 ? "#f59e0b" :
    fgValue >= 20 ? "#f97316" : "#ef4444";

  const sideMetrics: Record<string, number | string> = {};
  ["narrative_heat", "consensus_level", "reversal_risk", "social_volume"].forEach((k) => {
    if (flat[k] !== undefined) sideMetrics[k] = flat[k];
  });

  const coreMetrics: Record<string, number | string> = {};
  [
    "sentiment_index",
    "fear_greed_index",
    "narrative_heat",
    "consensus_level",
    "reversal_risk",
    "social_volume",
    "contrarian_signal",
    "market_psychology",
    "twitter_sentiment",
    "reddit_sentiment",
    "news_sentiment",
    "search_trend",
  ].forEach((k) => {
    if (flat[k] !== undefined) coreMetrics[k] = flat[k];
  });

  const heatmapData = data?.heatmap_data || [
    { category: "社交媒体", score: toNum(flat.twitter_sentiment || flat.social_volume || 55) },
    { category: "新闻舆情", score: toNum(flat.news_sentiment || 48) },
    { category: "搜索热度", score: toNum(flat.search_trend || 62) },
    { category: "衍生品", score: 35 + Math.random() * 20 },
    { category: "资金流向", score: 70 + Math.random() * 10 },
    { category: "链上活动", score: 42 + Math.random() * 15 },
    { category: "宏观环境", score: 30 + Math.random() * 25 },
    { category: "技术面", score: 58 + Math.random() * 15 },
  ];

  return (
    <div className="flex flex-col h-full">
      <ResearchHeader
        module={MODULE}
        title="📈 情绪研究"
        onRefresh={loadData}
        lastUpdated={lastUpdated}
        loading={loading}
      />

      {error && !data && (
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

      {loading && !data && (
        <div className="flex items-center justify-center flex-1">
          <div className="text-[#6b7280] text-sm">加载中...</div>
        </div>
      )}

      {data && (
        <div className="flex-1 overflow-y-auto p-6" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* 第一行：恐惧贪婪仪表 + 状态卡片 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 3fr",
              gap: 16,
            }}
          >
            <div
              style={{
                backgroundColor: "#1a1a1a",
                border: "1px solid #2a2a2a",
                borderRadius: 12,
                padding: 24,
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 14, color: "#8a8a8a", marginBottom: 12 }}>
                恐惧贪婪指数
              </div>
              <div style={{ fontSize: 48, fontWeight: 700, color: fgColor, marginBottom: 8 }}>
                {fgValue}
              </div>
              <div style={{ fontSize: 16, fontWeight: 500, color: fgColor }}>
                {fgLabel}
              </div>
              <div
                style={{
                  marginTop: 16,
                  height: 8,
                  backgroundColor: "#2a2a2a",
                  borderRadius: 4,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${fgValue}%`,
                    height: "100%",
                    backgroundColor: fgColor,
                    transition: "width 0.3s ease",
                  }}
                />
              </div>
              <div
                style={{
                  marginTop: 8,
                  fontSize: 11,
                  color: "#8a8a8a",
                  display: "flex",
                  justifyContent: "space-between",
                }}
              >
                <span>极度恐惧</span>
                <span>极度贪婪</span>
              </div>
            </div>

            <SentimentHeatmap data={heatmapData} title="市场情绪热力图" />
          </div>

          {/* 第二行：情绪指标 + 趋势图 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <MetricsGrid
              title="情绪指标"
              metrics={coreMetrics}
              columns={3}
              displayNames={displayNames}
            />
            <ResistanceChart timeseries={normalizeTs(data.timeseries || [])} />
          </div>

          {/* 第三行：信号 + 舆情事件 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <SignalCard signals={data.signals || []} title="情绪信号" maxItems={5} />
            <EventTimeline events={normalizeEvents(data.events || [])} title="舆情事件时间线" />
          </div>
        </div>
      )}
    </div>
  );
}
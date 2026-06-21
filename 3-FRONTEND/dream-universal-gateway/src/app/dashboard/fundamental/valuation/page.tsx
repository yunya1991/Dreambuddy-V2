'use client';
import React, { useState, useEffect, useCallback } from "react";
import ResearchHeader from "../components/ResearchHeader";
import ResistanceChart from "../components/ResistanceChart";
import MetricsGrid from "../components/MetricsGrid";
import SignalCard from "../components/SignalCard";
import GaugeDisplay from "../components/GaugeDisplay";
import EventTimeline from "../components/EventTimeline";
import MVRVZoneChart from "../components/MVRVZoneChart";

const MODULE = "valuation";
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
}

const displayNames: Record<string, string> = {
  mvrv_ratio: "MVRV",
  mvrv_z_score: "Z-Score",
  sopr: "SOPR",
  ahr999_index: "AHR999",
  pi_cycle_top: "Pi周期顶",
  mayer_multiple: "Mayer倍数",
  puell_multiple: "Puell倍数",
  therm_index: "Therm热度",
  valuation_range: "估值区间",
  valuation_heat_level: "热度等级",
  nupl: "NUPL",
  realized_price: "已实现价格",
  market_price: "市价",
  price_distance_from_realized: "偏离已实现价格%",
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

function highlightForValuation(
  raw: string | number
): "up" | "down" | "neutral" {
  const s = String(raw).toLowerCase();
  if (s.includes("严重低估") || s.includes("低估") || s.includes("超卖")) return "down";
  if (s.includes("高估") || s.includes("过热") || s.includes("泡沫") || s.includes("偏高")) return "up";
  return "neutral";
}

export default function ValuationPage() {
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

  const zScoreRaw = toNum(flat.mvrv_z_score);
  const mvrvRatio = toNum(flat.mvrv_ratio);
  const nupl = toNum(flat.nupl);
  const realizedPrice = toNum(flat.realized_price);
  const marketPrice = toNum(flat.market_price || 65000);
  const priceDistance = toNum(flat.price_distance_from_realized || ((marketPrice - realizedPrice) / realizedPrice * 100));

  const nuplGauge = Math.max(0, Math.min(100, Math.round(nupl * 100)));
  const ahr999Gauge = Math.max(0, Math.min(100, Math.round(toNum(flat.ahr999_index) * 50)));

  const coreMetrics: Record<string, number | string> = {};
  const highlight: Record<string, "up" | "down" | "neutral"> = {};
  [
    "mvrv_ratio",
    "mvrv_z_score",
    "sopr",
    "ahr999_index",
    "pi_cycle_top",
    "mayer_multiple",
    "puell_multiple",
    "therm_index",
    "valuation_range",
    "valuation_heat_level",
    "nupl",
    "realized_price",
    "market_price",
    "price_distance_from_realized",
  ].forEach((k) => {
    if (flat[k] !== undefined) {
      coreMetrics[k] = flat[k];
      if (k === "valuation_range" || k === "valuation_heat_level") {
        highlight[k] = highlightForValuation(flat[k]);
      }
    }
  });

  return (
    <div className="flex flex-col h-full">
      <ResearchHeader
        module={MODULE}
        title="💰 估值研究"
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
          {/* 第一行：MVRV Z-Score 区间图 + NUPL + AHR999 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr 1fr",
              gap: 16,
            }}
          >
            <MVRVZoneChart zScore={zScoreRaw} mvrvRatio={mvrvRatio} title="MVRV Z-Score 区间" size={280} />
            <div
              style={{
                backgroundColor: "#1a1a1a",
                border: "1px solid #2a2a2a",
                borderRadius: 12,
                padding: 20,
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 12 }}>
                NUPL (未实现利润占比)
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: nuplGauge >= 70 ? "#22c55e" : nuplGauge >= 40 ? "#f59e0b" : "#ef4444" }}>
                {nupl.toFixed(2)}
              </div>
              <div style={{ fontSize: 12, color: "#8a8a8a", marginTop: 8 }}>
                {nuplGauge >= 70 ? "高利润区" : nuplGauge >= 40 ? "中等利润" : "低利润区"}
              </div>
            </div>
            <div
              style={{
                backgroundColor: "#1a1a1a",
                border: "1px solid #2a2a2a",
                borderRadius: 12,
                padding: 20,
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 12 }}>
                AHR999 挃数
              </div>
              <div style={{ fontSize: 36, fontWeight: 700, color: ahr999Gauge <= 30 ? "#22c55e" : ahr999Gauge <= 60 ? "#f59e0b" : "#ef4444" }}>
                {toNum(flat.ahr999_index).toFixed(2)}
              </div>
              <div style={{ fontSize: 12, color: "#8a8a8a", marginTop: 8 }}>
                {ahr999Gauge <= 30 ? "定投区间" : ahr999Gauge <= 60 ? "持有区间" : "高估区间"}
              </div>
            </div>
          </div>

          {/* 第二行：价格对比 */}
          <div
            style={{
              backgroundColor: "#1a1a1a",
              border: "1px solid #2a2a2a",
              borderRadius: 12,
              padding: 20,
            }}
          >
            <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0", marginBottom: 16 }}>
              已实现价格 vs 市价对比
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 4 }}>已实现价格</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: "#3b82f6" }}>
                  ${realizedPrice.toFixed(0)}
                </div>
              </div>
              <div style={{ fontSize: 32, color: priceDistance >= 0 ? "#22c55e" : "#ef4444" }}>
                {priceDistance >= 0 ? "↑" : "↓"}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 4 }}>当前市价</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: "#e0e0e0" }}>
                  ${marketPrice.toFixed(0)}
                </div>
              </div>
              <div style={{ flex: 1, textAlign: "right" }}>
                <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 4 }}>偏离度</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: priceDistance >= 50 ? "#ef4444" : priceDistance >= 20 ? "#f59e0b" : "#22c55e" }}>
                  {priceDistance.toFixed(1)}%
                </div>
              </div>
            </div>
          </div>

          {/* 第三行：核心指标 + 趋势图 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <MetricsGrid
              title="估值指标"
              metrics={coreMetrics}
              columns={3}
              displayNames={displayNames}
              highlight={Object.keys(highlight).length ? highlight : undefined}
            />
            <ResistanceChart timeseries={normalizeTs(data.timeseries || [])} />
          </div>

          {/* 第四行：信号 + 事件 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 16,
            }}
          >
            <SignalCard signals={data.signals || []} title="估值信号" maxItems={5} />
            <EventTimeline events={normalizeEvents(data.events || [])} title="估值事件时间线" />
          </div>
        </div>
      )}
    </div>
  );
}
'use client';
import React, { useState, useEffect, useCallback } from "react";
import ResearchHeader from "../components/ResearchHeader";
import ResistanceChart from "../components/ResistanceChart";
import MetricsGrid from "../components/MetricsGrid";
import SignalCard from "../components/SignalCard";
import GaugeDisplay from "../components/GaugeDisplay";
import EventTimeline from "../components/EventTimeline";
import NetFlowTrendChart from "../components/NetFlowTrendChart";
import WhaleTracker from "../components/WhaleTracker";

const MODULE = "flow";
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
    net_flow?: number;
    etf_flow?: number;
    exchange_flow?: number;
  }>;
  whale_transactions?: Array<{
    wallet_address?: string;
    wallet_label?: string;
    amount: number;
    direction: "in" | "out";
    timestamp?: string;
    exchange?: string;
    usd_value?: number;
  }>;
}

const displayNames: Record<string, string> = {
  fund_flow_score: "资金流得分",
  etf_net_flow: "ETF净流入(百万$)",
  funding_rate: "资金费率",
  long_short_ratio: "多空比",
  liquidation_pressure: "清算压力",
  whale_activity: "鲸鱼活动",
  stablecoin_supply_change: "稳定币变化",
  smart_money_direction: "聪明钱",
  flow_velocity_score: "流速得分",
  exchange_inflow: "交易所流入",
  exchange_outflow: "交易所流出",
};

const normalizeTs = (arr: any[]) =>
  arr?.map((p, i) => ({
    ts: p.ts || p.timestamp || new Date(Date.now() - (arr.length - i) * 3600000).toISOString(),
    direction_score: typeof p.direction_score === "number" ? p.direction_score : (p.value ?? 0),
    velocity: typeof p.velocity === "number" ? p.velocity : 0,
    acceleration: typeof p.acceleration === "number" ? p.acceleration : 0,
    net_flow: typeof p.net_flow === "number" ? p.net_flow : 0,
    etf_flow: typeof p.etf_flow === "number" ? p.etf_flow : undefined,
    exchange_flow: typeof p.exchange_flow === "number" ? p.exchange_flow : undefined,
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

export default function FlowPage() {
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

  const fundFlowScore = Math.round((toNum(flat.fund_flow_score) + 1) * 50);
  const whaleActivity =
    flat.whale_activity !== undefined
      ? Math.round(toNum(flat.whale_activity))
      : Math.round(toNum(flat.flow_velocity_score) * 100);
  const liquidationPressure = Math.round(toNum(flat.liquidation_pressure));
  const exchangeInflow = Math.round(toNum(flat.exchange_inflow || flat.etf_net_flow));
  const exchangeOutflow = Math.round(toNum(flat.exchange_outflow || -flat.etf_net_flow));

  const coreMetrics: Record<string, number | string> = {};
  [
    "fund_flow_score",
    "etf_net_flow",
    "funding_rate",
    "long_short_ratio",
    "liquidation_pressure",
    "whale_activity",
    "stablecoin_supply_change",
    "smart_money_direction",
    "flow_velocity_score",
    "exchange_inflow",
    "exchange_outflow",
  ].forEach((k) => {
    if (flat[k] !== undefined) coreMetrics[k] = flat[k];
  });

  const netFlowTs = normalizeTs(data?.timeseries || []).map((p) => ({
    ts: p.ts,
    net_flow: p.net_flow || p.direction_score * 100,
    etf_flow: p.etf_flow,
    exchange_flow: p.exchange_flow,
  }));

  const whaleTxs = data?.whale_transactions || [
    { wallet_label: "灰度信托", amount: 850, direction: "out", exchange: "Coinbase", usd_value: 55250000 },
    { wallet_label: "未知鲸鱼", amount: 1200, direction: "in", exchange: "Binance", usd_value: 78000000 },
    { wallet_label: "MicroStrategy", amount: 500, direction: "in", exchange: "链上", usd_value: 32500000 },
    { wallet_label: "交易所冷钱包", amount: 2000, direction: "out", exchange: "Kraken", usd_value: 130000000 },
  ];

  return (
    <div className="flex flex-col h-full">
      <ResearchHeader
        module={MODULE}
        title="💵 资金流研究"
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
          {/* 第一行：三个仪表盘 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr 1fr",
              gap: 16,
            }}
          >
            <GaugeDisplay value={fundFlowScore} title="综合资金压力" size={180} />
            <GaugeDisplay value={whaleActivity} title="鲸鱼活跃度" size={180} />
            <GaugeDisplay value={liquidationPressure} title="清算压力" size={180} />
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <div
                style={{
                  backgroundColor: "#1a1a1a",
                  border: "1px solid #2a2a2a",
                  borderRadius: 12,
                  padding: 16,
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 12, color: "#8a8a8a" }}>交易所流入</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: "#ef4444" }}>
                  {exchangeInflow}M
                </div>
              </div>
              <div
                style={{
                  backgroundColor: "#1a1a1a",
                  border: "1px solid #2a2a2a",
                  borderRadius: 12,
                  padding: 16,
                  textAlign: "center",
                }}
              >
                <div style={{ fontSize: 12, color: "#8a8a8a" }}>交易所流出</div>
                <div style={{ fontSize: 24, fontWeight: 700, color: "#22c55e" }}>
                  {exchangeOutflow}M
                </div>
              </div>
            </div>
          </div>

          {/* 第二行：净流入趋势图 + 鲸鱼追踪 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr",
              gap: 16,
            }}
          >
            <NetFlowTrendChart timeseries={netFlowTs} title="净流入趋势 (30天)" height={300} />
            <WhaleTracker transactions={whaleTxs} title="鲸鱼钱包追踪" maxItems={6} />
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
              title="核心指标"
              metrics={coreMetrics}
              columns={3}
              displayNames={displayNames}
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
            <SignalCard signals={data.signals || []} title="资金流信号" maxItems={5} />
            <EventTimeline events={normalizeEvents(data.events || [])} title="资金事件时间线" />
          </div>
        </div>
      )}
    </div>
  );
}
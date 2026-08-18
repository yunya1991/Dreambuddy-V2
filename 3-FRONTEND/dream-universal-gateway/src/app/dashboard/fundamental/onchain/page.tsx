'use client';
import React, { useState, useEffect, useCallback } from "react";
import ResearchHeader from "../components/ResearchHeader";
import ResistanceChart from "../components/ResistanceChart";
import MetricsGrid from "../components/MetricsGrid";
import SignalCard from "../components/SignalCard";
import GaugeDisplay from "../components/GaugeDisplay";
import EventTimeline from "../components/EventTimeline";
import UTXOAgeDistribution from "../components/UTXOAgeDistribution";

const MODULE = "onchain";
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
  utxo_age_distribution?: Array<{
    age_range: string;
    percentage: number;
    color?: string;
  }>;
}

const displayNames: Record<string, string> = {
  exchange_net_flow: "交易所净流入(百万$)",
  active_addresses: "活跃地址(万)",
  transaction_volume: "链上交易量(十亿$)",
  gas_price_gwei: "Gas价格",
  miner_position: "矿工行为",
  whale_position: "鲸鱼位置",
  stablecoin_supply: "稳定币总供给(十亿$)",
  whale_accumulation_score: "鲸鱼积累得分",
  exchange_supply_pressure: "供给压力",
  hodl_wave_strength: "HODL浪潮",
  miner_outflow: "矿工流出",
  exchange_reserve: "交易所储备",
  hash_rate: "算力",
  difficulty: "难度",
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

export default function OnchainPage() {
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

  const whaleAccum = Math.round(toNum(flat.whale_accumulation_score));
  const exchangePressure = Math.round(toNum(flat.exchange_supply_pressure));
  const minerOutflow = Math.round(toNum(flat.miner_outflow || flat.exchange_net_flow));
  const hashRate = Math.round(toNum(flat.hash_rate || 650));
  const exchangeReserve = toNum(flat.exchange_reserve || 2500);

  const coreMetrics: Record<string, number | string> = {};
  [
    "exchange_net_flow",
    "active_addresses",
    "transaction_volume",
    "gas_price_gwei",
    "miner_position",
    "whale_position",
    "stablecoin_supply",
    "whale_accumulation_score",
    "exchange_supply_pressure",
    "hodl_wave_strength",
    "miner_outflow",
    "exchange_reserve",
    "hash_rate",
    "difficulty",
  ].forEach((k) => {
    if (flat[k] !== undefined) coreMetrics[k] = flat[k];
  });

  const utxoBuckets = data?.utxo_age_distribution || [
    { age_range: "<1天", percentage: 5 + Math.random() * 3 },
    { age_range: "1-7天", percentage: 8 + Math.random() * 4 },
    { age_range: "7-30天", percentage: 12 + Math.random() * 5 },
    { age_range: "30-90天", percentage: 15 + Math.random() * 6 },
    { age_range: "90-365天", percentage: 18 + Math.random() * 7 },
    { age_range: "1-2年", percentage: 20 + Math.random() * 8 },
    { age_range: "2-3年", percentage: 12 + Math.random() * 5 },
    { age_range: "3-5年", percentage: 8 + Math.random() * 4 },
    { age_range: ">5年", percentage: 10 + Math.random() * 5 },
  ];

  return (
    <div className="flex flex-col h-full">
      <ResearchHeader
        module={MODULE}
        title="⛓️ 链上指标研究"
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
          {/* 第一行：鲸鱼积累 + 交易所供给 + 矿工流出 + 算力 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr 1fr",
              gap: 16,
            }}
          >
            <GaugeDisplay value={whaleAccum} title="鲸鱼积累得分" size={180} />
            <GaugeDisplay value={exchangePressure} title="交易所供给压力" size={180} />
            <div
              style={{
                backgroundColor: "#1a1a1a",
                border: "1px solid #2a2a2a",
                borderRadius: 12,
                padding: 20,
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 8 }}>
                矿工流出
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: minerOutflow > 0 ? "#ef4444" : "#22c55e" }}>
                {minerOutflow > 0 ? "+" : ""}{minerOutflow} BTC
              </div>
              <div style={{ fontSize: 11, color: "#8a8a8a", marginTop: 4 }}>
                {minerOutflow > 50 ? "抛压增加" : minerOutflow < -50 ? "积累增加" : "中性"}
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
              <div style={{ fontSize: 12, color: "#8a8a8a", marginBottom: 8 }}>
                网络算力
              </div>
              <div style={{ fontSize: 28, fontWeight: 700, color: "#3b82f6" }}>
                {hashRate} EH/s
              </div>
              <div style={{ fontSize: 11, color: "#8a8a8a", marginTop: 4 }}>
                {hashRate >= 600 ? "健康" : hashRate >= 500 ? "正常" : "偏低"}
              </div>
            </div>
          </div>

          {/* 第二行：UTXO年龄分布 + 交易所储备 */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 1fr",
              gap: 16,
            }}
          >
            <UTXOAgeDistribution buckets={utxoBuckets} title="UTXO年龄分布" />
            <div
              style={{
                backgroundColor: "#1a1a1a",
                border: "1px solid #2a2a2a",
                borderRadius: 12,
                padding: 20,
              }}
            >
              <div style={{ fontSize: 14, fontWeight: 600, color: "#e0e0e0", marginBottom: 16 }}>
                交易所储备趋势
              </div>
              <div style={{ textAlign: "center", marginBottom: 16 }}>
                <div style={{ fontSize: 32, fontWeight: 700, color: exchangeReserve >= 2500 ? "#f59e0b" : "#22c55e" }}>
                  {exchangeReserve.toFixed(0)}K BTC
                </div>
                <div style={{ fontSize: 12, color: "#8a8a8a", marginTop: 4 }}>
                  {exchangeReserve >= 2500 ? "储备充足，潜在抛压" : "储备下降，供给收紧"}
                </div>
              </div>
              <div
                style={{
                  backgroundColor: "#0d0d0d",
                  borderRadius: 8,
                  padding: 12,
                  fontSize: 11,
                  color: "#8a8a8a",
                }}
              >
                <div style={{ marginBottom: 8 }}>交易所储备下降通常表示：</div>
                <ul style={{ marginLeft: 16, lineHeight: 1.6 }}>
                  <li>用户将BTC转移到冷钱包</li>
                  <li>长期持有意愿增强</li>
                  <li>短期抛压减小</li>
                </ul>
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
              title="链上指标"
              metrics={coreMetrics}
              columns={2}
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
            <SignalCard signals={data.signals || []} title="链上信号" maxItems={5} />
            <EventTimeline events={normalizeEvents(data.events || [])} title="链上事件时间线" />
          </div>
        </div>
      )}
    </div>
  );
}
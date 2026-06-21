"use client";

import React, { useState, useEffect, useCallback } from "react";
import ResearchHeader from "../components/ResearchHeader";
import ResistanceChart from "../components/ResistanceChart";
import MetricsCard from "../components/MetricsCard";
import SignalPanel from "../components/SignalPanel";
import EventTimeline from "../components/EventTimeline";

interface ModuleSnapshot {
  module: string; ts: string;
  resistance_3d: { direction: "up" | "down" | "neutral"; direction_score: number; velocity: number; acceleration: number; confidence: number; data_points: number; trend_summary: string };
  signals: Array<{ id: string; type: "strong_buy" | "buy" | "hold" | "sell" | "strong_sell" | "reduce"; strength: number; confidence: number; reason: string; horizon: "short" | "medium" | "long"; factors: string[]; created_at: string }>;
  metrics: Record<string, number | string>;
  events: Array<{ id: string; timestamp: string; title: string; category: string; sentiment: number; impact_score: number; source: string }>;
  timeseries: Array<{ ts: string; direction_score: number; velocity: number; acceleration: number; sentiment: number; event_count: number }>;
  meta: { source: string[]; last_update: string; data_quality: "high" | "medium" | "low" };
}

const ENDPOINT = "/api/fundamental/narrative/snapshot";

export default function NarrativePage() {
  const [data, setData] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const res = await fetch(ENDPOINT, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const result: ModuleSnapshot = await res.json();
      setData(result); setLastUpdated(new Date().toLocaleString("zh-CN"));
    } catch (e: any) { setError(`无法连接后端服务`); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); const timer = setInterval(loadData, 120000); return () => clearInterval(timer); }, [loadData]);

  return (
    <div className="flex flex-col h-full">
      <ResearchHeader module="narrative" title="📚 叙事追踪" onRefresh={loadData} lastUpdated={lastUpdated} loading={loading} />
      {error && !data && <div className="m-6 p-4 rounded-md" style={{ backgroundColor: "#2a1a1a", border: "1px solid rgba(239,68,68,0.3)", color: "#fca5a5" }}>⚠️ {error}</div>}
      {loading && !data && <div className="flex items-center justify-center flex-1"><div className="text-[#6b7280] text-sm">加载中...</div></div>}
      {data && (
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "2fr 1fr" }}>
            <ResistanceChart timeseries={data.timeseries || []} />
            <MetricsCard metrics={{ ...data.resistance_3d, confidence: data.resistance_3d.confidence }} title="核心指标" />
          </div>
          <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "1fr 1fr" }}>
            <SignalPanel signals={data.signals || []} title="交易信号" />
            <MetricsCard metrics={data.metrics || {}} title="叙事指标" />
          </div>
          <EventTimeline events={data.events || []} title="事件时间线" />
        </div>
      )}
    </div>
  );
}

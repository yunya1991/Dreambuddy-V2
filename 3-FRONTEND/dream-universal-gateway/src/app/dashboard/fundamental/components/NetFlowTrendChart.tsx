"use client";

import React from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Area,
  ComposedChart,
} from "recharts";

interface NetFlowPoint {
  ts: string;
  net_flow: number;
  etf_flow?: number;
  exchange_flow?: number;
}

interface NetFlowTrendChartProps {
  timeseries: NetFlowPoint[];
  title?: string;
  height?: number;
}

function formatDate(ts: string): string {
  const d = new Date(ts);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function formatValue(v: number): string {
  if (Math.abs(v) >= 1000) {
    return `${(v / 1000).toFixed(1)}B`;
  }
  return `${v.toFixed(0)}M`;
}

export default function NetFlowTrendChart({
  timeseries,
  title = "净流入趋势",
  height = 280,
}: NetFlowTrendChartProps) {
  if (!timeseries || timeseries.length === 0) {
    return (
      <div
        style={{
          backgroundColor: "#1a1a1a",
          border: "1px solid #2a2a2a",
          borderRadius: 12,
          padding: 20,
          color: "#8a8a8a",
        }}
      >
        {title}：暂无数据
      </div>
    );
  }

  const data = timeseries.map((p, i) => ({
    date: formatDate(p.ts) || `D${i + 1}`,
    netFlow: typeof p.net_flow === "number" ? p.net_flow : 0,
    etfFlow: typeof p.etf_flow === "number" ? p.etf_flow : undefined,
    exchangeFlow: typeof p.exchange_flow === "number" ? p.exchange_flow : undefined,
    rawTs: p.ts,
  }));

  const maxVal = Math.max(...data.map((d) => Math.abs(d.netFlow)));
  const avgFlow = data.reduce((sum, d) => sum + d.netFlow, 0) / data.length;

  return (
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
          marginBottom: 16,
        }}
      >
        {title}
        <span
          style={{
            fontSize: 12,
            color: avgFlow >= 0 ? "#22c55e" : "#ef4444",
            marginLeft: 12,
          }}
        >
          平均净流入: {formatValue(avgFlow)}
        </span>
      </div>

      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
          <XAxis
            dataKey="date"
            stroke="#6b7280"
            fontSize={11}
            tickLine={false}
          />
          <YAxis
            stroke="#6b7280"
            fontSize={11}
            tickFormatter={(v) => formatValue(v)}
            domain={[-maxVal * 1.2, maxVal * 1.2]}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#0d0d0d",
              border: "1px solid #2a2a2a",
              borderRadius: 8,
              color: "#e0e0e0",
            }}
            formatter={(value: number) => [formatValue(value), "净流入"]}
            labelFormatter={(label) => `日期: ${label}`}
          />
          <ReferenceLine y={0} stroke="#4a4a4a" strokeWidth={1} />
          <Area
            type="monotone"
            dataKey="netFlow"
            fill="url(#netFlowGradient)"
            stroke="#3b82f6"
            strokeWidth={2}
          />
          <defs>
            <linearGradient id="netFlowGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.05} />
            </linearGradient>
          </defs>
        </ComposedChart>
      </ResponsiveContainer>

      {data[0]?.etfFlow !== undefined && (
        <div
          style={{
            marginTop: 12,
            fontSize: 12,
            color: "#8a8a8a",
            display: "flex",
            gap: 16,
          }}
        >
          <span>ETF流入: {formatValue(data[data.length - 1]?.etfFlow || 0)}</span>
          <span>交易所: {formatValue(data[data.length - 1]?.exchangeFlow || 0)}</span>
        </div>
      )}
    </div>
  );
}
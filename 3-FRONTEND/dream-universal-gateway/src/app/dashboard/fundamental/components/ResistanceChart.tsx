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
  Legend,
} from "recharts";

interface TimeseriesPoint {
  ts: string;
  direction_score: number;
  velocity: number;
  acceleration: number;
  sentiment?: number;
  event_count?: number;
}

interface ResistanceChartProps {
  timeseries: TimeseriesPoint[];
}

const formatTime = (ts: string) => {
  const date = new Date(ts);
  return `${date.getMonth() + 1}/${date.getDate()}`;
};

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ color: string; name: string; value: number }>;
  label?: string;
}) => {
  if (active && payload && payload.length) {
    const date = label ? new Date(label) : null;
    return (
      <div
        className="rounded-lg p-3 border"
        style={{
          backgroundColor: "#1a1a1a",
          borderColor: "#2a2a2a",
        }}
      >
        <p className="text-xs text-[#8a8a8a] mb-2">
          {date?.toLocaleString("zh-CN")}
        </p>
        {payload.map((entry, index) => (
          <p key={index} className="text-xs" style={{ color: entry.color }}>
            {entry.name}: {entry.value?.toFixed(3)}
          </p>
        ))}
      </div>
    );
  }
  return null;
};

export default function ResistanceChart({ timeseries }: ResistanceChartProps) {
  if (!timeseries || timeseries.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full rounded-lg"
        style={{ backgroundColor: "#1a1a1a", minHeight: 300 }}
      >
        <p className="text-[#6b7280] text-sm">暂无数据</p>
      </div>
    );
  }

  const data = timeseries.map((point) => ({
    ...point,
    ts: point.ts,
  }));

  return (
    <div
      className="rounded-lg p-4"
      style={{ backgroundColor: "#1a1a1a", border: "1px solid #2a2a2a" }}
    >
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
          <XAxis
            dataKey="ts"
            tickFormatter={formatTime}
            stroke="#6b7280"
            fontSize={10}
            tickLine={false}
          />
          <YAxis
            domain={[-1, 1]}
            stroke="#6b7280"
            fontSize={10}
            tickLine={false}
            ticks={[-1, -0.5, 0, 0.5, 1]}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "#8a8a8a" }}
            formatter={(value) => <span style={{ color: "#e0e0e0" }}>{value}</span>}
          />
          <Line
            type="monotone"
            dataKey="direction_score"
            name="Direction"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "#3b82f6" }}
          />
          <Line
            type="monotone"
            dataKey="velocity"
            name="Velocity"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "#22c55e" }}
          />
          <Line
            type="monotone"
            dataKey="acceleration"
            name="Acceleration"
            stroke="#f97316"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: "#f97316" }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

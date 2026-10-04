'use client';

import React from 'react';
import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer,
} from 'recharts';

interface RadarDimensionsProps {
  dimensions: Record<string, { score: number; label: string }>;
  height?: number;
}

const dimLabelMap: Record<string, string> = {
  macro: '宏观',
  onchain: '链上',
  technical: '技术面',
  sentiment: '情绪',
  fundamental: '基本面',
  timing: '时机',
  risk: '风险',
};

/**
 * 七维评分雷达图 — 使用 recharts Radar
 * 展示战略层各维度评分
 */
export function RadarDimensions({ dimensions, height = 280 }: RadarDimensionsProps) {
  const data = Object.entries(dimensions).map(([key, val]) => ({
    dimension: dimLabelMap[key] || key,
    score: val.score || 0,
    fullMark: 100,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="70%">
        <PolarGrid stroke="#334155" />
        <PolarAngleAxis
          dataKey="dimension"
          tick={{ fill: '#94a3b8', fontSize: 11 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fill: '#64748b', fontSize: 9 }}
          stroke="#475569"
        />
        <Radar
          name="评分"
          dataKey="score"
          stroke="#3b82f6"
          fill="#3b82f6"
          fillOpacity={0.3}
          strokeWidth={2}
        />
      </RadarChart>
    </ResponsiveContainer>
  );
}

export default RadarDimensions;

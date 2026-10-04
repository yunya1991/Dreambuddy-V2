'use client';

import React from 'react';

interface ConfidenceGaugeProps {
  value: number; // 0-100
  label?: string;
  size?: number;
  direction?: 'bullish' | 'bearish' | 'neutral';
}

/**
 * 置信度仪表盘 — 半圆 SVG 仪表盘
 * 参考金融终端风格，颜色随置信度渐变
 */
export function ConfidenceGauge({ value, label, size = 160, direction = 'neutral' }: ConfidenceGaugeProps) {
  const clampedValue = Math.max(0, Math.min(100, value));
  const radius = (size - 20) / 2;
  const strokeWidth = 14;
  const centerX = size / 2;
  const centerY = size / 2 + 10;

  // 半圆路径
  const circumference = Math.PI * radius;
  const offset = circumference - (clampedValue / 100) * circumference;

  // 颜色根据方向和置信度
  const getColor = () => {
    if (direction === 'bullish') return clampedValue > 60 ? '#10b981' : '#34d399';
    if (direction === 'bearish') return clampedValue > 60 ? '#ef4444' : '#f87171';
    return clampedValue > 60 ? '#3b82f6' : '#60a5fa';
  };

  const color = getColor();

  // 指针角度（-90 到 90 度）
  const angle = (clampedValue / 100) * 180 - 90;
  const pointerLength = radius - strokeWidth - 5;
  const pointerX = centerX + pointerLength * Math.cos((angle * Math.PI) / 180);
  const pointerY = centerY + pointerLength * Math.sin((angle * Math.PI) / 180);

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size / 2 + 45} viewBox={`0 0 ${size} ${size / 2 + 45}`}>
        {/* 背景弧 */}
        <path
          d={`M ${centerX - radius} ${centerY} A ${radius} ${radius} 0 0 1 ${centerX + radius} ${centerY}`}
          fill="none"
          stroke="#1e293b"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
        />
        {/* 进度弧 */}
        <path
          d={`M ${centerX - radius} ${centerY} A ${radius} ${radius} 0 0 1 ${centerX + radius} ${centerY}`}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
        {/* 指针 */}
        <line
          x1={centerX}
          y1={centerY}
          x2={pointerX}
          y2={pointerY}
          stroke={color}
          strokeWidth="3"
          strokeLinecap="round"
          style={{ transition: 'all 0.6s ease' }}
        />
        <circle cx={centerX} cy={centerY} r="5" fill={color} />
        {/* 数值 */}
        <text
          x={centerX}
          y={centerY + 25}
          textAnchor="middle"
          fill="#e2e8f0"
          fontSize="20"
          fontWeight="bold"
        >
          {clampedValue.toFixed(0)}%
        </text>
      </svg>
      {label && (
        <span className="text-xs text-slate-400 mt-1">{label}</span>
      )}
    </div>
  );
}

export default ConfidenceGauge;

'use client';

// ============================================
// SynthesisChart — 渲染 subagent 产出的图表
// 后端 ChartSpec 格式: { type, title, data, config }
// 支持类型: gauge / line / bar / sankey / heatmap / candlestick / scatter / pie
// ============================================

import React from 'react';
import {
  LineChart, Line, BarChart, Bar,
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  RadialBarChart, RadialBar, Cell,
  CartesianGrid, ScatterChart, Scatter, PieChart, Pie,
} from 'recharts';

export interface ChartSpec {
  type: string;
  title: string;
  data: Record<string, unknown> | number | unknown[];
  config?: Record<string, unknown>;
}

interface SynthesisChartProps {
  chart: ChartSpec;
}

const COLORS = ['#a78bfa', '#60a5fa', '#34d399', '#fbbf24', '#f87171'];

function buildSeriesData(data: Record<string, unknown>): { name: string; value: number }[] {
  return Object.entries(data)
    .filter(([, v]) => typeof v === 'number' && !isNaN(v as number))
    .map(([k, v]) => ({ name: k, value: v as number }));
}

export function SynthesisChart({ chart }: SynthesisChartProps) {
  const { type, title, data } = chart;

  if (data === null || data === undefined) {
    return (
      <div className="text-xs text-gray-500 italic p-2">
        {title}: 无数据
      </div>
    );
  }

  switch (type) {
    case 'gauge':
      return <GaugeChart title={title} data={data} />;
    case 'line':
      return <LineChartView title={title} data={data} />;
    case 'bar':
      return <BarChartView title={title} data={data} />;
    case 'sankey':
      return <SankeyChart title={title} data={data} />;
    case 'heatmap':
      return <HeatmapChart title={title} data={data} />;
    case 'candlestick':
      return <CandlestickChart title={title} data={data} />;
    case 'scatter':
      return <ScatterChartView title={title} data={data} />;
    case 'pie':
      return <PieChartView title={title} data={data} />;
    default:
      return <TextFallback title={title} data={data} />;
  }
}

// ── Gauge ──────────────────────────────────
function GaugeChart({ title, data }: { title: string; data: unknown }) {
  const value = typeof data === 'number' ? data : Number(data);
  const pct = Math.max(0, Math.min(100, isNaN(value) ? 0 : value));
  const gaugeData = [{ name: title, value: pct, fill: COLORS[0] }];
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 120 }}>
        <ResponsiveContainer width="100%" height="100%">
          <RadialBarChart innerRadius="60%" outerRadius="100%" data={gaugeData} startAngle={90} endAngle={-270}>
            <RadialBar background={{ fill: '#374151' }} dataKey="value" cornerRadius={6} />
          </RadialBarChart>
        </ResponsiveContainer>
      </div>
      <div className="text-center text-xs text-gray-300 -mt-8">
        {typeof data === 'number' ? data.toFixed(1) : String(value)}
      </div>
    </div>
  );
}

// ── Line ───────────────────────────────────
function LineChartView({ title, data }: { title: string; data: unknown }) {
  if (typeof data !== 'object' || Array.isArray(data) || data === null) {
    return <TextFallback title={title} data={data} />;
  }
  const series = buildSeriesData(data as Record<string, unknown>);
  if (series.length === 0) return <TextFallback title={title} data={data} />;
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.4} />
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }} />
            <Line type="monotone" dataKey="value" stroke={COLORS[0]} strokeWidth={2} dot={{ r: 3, fill: COLORS[0] }} activeDot={{ r: 5 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Bar ────────────────────────────────────
function BarChartView({ title, data }: { title: string; data: unknown }) {
  const series = (() => {
    if (Array.isArray(data)) {
      // 数组格式: [{name, value}] 或 [name, value]
      return data
        .map((d: unknown) => {
          if (typeof d === 'object' && d !== null) {
            const o = d as Record<string, unknown>;
            return { name: String(o.name ?? o.key ?? ''), value: Number(o.value ?? o.val ?? 0) };
          }
          if (Array.isArray(d)) {
            return { name: String(d[0] ?? ''), value: Number(d[1] ?? 0) };
          }
          return null;
        })
        .filter((d): d is { name: string; value: number } => d !== null && !isNaN(d.value));
    }
    if (typeof data === 'object' && data !== null) {
      return buildSeriesData(data as Record<string, unknown>);
    }
    return [];
  })();
  if (series.length === 0) return <TextFallback title={title} data={data} />;
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <div style={{ width: '100%', height: 160 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={series} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" opacity={0.4} />
            <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <YAxis tick={{ fill: '#9ca3af', fontSize: 10 }} />
            <Tooltip contentStyle={{ background: '#1f2937', border: '1px solid #374151', borderRadius: 6, fontSize: 11 }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {series.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ── Sankey (纯 SVG 实现) ────────────────────
interface SankeyNode { name: string }
interface SankeyLink { source: string; target: string; value: number }

function SankeyChart({ title, data }: { title: string; data: unknown }) {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) {
    return <TextFallback title={title} data={data} />;
  }
  const nodes = (data as Record<string, unknown>).nodes as SankeyNode[] | undefined;
  const links = (data as Record<string, unknown>).links as SankeyLink[] | undefined;
  if (!nodes || !links || nodes.length === 0) {
    return <TextFallback title={title} data={data} />;
  }

  const width = 360;
  const height = 180;
  const nodeWidth = 16;
  const nodeGap = 12;

  // 计算节点层级 (左侧: 只有出度的节点; 右侧: 只有入度的节点; 中间: 两者都有)
  const sourceSet = new Set(links.map(l => l.source));
  const targetSet = new Set(links.map(l => l.target));

  const leftNodes = nodes.filter(n => sourceSet.has(n.name) && !targetSet.has(n.name));
  const rightNodes = nodes.filter(n => targetSet.has(n.name) && !sourceSet.has(n.name));
  const middleNodes = nodes.filter(n => sourceSet.has(n.name) && targetSet.has(n.name));

  const layers = [leftNodes, middleNodes, rightNodes].filter(l => l.length > 0);
  const layerCount = layers.length;

  // 计算每个节点的总流量 (决定高度)
  const nodeFlow = new Map<string, number>();
  for (const n of nodes) nodeFlow.set(n.name, 0);
  for (const l of links) {
    nodeFlow.set(l.source, (nodeFlow.get(l.source) || 0) + l.value);
    nodeFlow.set(l.target, (nodeFlow.get(l.target) || 0) + l.value);
  }
  const maxFlow = Math.max(...Array.from(nodeFlow.values()), 1);

  // 布局节点
  const nodePositions = new Map<string, { x: number; y: number; h: number }>();
  const layerGap = layerCount > 1 ? (width - nodeWidth) / (layerCount - 1) : 0;

  layers.forEach((layer, li) => {
    const totalH = layer.reduce((s, n) => s + Math.max(8, (nodeFlow.get(n.name) || 0) / maxFlow * 100), 0);
    const totalGap = (layer.length - 1) * nodeGap;
    const startY = (height - totalH - totalGap) / 2;
    let y = Math.max(10, startY);
    const x = layerCount > 1 ? li * layerGap : (width - nodeWidth) / 2;
    for (const n of layer) {
      const h = Math.max(8, (nodeFlow.get(n.name) || 0) / maxFlow * 100);
      nodePositions.set(n.name, { x, y, h });
      y += h + nodeGap;
    }
  });

  // 生成 links 路径
  const linkPaths = links.map((l, i) => {
    const s = nodePositions.get(l.source);
    const t = nodePositions.get(l.target);
    if (!s || !t) return null;
    const sx = s.x + nodeWidth;
    const sy = s.y + s.h / 2;
    const tx = t.x;
    const ty = t.y + t.h / 2;
    const cx = (sx + tx) / 2;
    const path = `M${sx},${sy} C${cx},${sy} ${cx},${ty} ${tx},${ty}`;
    const opacity = Math.max(0.15, Math.min(0.8, l.value / maxFlow));
    return { path, color: COLORS[i % COLORS.length], opacity, value: l.value, source: l.source, target: l.target };
  }).filter(Boolean) as { path: string; color: string; opacity: number; value: number; source: string; target: string }[];

  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ maxHeight: 200 }}>
        {/* links */}
        {linkPaths.map((lp, i) => (
          <path
            key={i}
            d={lp.path}
            fill="none"
            stroke={lp.color}
            strokeWidth={Math.max(2, lp.value / maxFlow * 20)}
            strokeOpacity={lp.opacity}
          >
            <title>{`${lp.source} → ${lp.target}: ${lp.value}`}</title>
          </path>
        ))}
        {/* nodes */}
        {Array.from(nodePositions.entries()).map(([name, pos]) => (
          <g key={name}>
            <rect
              x={pos.x}
              y={pos.y}
              width={nodeWidth}
              height={pos.h}
              fill={COLORS[nodes.findIndex(n => n.name === name) % COLORS.length]}
              rx={3}
            />
            <text
              x={pos.x < width / 2 ? pos.x + nodeWidth + 4 : pos.x - 4}
              y={pos.y + pos.h / 2}
              textAnchor={pos.x < width / 2 ? 'start' : 'end'}
              dominantBaseline="middle"
              fill="#9ca3af"
              fontSize={10}
            >
              {name}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── Heatmap (纯 SVG/CSS 网格) ──────────────
function HeatmapChart({ title, data }: { title: string; data: unknown }) {
  if (!Array.isArray(data)) {
    return <TextFallback title={title} data={data} />;
  }
  // 格式: [[row, col, value], ...]
  const cells = data
    .map((d: unknown) => {
      if (Array.isArray(d) && d.length >= 3) {
        return { row: String(d[0]), col: String(d[1]), value: Number(d[2]) };
      }
      return null;
    })
    .filter((c): c is { row: string; col: string; value: number } => c !== null && !isNaN(c.value));

  if (cells.length === 0) return <TextFallback title={title} data={data} />;

  const rows = Array.from(new Set(cells.map(c => c.row)));
  const cols = Array.from(new Set(cells.map(c => c.col)));
  const maxVal = Math.max(...cells.map(c => Math.abs(c.value)), 1);

  // 颜色映射: 负值→红, 正值→绿, 0→灰
  const colorFor = (v: number) => {
    if (v === 0) return '#374151';
    const ratio = Math.min(1, Math.abs(v) / maxVal);
    if (v > 0) {
      // 绿色渐变
      const r = Math.round(52 + (34 - 52) * (1 - ratio));
      const g = Math.round(211 + (197 - 211) * (1 - ratio));
      const b = Math.round(153 + (94 - 153) * (1 - ratio));
      return `rgb(${r},${g},${b})`;
    }
    // 红色渐变
    const r = Math.round(248 + (239 - 248) * (1 - ratio));
    const g = Math.round(113 + (68 - 113) * (1 - ratio));
    const b = Math.round(113 + (68 - 113) * (1 - ratio));
    return `rgb(${r},${g},${b})`;
  };

  const cellW = 70;
  const cellH = 28;

  return (
    <div className="my-2 overflow-x-auto">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <table className="border-collapse" style={{ minWidth: '100%' }}>
        <thead>
          <tr>
            <th style={{ width: 70, padding: '2px 4px' }} className="text-[10px] text-gray-500 text-left" />
            {cols.map(c => (
              <th key={c} style={{ width: cellW, padding: '2px 4px' }} className="text-[10px] text-gray-400 text-center">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={r}>
              <td style={{ padding: '2px 4px' }} className="text-[10px] text-gray-400 whitespace-nowrap">
                {r}
              </td>
              {cols.map(c => {
                const cell = cells.find(cc => cc.row === r && cc.col === c);
                const v = cell?.value ?? 0;
                return (
                  <td key={c} style={{ padding: '2px 4px' }}>
                    <div
                      className="rounded text-center text-[10px] font-medium"
                      style={{
                        width: cellW - 8,
                        height: cellH,
                        lineHeight: `${cellH}px`,
                        backgroundColor: colorFor(v),
                        color: Math.abs(v) / maxVal > 0.5 ? '#fff' : '#d1d5db',
                      }}
                      title={`${r} / ${c}: ${v}`}
                    >
                      {v}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Candlestick (OHLC) ─────────────────────
function CandlestickChart({ title, data }: { title: string; data: unknown }) {
  // data: array of { time, open, high, low, close } or { o, h, l, c }
  const arr = Array.isArray(data) ? data : [];
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无 OHLC 数据</div>;
  }
  const rows = arr.map((item: any, i: number) => {
    const t = item.time || item.t || item.date || `#${i + 1}`;
    const o = item.open ?? item.o;
    const h = item.high ?? item.h;
    const l = item.low ?? item.l;
    const c = item.close ?? item.c;
    const up = c >= o;
    return (
      <tr key={i} className="border-b border-gray-700/40">
        <td className="py-0.5 pr-2 text-[10px] text-gray-400">{String(t)}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{o?.toFixed?.(2) ?? o}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{h?.toFixed?.(2) ?? h}</td>
        <td className="py-0.5 pr-2 text-[10px] text-gray-300">{l?.toFixed?.(2) ?? l}</td>
        <td className={`py-0.5 text-[10px] font-medium ${up ? 'text-emerald-400' : 'text-red-400'}`}>{c?.toFixed?.(2) ?? c}</td>
      </tr>
    );
  });
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <table className="w-full text-left">
        <thead>
          <tr className="text-[10px] text-gray-500 border-b border-gray-700/60">
            <th className="py-0.5 pr-2">时间</th>
            <th className="py-0.5 pr-2">开</th>
            <th className="py-0.5 pr-2">高</th>
            <th className="py-0.5 pr-2">低</th>
            <th className="py-0.5">收</th>
          </tr>
        </thead>
        <tbody>{rows.slice(0, 20)}</tbody>
      </table>
    </div>
  );
}

// ── Scatter ────────────────────────────────
function ScatterChartView({ title, data }: { title: string; data: unknown }) {
  // data: array of { x, y } or { name, value }
  const arr = Array.isArray(data) ? data : buildSeriesData(data as Record<string, unknown>).map(d => ({ x: d.name, y: d.value }));
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无散点数据</div>;
  }
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <ResponsiveContainer width="100%" height={180}>
        <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
          <XAxis dataKey="x" tick={{ fontSize: 10, fill: '#9ca3af' }} />
          <YAxis dataKey="y" tick={{ fontSize: 10, fill: '#9ca3af' }} />
          <Tooltip />
          <Scatter data={arr} fill={COLORS[0]} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Pie ────────────────────────────────────
function PieChartView({ title, data }: { title: string; data: unknown }) {
  const arr = Array.isArray(data) ? data : buildSeriesData(data as Record<string, unknown>);
  if (arr.length === 0) {
    return <div className="text-xs text-gray-500 italic p-2">{title}: 无饼图数据</div>;
  }
  return (
    <div className="my-2">
      <div className="text-[11px] text-gray-400 mb-1">{title}</div>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={arr}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            outerRadius={70}
            label={(entry: any) => `${entry.name}`}
            labelLine={false}
          >
            {arr.map((_: any, i: number) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

// ── Text Fallback ──────────────────────────
function TextFallback({ title, data }: { title: string; data: unknown }) {
  let text = '';
  if (typeof data === 'object' && data !== null) {
    text = Object.entries(data as Record<string, unknown>)
      .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : String(v)}`)
      .join(' | ');
  } else {
    text = String(data);
  }
  return (
    <div className="text-xs text-gray-400 p-2 bg-gray-800/30 rounded">
      <span className="text-gray-500">{title}: </span>{text}
    </div>
  );
}

export default SynthesisChart;

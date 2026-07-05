'use client';

import { V3Card, V3StatusDot, V3Empty } from '@/components';
import { useChainStore } from '@/stores';

const layerColors: Record<string, string> = {
  S: '#a855f7', A: '#3b82f6', C: '#22c55e', G: '#f59e0b',
};

export function DAGGraphView() {
  const { dagNodes, dagEdges } = useChainStore();

  if (dagNodes.length === 0) {
    return (
      <V3Card>
        <V3Empty icon={<svg className="w-8 h-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 6h16M4 12h16M4 18h16" /></svg>} title="暂无 DAG 数据" description="等待 Chain 启动后显示执行图" />
      </V3Card>
    );
  }

  // Position nodes in a simple grid
  const positioned = dagNodes.map((node, i) => ({
    ...node,
    x: (i % 4) * 180 + 100,
    y: Math.floor(i / 4) * 120 + 60,
  }));

  return (
    <V3Card title="DAG 执行图">
      <svg viewBox="0 0 720 400" className="w-full h-auto">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
          </marker>
        </defs>
        {dagEdges.map((edge, i) => {
          const from = positioned.find(n => n.id === edge.from);
          const to = positioned.find(n => n.id === edge.to);
          if (!from || !to) return null;
          const midX = (from.x + to.x) / 2;
          return (
            <path key={i} d={`M ${from.x} ${from.y} C ${midX} ${from.y}, ${midX} ${to.y}, ${to.x} ${to.y}`}
              fill="none" stroke="#334155" strokeWidth="2" markerEnd="url(#arrow)" />
          );
        })}
        {positioned.map(node => (
          <g key={node.id}>
            <rect x={node.x - 50} y={node.y - 20} width={100} height={40} rx={8}
              fill={node.status === 'active' ? `${layerColors[node.layer]}20` : '#1e293b'}
              stroke={layerColors[node.layer]} strokeWidth={node.status === 'active' ? 2 : 1}
              className={node.status === 'active' ? 'animate-pulse' : ''} />
            <circle cx={node.x - 30} cy={node.y} r={4} fill={layerColors[node.layer]} />
            <text x={node.x + 4} y={node.y + 4} fill="#e2e8f0" fontSize="11" textAnchor="middle">{node.label}</text>
          </g>
        ))}
      </svg>
      <div className="flex items-center gap-4 mt-3 justify-center">
        {Object.entries(layerColors).map(([layer, color]) => (
          <div key={layer} className="flex items-center gap-1.5">
            <span className="w-3 h-3 rounded-full" style={{ backgroundColor: color }} />
            <span className="text-[10px] text-slate-500">{layer === 'S' ? '感知' : layer === 'A' ? '编排' : layer === 'C' ? '执行' : '存储'}</span>
          </div>
        ))}
      </div>
    </V3Card>
  );
}

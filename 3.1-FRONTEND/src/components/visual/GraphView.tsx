'use client';

// T3 共振网络渲染：确定性环形布局（无重型力导向依赖），边粗细/透明度 = |ρ|
// D-E18 资金流边（kind=flow）：箭头指向流入方，tooltip 读 meta.flows（LT-G7 不伪造边）

interface GraphNode {
  id: string;
  label: string;
  group?: string | null;
}

interface GraphEdge {
  src: string;
  dst: string;
  kind: string;
  weight: number | null;
  p_adj: number | null;
}

interface FlowMeta {
  edge_index: number;
  flow_z?: number | null;
  flow_usdt?: number | null;
  window?: number | null;
  direction?: string | null;
}

interface GraphMeta {
  flows?: FlowMeta[];
  reason?: string;
  [key: string]: unknown;
}

const WIDTH = 460;
const HEIGHT = 320;
const FLOW_COLOR = '#34d399';
const CORR_COLOR = '#60a5fa';

function edgeTitle(
  edge: GraphEdge,
  flow: FlowMeta | undefined,
  labelOf: (id: string) => string,
): string {
  const src = labelOf(edge.src);
  const dst = labelOf(edge.dst);
  if (edge.kind !== 'flow') {
    return `${edge.src}–${edge.dst} ρ=${edge.weight ?? '—'} q=${edge.p_adj ?? '—'}`;
  }
  const parts = [`${src} → ${dst}`, `flow_z=${flow?.flow_z ?? '—'}`];
  if (flow?.window) parts.push(`${flow.window}日窗口`);
  if (typeof flow?.flow_usdt === 'number' && flow.flow_usdt !== 0) {
    parts.push(`净流入 ${flow.flow_usdt} 百万美元`);
  }
  return parts.join(' · ');
}

export function GraphView({
  nodes,
  edges,
  meta,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  meta?: GraphMeta;
}) {
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  const radius = Math.min(WIDTH, HEIGHT) / 2 - 56;
  const step = (Math.PI * 2) / Math.max(nodes.length, 1);

  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + index * step;
    positions.set(node.id, {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    });
  });

  const labelOf = (id: string) => nodes.find(node => node.id === id)?.label ?? id;
  const flows = meta?.flows ?? [];
  const hasFlow = edges.some(edge => edge.kind === 'flow');

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/30">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto">
        <defs>
          <marker
            id="flow-arrow"
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={6}
            markerHeight={6}
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill={FLOW_COLOR} />
          </marker>
        </defs>
        {edges.map((edge, index) => {
          const src = positions.get(edge.src);
          const dst = positions.get(edge.dst);
          if (!src || !dst) return null;
          const weight = Math.abs(edge.weight ?? 0);
          const isFlow = edge.kind === 'flow';
          const dx = dst.x - src.x;
          const dy = dst.y - src.y;
          const length = Math.hypot(dx, dy) || 1;
          // 箭头收在节点外沿，避免被圆心圆点盖住
          const inset = isFlow ? 9 : 0;
          return (
            <line
              key={`${edge.src}-${edge.dst}-${index}`}
              x1={src.x}
              y1={src.y}
              x2={dst.x - (dx / length) * inset}
              y2={dst.y - (dy / length) * inset}
              stroke={isFlow ? FLOW_COLOR : CORR_COLOR}
              strokeWidth={0.6 + weight * 2.6}
              strokeOpacity={0.15 + weight * 0.6}
              markerEnd={isFlow ? 'url(#flow-arrow)' : undefined}
            >
              <title>{edgeTitle(edge, flows.find(flow => flow.edge_index === index), labelOf)}</title>
            </line>
          );
        })}
        {nodes.map(node => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          return (
            <g key={node.id}>
              <circle cx={pos.x} cy={pos.y} r={5} fill="#a78bfa" fillOpacity={0.85} />
              <text
                x={pos.x}
                y={pos.y - 9}
                textAnchor="middle"
                className="fill-slate-300"
                style={{ fontSize: 10 }}
              >
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>
      <p className="px-3 pb-2 text-[10px] text-slate-500">
        {hasFlow
          ? '节点=资产 · 绿箭头=资金流（指向流入方）· 线宽=|flow_z|/3 · 蓝线=同期相关'
          : `节点=资产 · 边=同期相关 · 线宽与透明度=|ρ|${
              meta?.reason ? ` · 降级：${meta.reason}` : ''
            }`}
      </p>
    </div>
  );
}

export default GraphView;


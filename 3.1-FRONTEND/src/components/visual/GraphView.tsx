'use client';

// T3 共振网络渲染：确定性环形布局（无重型力导向依赖），边粗细/透明度 = |ρ|

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

const WIDTH = 460;
const HEIGHT = 320;

export function GraphView({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
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

  return (
    <div className="rounded-lg border border-slate-800/60 bg-slate-900/30">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto">
        {edges.map((edge, index) => {
          const src = positions.get(edge.src);
          const dst = positions.get(edge.dst);
          if (!src || !dst) return null;
          const weight = Math.abs(edge.weight ?? 0);
          return (
            <line
              key={`${edge.src}-${edge.dst}-${index}`}
              x1={src.x}
              y1={src.y}
              x2={dst.x}
              y2={dst.y}
              stroke="#60a5fa"
              strokeWidth={0.6 + weight * 2.6}
              strokeOpacity={0.15 + weight * 0.6}
            >
              <title>{`${edge.src}–${edge.dst} ρ=${edge.weight ?? '—'} q=${edge.p_adj ?? '—'}`}</title>
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
      <p className="px-3 pb-2 text-[10px] text-slate-500">节点=资产 · 边=同期相关 · 线宽与透明度=|ρ|</p>
    </div>
  );
}

export default GraphView;

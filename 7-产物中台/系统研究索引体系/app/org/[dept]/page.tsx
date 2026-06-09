import { notFound } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Circle } from 'lucide-react';
import { getOrgTreeWithStatus } from '@/lib/org-data';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/status-inference';
import type { NodeColor } from '@/lib/status-inference';
import type { OrgNode as OrgNodeType } from '@/lib/org-types';

const DEPT_COLORS: Record<string, string> = {
  trading: 'bg-blue-500',
  dream: 'bg-purple-500',
  governance: 'bg-amber-500',
  knowledge: 'bg-emerald-500',
  hr: 'bg-pink-500',
  cfo: 'bg-orange-500',
  support: 'bg-slate-500',
};

function NodeRow({ node, deptId, subId }: { node: OrgNodeType; deptId: string; subId: string }) {
  const color: NodeColor = node.inferredStatus || 'gray';
  return (
    <Link
      href={`/org/${deptId}/${subId}/${node.id}`}
      className="flex items-center gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2.5 hover:shadow-sm hover:border-gray-300 transition-all"
    >
      <Circle className="h-2.5 w-2.5" fill={STATUS_COLORS[color]} stroke={STATUS_COLORS[color]} />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-gray-900">{node.name}</div>
        {node.skill && (
          <div className="text-xs text-gray-400 font-mono">{node.skill}</div>
        )}
      </div>
      <span className="text-xs text-gray-400">{STATUS_LABELS[color]}</span>
    </Link>
  );
}

export default async function DeptPage({ params }: { params: { dept: string } }) {
  const data = getOrgTreeWithStatus();
  const dept = data.company.departments.find((d) => d.id === params.dept);

  if (!dept) notFound();

  const allNodes = dept.subsystems.flatMap((s) => s.nodes);
  const counts = { green: 0, amber: 0, red: 0, gray: 0 };
  for (const n of allNodes) {
    const c = n.inferredStatus || 'gray';
    counts[c]++;
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/org" className="hover:text-blue-600 transition-colors">
          公司架构
        </Link>
        <span>/</span>
        <span className="text-gray-900 font-medium">{dept.name}</span>
      </nav>

      <div className={['rounded-xl p-6 text-white', DEPT_COLORS[dept.id] || 'bg-gray-400'].join(' ')}>
        <h1 className="text-2xl font-bold">{dept.name}</h1>
        <div className="mt-2 flex gap-3 text-sm opacity-80">
          <span>{dept.subsystems.length}个子系统</span>
          <span>·</span>
          <span>{dept.node_count}个节点</span>
        </div>
        <div className="mt-2 flex gap-3 text-xs">
          <span>🟢 {counts.green} 正常</span>
          <span>🟡 {counts.amber} 等待</span>
          <span>🔴 {counts.red} 异常</span>
          <span>⚪ {counts.gray} 待机</span>
        </div>
      </div>

      {dept.subsystems.map((sub) => (
        <div key={sub.id} className="rounded-xl border border-gray-200 bg-white p-4 space-y-3">
          <h2 className="text-lg font-semibold text-gray-900">{sub.name}</h2>
          <div className="space-y-2">
            {sub.nodes.map((node) => (
              <NodeRow key={node.id} node={node} deptId={dept.id} subId={sub.id} />
            ))}
          </div>
        </div>
      ))}

      <Link
        href="/org"
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-blue-600"
      >
        <ArrowLeft className="h-4 w-4" />
        返回公司架构
      </Link>
    </div>
  );
}

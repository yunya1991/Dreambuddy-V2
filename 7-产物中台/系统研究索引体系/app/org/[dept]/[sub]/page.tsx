import { notFound } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import { getOrgTreeWithStatus } from '@/lib/org-data';
import type { OrgNode } from '@/lib/org-types';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/status-inference';

function NodeCard({ node, deptId, subId }: { node: OrgNode; deptId: string; subId: string }) {
  const color = node.inferredStatus || 'gray';
  const statusColor = STATUS_COLORS[color];

  return (
    <Link
      href={`/org/${deptId}/${subId}/${node.id}`}
      className="block rounded-lg border border-gray-200 bg-white p-4 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-900">{node.name}</h3>
          {node.skill && (
            <p className="text-xs text-gray-400 font-mono mt-0.5">{node.skill}</p>
          )}
          {node.inferredReason && (
            <p className="text-xs text-gray-500 mt-1">{node.inferredReason}</p>
          )}
        </div>
        <span
          className="flex-shrink-0 rounded px-2 py-1 text-xs text-white font-medium"
          style={{ backgroundColor: statusColor }}
        >
          {STATUS_LABELS[color]}
        </span>
      </div>
    </Link>
  );
}

export default async function SubPage({ params }: { params: { dept: string; sub: string } }) {
  const data = getOrgTreeWithStatus();
  const dept = data.company.departments.find((d) => d.id === params.dept);
  if (!dept) notFound();

  const sub = dept.subsystems.find((s) => s.id === params.sub);
  if (!sub) notFound();

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/org" className="hover:text-blue-600">公司架构</Link>
        <span>/</span>
        <Link href={`/org/${dept.id}`} className="hover:text-blue-600">{dept.name}</Link>
        <span>/</span>
        <span className="text-gray-900 font-medium">{sub.name}</span>
      </nav>

      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <h1 className="text-xl font-bold text-gray-900">{sub.name}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {dept.name} · {sub.node_count}个节点
        </p>
      </div>

      <div className="space-y-3">
        {sub.nodes.map((node) => (
          <NodeCard key={node.id} node={node} deptId={dept.id} subId={sub.id} />
        ))}
      </div>

      <Link
        href={`/org/${dept.id}`}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-blue-600"
      >
        <ArrowLeft className="h-4 w-4" />
        返回{dept.name}
      </Link>
    </div>
  );
}

'use client';

import Link from 'next/link';
import type { OrgDepartment, OrgSubsystem, OrgNode } from '@/lib/org-types';
import { STATUS_COLORS } from '@/lib/status-inference';

interface Props {
  departments: OrgDepartment[];
  companyName: string;
  stats: Record<string, number>;
}

const DEPT_BARS: Record<string, string> = {
  trading: '#60a5fa', dream: '#fbbf24', governance: '#a78bfa',
  knowledge: '#fb923c', hr: '#d1d5db', cfo: '#d1d5db', support: '#34d399',
};

export default function OrgTree({ departments, companyName, stats }: Props) {
  // Split into large (3+ subsystems or 10+ nodes) and small
  const large = departments.filter(d => d.node_count >= 10 || d.subsystems.length >= 3);
  const small = departments.filter(d => d.node_count < 10 && d.subsystems.length < 3);

  return (
    <div className="space-y-2">
      {/* Company header */}
      <div className="rounded-xl border border-gray-200 bg-white px-5 py-4">
        <h1 className="text-base font-semibold text-gray-900">{companyName}</h1>
        <div className="flex gap-5 text-xs text-gray-400 mt-1.5">
          <span>{departments.length}部门</span>
          <span>{stats.total_nodes || departments.reduce((s,d)=>s+d.node_count,0)}节点</span>
          <span>{departments.reduce((s,d)=>s+d.subsystems.length,0)}子系统</span>
        </div>
      </div>

      {/* Large departments (full width) */}
      {large.map(dept => (
        <DeptCard key={dept.id} dept={dept} />
      ))}

      {/* Small departments (2 per row) */}
      <div className="grid grid-cols-2 gap-3">
        {small.map(dept => (
          <DeptCard key={dept.id} dept={dept} compact />
        ))}
      </div>
    </div>
  );
}

/* ──── Department Card ──── */
function DeptCard({ dept, compact }: { dept: OrgDepartment; compact?: boolean }) {
  const barColor = DEPT_BARS[dept.id] || '#d1d5db';
  const activeCount = dept.subsystems.reduce((s, sub) =>
    s + sub.nodes.filter(n => n.inferredStatus === 'green').length, 0);
  const hasActive = activeCount > 0;

  return (
    <div className="flex gap-0 rounded-xl border border-gray-200 bg-white overflow-hidden">
      {/* Color bar */}
      <div className="w-1 flex-shrink-0" style={{ background: barColor }} />

      <div className="flex-1 p-4">
        {/* Header */}
        <Link href={`/org/${dept.id}`} className="flex items-center gap-2 mb-1.5 group">
          <span className="w-2 h-2 rounded-full flex-shrink-0"
            style={{ background: hasActive ? '#10b981' : '#d1d5db' }} />
          <span className="text-sm font-medium text-gray-900 group-hover:text-blue-600">{dept.name}</span>
          <span className="text-xs text-gray-400">{dept.node_count}节点</span>
        </Link>

        {/* Subsystems */}
        <div className={compact ? '' : 'ml-1'}>
          {dept.subsystems.map(sub => (
            <SubsystemRow key={sub.id} sub={sub} deptId={dept.id} compact={compact} />
          ))}
        </div>
      </div>
    </div>
  );
}

/* ──── Subsystem Row ──── */
function SubsystemRow({ sub, deptId, compact }: { sub: OrgSubsystem; deptId: string; compact?: boolean }) {
  return (
    <div className="pl-3 border-l border-dashed border-gray-200 mt-2 first:mt-0">
      <div className="text-[11px] text-gray-400 mb-1.5">{sub.name}</div>
      <div className="flex flex-wrap gap-1.5">
        {sub.nodes.map(node => (
          <NodeTag key={node.id} node={node} deptId={deptId} subId={sub.id} />
        ))}
      </div>
    </div>
  );
}

/* ──── Node Tag ──── */
function NodeTag({ node, deptId, subId }: { node: OrgNode; deptId: string; subId: string }) {
  const color = node.inferredStatus || 'gray';
  const isGreen = color === 'green';
  const isAmber = color === 'amber';
  const isRed = color === 'red';
  const isGray = color === 'gray';

  const style = isGreen
    ? 'border-green-200 text-green-700 bg-green-50'
    : isAmber
    ? 'border-amber-200 text-amber-700 bg-amber-50'
    : isRed
    ? 'border-red-200 text-red-700 bg-red-50'
    : 'border-gray-150 text-gray-400 bg-gray-50/50';

  return (
    <Link
      href={`/org/${deptId}/${subId}/${node.id}`}
      className={`inline-flex text-[11px] px-2 py-1 rounded border cursor-pointer hover:shadow-sm transition-all ${style}`}
    >
      {node.name}
    </Link>
  );
}

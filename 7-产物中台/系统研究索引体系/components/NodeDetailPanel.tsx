import Link from 'next/link';
import { ArrowLeft, BookOpen, GitCommit, Hash } from 'lucide-react';
import type { OrgNode } from '@/lib/org-types';
import { STATUS_COLORS, STATUS_LABELS } from '@/lib/status-inference';

interface NodeDetailPanelProps {
  node: OrgNode;
  deptName: string;
  subName: string;
  deptId: string;
}

export default function NodeDetailPanel({ node, deptName, subName, deptId }: NodeDetailPanelProps) {
  const color = node.inferredStatus || 'gray';
  const statusColor = STATUS_COLORS[color];
  const statusLabel = STATUS_LABELS[color];

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link href="/org" className="hover:text-blue-600 transition-colors">
          公司架构
        </Link>
        <span>/</span>
        <Link href={`/org/${deptId}`} className="hover:text-blue-600 transition-colors">
          {deptName}
        </Link>
        <span>/</span>
        <span className="text-gray-700">{subName}</span>
        <span>/</span>
        <span className="text-gray-900 font-medium">{node.name}</span>
      </nav>

      {/* Header */}
      <div className="rounded-xl border border-gray-200 bg-white p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <h1 className="text-2xl font-bold text-gray-900">{node.name}</h1>
            <p className="mt-1 text-sm text-gray-500">
              子系统: {subName} · 部门: {deptName}
            </p>
          </div>
          {/* Status indicator */}
          <div
            className="flex-shrink-0 rounded-lg px-3 py-2 text-white text-sm font-medium"
            style={{ backgroundColor: statusColor }}
          >
            {statusLabel}
          </div>
        </div>

        {/* Status reason */}
        {node.inferredReason && (
          <div className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600">
            📊 {node.inferredReason}
          </div>
        )}
      </div>

      {/* Details */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 space-y-4">
        <h2 className="text-lg font-semibold text-gray-900">节点信息</h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {node.skill && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-gray-400">
                <BookOpen className="h-3.5 w-3.5" />
                关联技能
              </div>
              <div className="text-sm font-mono text-gray-700">{node.skill}</div>
            </div>
          )}

          {node.version && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-gray-400">
                <GitCommit className="h-3.5 w-3.5" />
                版本
              </div>
              <div className="text-sm text-gray-700">{node.version}</div>
            </div>
          )}

          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-xs text-gray-400">
              <Hash className="h-3.5 w-3.5" />
              节点ID
            </div>
            <div className="text-sm font-mono text-gray-700">{node.id}</div>
          </div>
        </div>

        {node.description && (
          <div className="space-y-1">
            <div className="text-xs text-gray-400">描述</div>
            <div className="text-sm text-gray-600 leading-relaxed">{node.description}</div>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <Link
          href="/org"
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-4 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          返回公司架构
        </Link>
        <Link
          href="/feed"
          className="inline-flex items-center gap-1.5 rounded-lg bg-gray-900 px-4 py-2 text-sm text-white hover:bg-gray-800 transition-colors"
        >
          查看产物中心
        </Link>
      </div>
    </div>
  );
}
